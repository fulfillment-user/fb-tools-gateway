# FB Tools Gateway -- devops handoff

One-time setup requested. Once this is in place, Kais/Claude operate it
entirely by editing this repo and pushing -- **including onboarding brand
new tools** -- with zero further devops involvement. That's a deliberate
design goal here, not an afterthought: see "Why one script, one pipeline"
below if the shape of the ask looks unusual.

## What this is

A small reverse-proxy + login gate in front of a set of internal tools
(currently one: the FB Quotation Tool), reachable at
`tools.fulfillmentbridge.com/<tool-slug>/` with per-user, per-tool access
control (via roles) and an access log (who opened what, when).

Pieces, all in this repo:

- **Caddy** (`Caddyfile`) -- stock `caddy:2.8-alpine` image. Terminates TLS
  (automatic via Let's Encrypt against the real domain), reverse-proxies each
  `/<slug>/*` path to that tool's container, gated by a `forward_auth` call
  to `auth-service` first.
- **auth-service** (`auth-service/`) -- FastAPI. Login page, session
  cookies, the `/verify` endpoint Caddy checks before every proxied request,
  and an admin-only access-log page at `/admin`. Reads `config/config.yaml`
  (who exists, what roles they hold, what's switched on) at request time.
- **apps/`<slug>`/source.yaml** -- one per tool, e.g. `apps/quotation-tool/`.
  Each just says where that tool's actual code lives (its own repo, a git
  ref, which Dockerfile) -- the code itself is NOT copied into this repo.
- **scripts/build_and_deploy.py** -- reads every `apps/*/source.yaml`,
  clones that repo at that ref, builds+tags+pushes its image, does the same
  for `auth-service/`, then runs `docker compose up -d`. **This is the one
  thing your pipeline needs to run.**

## What we need from you (one time)

1. **One pipeline**, triggered on push to *this* repo, that runs:
   ```
   pip install -r scripts/requirements.txt
   REGISTRY=<your Artifact Registry path> python3 scripts/build_and_deploy.py
   ```
   That's the entire build step, regardless of how many tools exist today or
   get added in six months -- the script discovers them from `apps/*/`.

2. **Somewhere for that pipeline to run with docker + git available**, and
   authenticated to your registry (`gcloud auth configure-docker` or
   equivalent) before the script runs.

3. **Where it actually deploys**: the script's last step is `docker compose
   up -d`, which needs to run *on* the box serving traffic (a small VM is
   plenty -- this is low-volume internal tooling). Two ways to wire that,
   whichever fits how you already do this for other GCP projects:
   - Run the whole pipeline (build step included) directly on that VM, so
     the final `docker compose up -d` is already local -- simplest.
   - Build elsewhere (a CI runner) with `SKIP_DEPLOY=1`, push images, then
     have your existing deploy mechanism pull and restart on the VM.

   If you'd rather target Cloud Run/GKE instead of a VM: flag it back to us
   first. This compose setup assumes plain container-to-container networking
   (`reverse_proxy quotation-tool:8505` resolves by service name on one
   docker network), which Cloud Run doesn't give you for free -- each
   backend would need to be a private service with the gateway
   authenticating to it via a Google-signed identity token per request,
   which isn't built. A VM is the fast path; Cloud Run is doable but is
   additional work we haven't done.

4. **Persistent volumes**:
   - `caddy_data` / `caddy_config` -- so the TLS cert isn't re-issued from
     scratch on every redeploy.
   - `gateway_log_data` -- the access-log SQLite file. Losing it loses
     history, not access control (`config/config.yaml` in git is the source
     of truth for who can log in).

5. **DNS**: point `tools.fulfillmentbridge.com` at this box's static IP.

6. **Firewall**: only 80/443 open to the internet. Nothing else (8505, 8000,
   etc.) should be externally reachable -- only Caddy talks to those, over
   the docker-internal network.

7. **`SESSION_SECRET`** env var: a random 64-char hex string
   (`python3 -c "import secrets; print(secrets.token_hex(32))"`), via your
   normal secrets mechanism, not committed to git.

8. **`ANTHROPIC_API_KEY`** env var, for leads-crm's "Suggest follow-up"
   feature (calls the Anthropic API server-side) -- Kais has this key
   already, same secrets mechanism as `SESSION_SECRET`.

## Why one script, one pipeline

The obvious alternative -- a pipeline per tool's own repo -- means every new
tool needs a devops ticket to wire its pipeline before anyone can use it.
Routing every tool through one manifest (`apps/*/source.yaml`) in this one
repo means the pipeline you set up today already knows how to build a tool
that doesn't exist yet: adding one is a plain git commit to this repo (a new
`apps/<slug>/source.yaml`, a `Caddyfile` route, a `config.yaml` entry, a
compose service block), which the existing trigger picks up automatically.
That's a one-time cost for you now in exchange for zero recurring devops
work as the tool list grows -- see `docs/RUNBOOK.md`'s "Onboard a brand new
app" for exactly what that commit looks like.

## What we'll own going forward

Everything in `config/config.yaml` (users, roles, which tool is switched
on), `Caddyfile` routes, and `apps/*/source.yaml` manifests -- all via normal
commits to this repo, picked up by the pipeline above. No further devops
involvement expected for adding people, adding roles, switching tools on/off,
or onboarding new tools.
