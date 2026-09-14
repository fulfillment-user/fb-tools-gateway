"""
Leads CRM -- one pipeline for every lead regardless of source (CEPEX,
Articrea, or whatever's added next). See db.py for the schema/merge logic
and seed.py for how source data lands here in the first place.

Runs behind the FB Tools Gateway at tools.fulfillmentbridge.com/leads-crm/ --
routes are defined WITH that prefix baked in (BASE below) rather than via
Flask's url_for/SCRIPT_NAME machinery, since Caddy proxies this path as-is
(no prefix-stripping), matching the same convention quotation-tool uses.

Who's acting: the gateway's auth-service sets an X-Auth-User response
header on a successful /verify call, which Caddy copies into the request it
forwards here (see Caddyfile) -- read via current_user() below. This is
only trustworthy because leads-crm is never reachable except through Caddy
(not exposed on the docker network's host ports) -- see docker-compose.yml.
"""
from flask import Flask, request, redirect, abort
import json

from . import db, llm
from .seed import main as run_seed

BASE = "/leads-crm"

app = Flask(__name__)


def current_user() -> str:
    return request.headers.get("X-Auth-User", "unknown")


def current_display_name() -> str:
    return request.headers.get("X-Auth-DisplayName") or current_user()


def current_calendly() -> str:
    return request.headers.get("X-Auth-Calendly") or llm.DEFAULT_CALENDLY_URL


@app.route("/")
def root_redirect():
    # Only ever hit when running standalone (locally, or direct-to-container
    # without Caddy in front) -- through the real gateway, Caddy's own "/"
    # route goes to auth-service, never here. Convenience only.
    return redirect(f"{BASE}/")


CSS = """
<style>
  body { font-family: -apple-system, sans-serif; max-width: 1000px; margin: 30px auto; color: #222; padding: 0 16px; }
  h1 { font-size: 20px; margin-bottom: 4px; }
  .sub { color: #666; font-size: 13px; margin-bottom: 20px; }
  table { border-collapse: collapse; width: 100%; font-size: 13.5px; }
  th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid #eee; }
  th { color: #666; font-weight: 600; font-size: 12px; text-transform: uppercase; }
  tr:hover { background: #fafafa; }
  a { color: #1a5fb4; text-decoration: none; }
  a:hover { text-decoration: underline; }
  .filters { display: flex; gap: 10px; margin-bottom: 16px; flex-wrap: wrap; }
  .filters select, .filters input { padding: 6px 8px; font-size: 13px; }
  .stage-pill { display: inline-block; padding: 2px 9px; border-radius: 999px; font-size: 11.5px; font-weight: 600; }
  .stage-new { background: #e8eefc; color: #1a5fb4; }
  .stage-contacted { background: #e6f4ea; color: #1e7e34; }
  .stage-call_scheduled { background: #fff3cd; color: #8a6d00; }
  .stage-negotiating { background: #ffe8cc; color: #a35900; }
  .stage-won { background: #d4edda; color: #155724; }
  .stage-lost, .stage-not_interested { background: #f1f1f1; color: #888; }
  .sources span { display: inline-block; background: #f0f0f0; border-radius: 4px; padding: 1px 6px; margin-right: 4px; font-size: 11px; }
  .back { font-size: 13px; margin-bottom: 14px; display: inline-block; }
  .card { border: 1px solid #eee; border-radius: 8px; padding: 14px 16px; margin-bottom: 14px; }
  .kv { font-size: 13.5px; margin: 3px 0; }
  .kv b { color: #555; display: inline-block; min-width: 90px; }
  form.inline { display: inline; }
  textarea { width: 100%; padding: 8px; font-family: inherit; font-size: 13.5px; box-sizing: border-box; }
  .note { border-bottom: 1px solid #f0f0f0; padding: 8px 0; font-size: 13.5px; }
  .note .meta { color: #999; font-size: 11.5px; }
  pre.raw { background: #fafafa; padding: 10px; font-size: 11.5px; overflow-x: auto; border-radius: 6px; }
</style>
"""


def stage_pill(stage):
    return f'<span class="stage-pill stage-{stage}">{db.STAGE_LABELS.get(stage, stage)}</span>'


@app.route(f"{BASE}/")
def list_leads():
    stage_f = request.args.get("stage", "")
    source_f = request.args.get("source", "")
    q = request.args.get("q", "").strip().lower()

    with db.get_db() as conn:
        rows = conn.execute("SELECT * FROM leads ORDER BY updated_at DESC").fetchall()

    filtered = []
    for r in rows:
        sources = json.loads(r["sources"])
        if stage_f and r["stage"] != stage_f:
            continue
        if source_f and source_f not in sources:
            continue
        if q:
            hay = " ".join(filter(None, [r["name"], r["phone"], r["email"], r["address"]])).lower()
            if q not in hay:
                continue
        filtered.append((r, sources))

    stage_options = "".join(
        f'<option value="{s}"{" selected" if s == stage_f else ""}>{db.STAGE_LABELS[s]}</option>'
        for s in db.STAGES
    )
    rows_html = "".join(
        f"<tr onclick=\"location.href='{BASE}/lead/{r['id']}'\" style='cursor:pointer'>"
        f"<td>{r['name']}</td>"
        f"<td class=sources>{''.join(f'<span>{s}</span>' for s in sources)}</td>"
        f"<td>{r['category'] or '&mdash;'}</td>"
        f"<td>{r['phone'] or '&mdash;'}</td>"
        f"<td>{stage_pill(r['stage'])}</td>"
        f"<td>{r['updated_at'][:10]}</td>"
        f"</tr>"
        for r, sources in filtered
    )

    return CSS + f"""
    <h1>Leads CRM</h1>
    <div class=sub>{len(filtered)} of {len(rows)} leads &middot; logged in as {current_user()}</div>
    <form class=filters method=get>
      <input type=text name=q placeholder="Search name/phone/email/address" value="{q}">
      <select name=stage onchange="this.form.submit()">
        <option value="">All stages</option>
        {stage_options}
      </select>
      <select name=source onchange="this.form.submit()">
        <option value="">All sources</option>
        <option value="cepex"{" selected" if source_f=="cepex" else ""}>CEPEX</option>
        <option value="articrea"{" selected" if source_f=="articrea" else ""}>Articrea</option>
      </select>
      <button type=submit>Filter</button>
    </form>
    <table>
      <tr><th>Name</th><th>Source</th><th>Category</th><th>Phone</th><th>Stage</th><th>Updated</th></tr>
      {rows_html}
    </table>
    """


@app.route(f"{BASE}/lead/<int:lead_id>")
def lead_detail(lead_id):
    with db.get_db() as conn:
        lead = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
        if not lead:
            abort(404)
        notes = conn.execute(
            "SELECT * FROM lead_notes WHERE lead_id=? ORDER BY created_at DESC", (lead_id,)
        ).fetchall()
        history = conn.execute(
            "SELECT * FROM lead_stage_history WHERE lead_id=? ORDER BY created_at DESC", (lead_id,)
        ).fetchall()
        suggestions = conn.execute(
            "SELECT * FROM lead_suggestions WHERE lead_id=? ORDER BY created_at DESC", (lead_id,)
        ).fetchall()

    sources = json.loads(lead["sources"])
    source_data = json.loads(lead["source_data"])

    stage_options = "".join(
        f'<option value="{s}"{" selected" if s == lead["stage"] else ""}>{db.STAGE_LABELS[s]}</option>'
        for s in db.STAGES
    )
    notes_html = "".join(
        f'<div class=note><div class=meta>{n["created_at"]} &middot; {n["author"]}</div>{n["text"]}</div>'
        for n in notes
    ) or "<p style='color:#999'>No notes yet.</p>"
    history_html = "".join(
        f'<div class=note><div class=meta>{h["created_at"]} &middot; {h["author"]}</div>'
        f'{h["from_stage"] or "(new lead)"} &rarr; {db.STAGE_LABELS.get(h["to_stage"], h["to_stage"])}</div>'
        for h in history
    ) or "<p style='color:#999'>No stage changes yet.</p>"
    source_blocks = "".join(
        f"<details><summary>{src} raw data</summary>"
        f"<pre class=raw>{json.dumps(source_data.get(src, {}), indent=2, ensure_ascii=False)}</pre></details>"
        for src in sources
    )
    action_labels = {"email": "Email drafted", "calendly": "Calendly invite drafted",
                      "no_action": "No action recommended"}
    suggestions_html = "".join(
        f'<div class=note><div class=meta>{s["created_at"]} &middot; {s["created_by"]}</div>'
        f'<a href="{BASE}/lead/{lead_id}/suggestion/{s["id"]}">'
        f'{action_labels.get(s["action_type"], s["action_type"])}</a></div>'
        for s in suggestions
    ) or "<p style='color:#999'>No suggestions generated yet.</p>"
    suggest_error = request.args.get("suggest_error")
    suggest_error_html = (f'<div style="background:#fee;border:1px solid #c33;padding:8px;'
                           f'margin-bottom:10px;font-size:13px;">{suggest_error}</div>'
                           if suggest_error else "")

    return CSS + f"""
    <a class=back href="{BASE}/">&larr; All leads</a>
    <h1>{lead['name']}</h1>
    <div class=sub>{stage_pill(lead['stage'])} &middot; sources: {', '.join(sources)}</div>

    <div class=card>
      <div class=kv><b>Phone</b> {lead['phone'] or '&mdash;'}</div>
      <div class=kv><b>Email</b> {lead['email'] or '&mdash;'}</div>
      <div class=kv><b>Address</b> {lead['address'] or '&mdash;'}</div>
      <div class=kv><b>Category</b> {lead['category'] or '&mdash;'}</div>
    </div>

    <div class=card>
      <b>Stage</b>
      <form method=post action="{BASE}/lead/{lead_id}/stage" class=inline>
        <select name=stage onchange="this.form.submit()">{stage_options}</select>
      </form>
      <h4>History</h4>
      {history_html}
    </div>

    <div class=card>
      <h4>Notes</h4>
      <form method=post action="{BASE}/lead/{lead_id}/note">
        <textarea name=text rows=3 placeholder="Call notes, what was discussed, next step..." required></textarea>
        <button type=submit>Add note</button>
      </form>
      {notes_html}
    </div>

    <div class=card>
      <h4>Follow-up suggestions</h4>
      {suggest_error_html}
      <form method=post action="{BASE}/lead/{lead_id}/suggest">
        <button type=submit>Suggest follow-up</button>
      </form>
      {suggestions_html}
    </div>

    <div class=card>
      <h4>Source data</h4>
      {source_blocks}
    </div>
    """


@app.route(f"{BASE}/lead/<int:lead_id>/note", methods=["POST"])
def add_note_route(lead_id):
    text = request.form.get("text", "").strip()
    if text:
        with db.get_db() as conn:
            db.add_note(conn, lead_id, current_user(), text)
    return redirect(f"{BASE}/lead/{lead_id}")


@app.route(f"{BASE}/lead/<int:lead_id>/stage", methods=["POST"])
def set_stage_route(lead_id):
    stage = request.form.get("stage", "")
    if stage in db.STAGES:
        with db.get_db() as conn:
            db.set_stage(conn, lead_id, stage, current_user())
    return redirect(f"{BASE}/lead/{lead_id}")


@app.route(f"{BASE}/lead/<int:lead_id>/suggest", methods=["POST"])
def suggest_route(lead_id):
    with db.get_db() as conn:
        lead = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
        if not lead:
            abort(404)
        notes = conn.execute(
            "SELECT * FROM lead_notes WHERE lead_id=? ORDER BY created_at ASC", (lead_id,)
        ).fetchall()
        try:
            suggestion_id = llm.generate_suggestion(
                conn, lead, notes, current_user(),
                calendly_url=current_calendly(), sender_name=current_display_name())
        except llm.SuggestionError as e:
            from urllib.parse import quote
            return redirect(f"{BASE}/lead/{lead_id}?suggest_error={quote(str(e))}")
    return redirect(f"{BASE}/lead/{lead_id}/suggestion/{suggestion_id}")


# Same template Kais already uses for CEPEX cold-outreach drafts (see e.g.
# cepex_scraper/outreach_drafts/*/*.html) -- a standalone HTML page with a
# "copy formatted email" button that range-selects #email-body and uses
# execCommand('copy'), so pasting into Gmail keeps bold/bullets/links intact
# instead of landing as one flat paragraph. Reused as-is (not the app's own
# CSS/BASE chrome) since the whole point is this page also works as a
# forwarded/saved standalone file, same as the CEPEX ones.
SUGGESTION_PAGE = """<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  body {{ font-family: Arial, Helvetica, sans-serif; max-width: 720px; margin: 24px auto; color: #111; padding: 0 16px; }}
  .backlink {{ font-size: 13px; color: #666; text-decoration: none; }}
  .meta {{ background: #f2f2f2; padding: 10px 14px; border-radius: 6px; margin: 14px 0 18px; font-size: 14px; }}
  .meta b {{ color: #b00; }}
  .reasoning {{ font-size: 12.5px; color: #888; margin-bottom: 16px; }}
  #copybtn {{ background: #1a73e8; color: #fff; border: none; padding: 8px 16px; border-radius: 4px; font-size: 14px; cursor: pointer; margin-bottom: 20px; }}
  #copybtn:active {{ background: #0d5bba; }}
  #status {{ margin-left: 10px; font-size: 13px; color: #067d06; }}
  #email-body p {{ line-height: 1.5; margin: 0 0 14px 0; }}
  #email-body ul {{ margin: 0 0 14px 0; padding-left: 22px; }}
  #email-body li {{ margin-bottom: 6px; line-height: 1.5; }}
  #email-body a {{ color: #1a73e8; }}
</style>
</head>
<body>
  <a class="backlink" href="{lead_url}">&larr; {lead_name}</a>
  <div class="meta">Destinataire : <b>{recipient}</b> &middot; Categorie : {category} &middot; Sources : {sources}</div>
  <div class="reasoning">{reasoning}</div>
  {content}
</body>
</html>"""

COPY_APPARATUS = """
  <button id="copybtn" onclick="copyEmail()">Copier l'email (formate)</button>
  <span id="status"></span>
  <div id="email-body">
    {body}
  </div>
<script>
function copyEmail() {{
  var node = document.getElementById('email-body');
  var range = document.createRange();
  range.selectNodeContents(node);
  var sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
  try {{
    document.execCommand('copy');
    document.getElementById('status').textContent = 'Copie -- collez directement dans Gmail (Cmd+V)';
  }} catch (e) {{
    document.getElementById('status').textContent = 'Copie echouee -- selectionnez le texte manuellement et Cmd+C';
  }}
  sel.removeAllRanges();
}}
</script>
"""


@app.route(f"{BASE}/lead/<int:lead_id>/suggestion/<int:suggestion_id>")
def suggestion_detail(lead_id, suggestion_id):
    with db.get_db() as conn:
        lead = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
        s = conn.execute("SELECT * FROM lead_suggestions WHERE id=? AND lead_id=?",
                          (suggestion_id, lead_id)).fetchone()
        if not lead or not s:
            abort(404)

    sources = ", ".join(json.loads(lead["sources"])) or "&mdash;"
    recipient = lead["email"] or lead["phone"] or "&mdash;"

    if s["action_type"] == "no_action":
        content = "<p style='color:#666'>No action recommended right now -- nothing to send.</p>"
    else:
        content = COPY_APPARATUS.format(body=s["body"] or "")

    return SUGGESTION_PAGE.format(
        lang="fr", title=f"{lead['name']} : Fulfillment Bridge",
        lead_url=f"{BASE}/lead/{lead_id}", lead_name=lead["name"],
        recipient=recipient, category=lead["category"] or "&mdash;", sources=sources,
        reasoning=f"{s['created_at']} &middot; suggested by {s['created_by']} &middot; {s['reasoning'] or ''}",
        content=content,
    )


# Run the (idempotent) seed import at import time, before the first request
# -- simplest way to guarantee it's happened exactly once per fresh volume,
# with no separate init container/step for devops to remember to run.
db.init_db()
run_seed()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8506)
