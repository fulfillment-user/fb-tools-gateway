"""
FB Tools Gateway -- auth service.

Sits behind Caddy's `forward_auth` directive: for every request to
tools.fulfillmentbridge.com/<app-slug>/..., Caddy calls GET /verify on this
service first. We look at the session cookie, work out who's asking, check
config.yaml for whether that app is switched on and whether this user is
allowed into it, and answer 200 (let them through) or 401/403 (Caddy sends
them to /login or shows "not authorized").

Also serves the actual /login page, a simple landing page listing each
user's own apps, and an admin-only access-log viewer -- all in one small
service so there's exactly one place that knows about users and apps.

Editing config.yaml (add a user, flip an app to public) and pushing to git
is the entire "admin panel" -- see docs/RUNBOOK.md in the repo root.
"""
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import bcrypt
import yaml
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

CONFIG_PATH = Path(os.environ.get("GATEWAY_CONFIG", "/config/config.yaml"))
LOG_DB_PATH = Path(os.environ.get("GATEWAY_LOG_DB", "/data/access_log.sqlite3"))
SESSION_SECRET = os.environ["SESSION_SECRET"]  # required -- fail loudly if missing

app = FastAPI(title="FB Tools Gateway")
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, same_site="lax",
                    https_only=os.environ.get("COOKIE_INSECURE") != "1")


# ---------------------------------------------------------------------------
# Config loading -- re-read on every request. These configs are tiny (a few
# hundred users/apps at most) and this is an internal tool, not a
# high-traffic service, so the simplicity of "no cache to invalidate" beats
# the cost of a re-read. A new deploy (git push) is still the only way to
# change it -- this just avoids needing a process restart on top of that.
# ---------------------------------------------------------------------------
def load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def get_app_cfg(cfg, slug):
    return (cfg.get("apps") or {}).get(slug)


def get_user_cfg(cfg, username):
    return (cfg.get("users") or {}).get(username)


def get_role_cfg(cfg, role_name):
    return (cfg.get("roles") or {}).get(role_name)


def user_apps(cfg, user_cfg):
    """Effective set of app slugs a user can reach: the union of every role
    they hold's apps, plus any one-off 'apps' listed directly on the user
    (kept as an escape hatch for a grant that doesn't warrant its own role)."""
    apps = set(user_cfg.get("apps") or [])
    for role_name in user_cfg.get("roles") or []:
        role_cfg = get_role_cfg(cfg, role_name) or {}
        apps.update(role_cfg.get("apps") or [])
    return apps


def user_can_access(cfg, user_cfg, slug):
    if user_cfg.get("is_admin"):
        return True
    allowed = user_apps(cfg, user_cfg)
    return "*" in allowed or slug in allowed


# ---------------------------------------------------------------------------
# Access log -- SQLite on a mounted volume so it survives redeploys. Every
# verify/login attempt gets one row: who, which app, when, what happened.
# ---------------------------------------------------------------------------
def _db():
    LOG_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(LOG_DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS access_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            username TEXT,
            app_slug TEXT,
            outcome TEXT NOT NULL,
            ip TEXT
        )
    """)
    return conn


def log_access(username, app_slug, outcome, ip):
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = _db()
    conn.execute(
        "INSERT INTO access_log (ts, username, app_slug, outcome, ip) VALUES (?, ?, ?, ?, ?)",
        (ts, username, app_slug, outcome, ip),
    )
    conn.commit()
    conn.close()
    # Also to stdout -- if this ever runs somewhere with centralized log
    # collection (Cloud Logging, etc.) that's a second, durable copy for free.
    print(f"[access] {ts} user={username!r} app={app_slug!r} outcome={outcome} ip={ip}")


def recent_log(limit=200):
    conn = _db()
    rows = conn.execute(
        "SELECT ts, username, app_slug, outcome, ip FROM access_log ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return rows


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "-")


# ---------------------------------------------------------------------------
# Forward-auth endpoint -- Caddy calls this before every proxied request.
# ---------------------------------------------------------------------------
@app.get("/verify")
def verify(request: Request):
    cfg = load_config()
    uri = request.headers.get("x-forwarded-uri", "/")
    slug = uri.strip("/").split("/", 1)[0] if uri.strip("/") else ""
    ip = client_ip(request)
    username = request.session.get("user")

    app_cfg = get_app_cfg(cfg, slug)
    if app_cfg is None:
        log_access(username, slug, "unknown_app", ip)
        return PlainTextResponse("Not found", status_code=404)

    if not app_cfg.get("public", False):
        log_access(username, slug, "app_offline", ip)
        return PlainTextResponse("This tool isn't switched on right now.", status_code=503)

    if not username:
        log_access(None, slug, "no_session", ip)
        return PlainTextResponse("Login required", status_code=401)

    user_cfg = get_user_cfg(cfg, username)
    if not user_cfg:
        # Session refers to a user removed from config.yaml since login.
        log_access(username, slug, "unknown_user", ip)
        return PlainTextResponse("Login required", status_code=401)

    if not user_can_access(cfg, user_cfg, slug):
        log_access(username, slug, "denied", ip)
        return PlainTextResponse("You don't have access to this tool.", status_code=403)

    log_access(username, slug, "allowed", ip)
    # Caddy's forward_auth copies named response headers into the request it
    # then proxies to the real backend (see Caddyfile's copy_headers) -- this
    # is how a backend app (e.g. leads-crm) knows who's logged in, and
    # optionally their own Calendly link, without implementing any auth or
    # reading config.yaml itself. Only trustworthy because that backend is
    # never reachable except through Caddy -- see docker-compose.yml.
    headers = {"X-Auth-User": username}
    calendly_url = user_cfg.get("calendly_url")
    if calendly_url:
        headers["X-Auth-Calendly"] = calendly_url
    return PlainTextResponse("OK", headers=headers)


# ---------------------------------------------------------------------------
# Login / logout / landing page
# ---------------------------------------------------------------------------
LOGIN_PAGE = """
<!doctype html><title>FB Tools</title>
<meta name=viewport content="width=device-width, initial-scale=1">
<style>
  body {{ font-family: -apple-system, sans-serif; max-width: 360px; margin: 80px auto; color: #222; }}
  h1 {{ font-size: 20px; }}
  input {{ width: 100%; padding: 8px; margin-top: 4px; box-sizing: border-box; }}
  label {{ font-size: 13px; color: #555; display: block; margin-top: 14px; }}
  button {{ margin-top: 20px; padding: 8px 18px; width: 100%; }}
  .err {{ background: #fee; border: 1px solid #c33; padding: 8px; margin-top: 14px; font-size: 13px; }}
</style>
<h1>FB Tools</h1>
{error}
<form method=post action="/login?next={next_url}">
  <label>Username<input name=username autofocus></label>
  <label>Password<input name=password type=password></label>
  <button type=submit>Log in</button>
</form>
"""


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next: str = "/"):
    return LOGIN_PAGE.format(error="", next_url=next)


@app.post("/login")
def login_submit(request: Request, username: str = Form(...), password: str = Form(...),
                  next: str = "/"):
    cfg = load_config()
    user_cfg = get_user_cfg(cfg, username)
    ip = client_ip(request)
    ok = False
    if user_cfg:
        ok = bcrypt.checkpw(password.encode(), user_cfg["password_hash"].encode())
    if not ok:
        log_access(username, "-", "login_failed", ip)
        time.sleep(0.5)  # slow down brute-force guessing a little
        return HTMLResponse(
            LOGIN_PAGE.format(error='<div class="err">Wrong username or password.</div>',
                               next_url=next),
            status_code=401,
        )
    request.session["user"] = username
    log_access(username, "-", "login_ok", ip)
    return RedirectResponse(url=next or "/", status_code=302)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=302)


LANDING_PAGE = """
<!doctype html><title>FB Tools</title>
<meta name=viewport content="width=device-width, initial-scale=1">
<style>
  body {{ font-family: -apple-system, sans-serif; max-width: 480px; margin: 60px auto; color: #222; }}
  h1 {{ font-size: 20px; }}
  a.tool {{ display: block; padding: 12px 14px; margin-top: 10px; border: 1px solid #ddd;
            border-radius: 8px; text-decoration: none; color: #222; }}
  a.tool:hover {{ background: #f7f7f7; }}
  .top {{ display: flex; justify-content: space-between; align-items: center; }}
  .top a {{ font-size: 13px; color: #888; }}
</style>
<div class=top><h1>FB Tools</h1><a href="/logout">Log out ({username})</a></div>
{tools}
"""


@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    username = request.session.get("user")
    if not username:
        return RedirectResponse(url="/login?next=/", status_code=302)
    cfg = load_config()
    user_cfg = get_user_cfg(cfg, username)
    if not user_cfg:
        request.session.clear()
        return RedirectResponse(url="/login", status_code=302)

    rows = []
    for slug, app_cfg in (cfg.get("apps") or {}).items():
        if not app_cfg.get("public", False):
            continue
        if not user_can_access(cfg, user_cfg, slug):
            continue
        rows.append(f'<a class=tool href="/{slug}/">{app_cfg.get("display_name", slug)}</a>')
    if user_cfg.get("is_admin"):
        rows.append('<a class=tool href="/admin">Access log (admin)</a>')

    tools_html = "\n".join(rows) if rows else "<p>No tools switched on for your account yet.</p>"
    return LANDING_PAGE.format(username=username, tools=tools_html)


# ---------------------------------------------------------------------------
# Admin: access log viewer
# ---------------------------------------------------------------------------
ADMIN_PAGE = """
<!doctype html><title>FB Tools - Access log</title>
<meta name=viewport content="width=device-width, initial-scale=1">
<style>
  body {{ font-family: -apple-system, sans-serif; max-width: 900px; margin: 40px auto; color: #222; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
  th, td {{ text-align: left; padding: 6px 10px; border-bottom: 1px solid #eee; }}
  th {{ color: #666; font-weight: 600; }}
  .allowed {{ color: #2a7; }} .denied, .login_failed {{ color: #c33; }}
  a {{ font-size: 13px; color: #888; }}
</style>
<p><a href="/">&larr; Back</a></p>
<h1>Access log (last {n})</h1>
<table>
<tr><th>Time (UTC)</th><th>User</th><th>Tool</th><th>Result</th><th>IP</th></tr>
{rows}
</table>
"""


@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request):
    username = request.session.get("user")
    cfg = load_config()
    user_cfg = get_user_cfg(cfg, username) if username else None
    if not user_cfg or not user_cfg.get("is_admin"):
        return RedirectResponse(url="/login?next=/admin", status_code=302)

    rows_html = "\n".join(
        f"<tr><td>{ts}</td><td>{u or '-'}</td><td>{a or '-'}</td>"
        f"<td class='{o}'>{o}</td><td>{ip}</td></tr>"
        for ts, u, a, o, ip in recent_log()
    )
    return ADMIN_PAGE.format(n=200, rows=rows_html or "<tr><td colspan=5>No activity yet.</td></tr>")
