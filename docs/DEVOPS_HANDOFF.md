# FB Tools Gateway -- devops handoff

One-time setup requested. Once this is in place, Kais/Claude operate it
entirely by editing config in git (see `RUNBOOK.md`) -- no further devops
involvement needed for day-to-day changes (adding users, switching a tool on,
onboarding a new tool's Caddy route).

## What this is

A small reverse-proxy + login gate in front of a set of internal tools
(currently one: the FB Quotation Tool), so they're reachable from the
internet at `tools.fulfillmentbridge.com/<tool-slug>/` with per-user,
per-tool access control and an access log (who opened what, when).

Three pieces, packaged as `docker-compose.yml` in this repo:

- **caddy** -- stock `caddy:2.8-alpine` image, config mounted from
  `Caddyfile`. Terminates TLS (automatic via Let's Encrypt against the real
  domain), reverse-proxies each `/<slug>/*` path to that tool's container,
  gated by a `forward_auth` call to `auth-service` first.
- **auth-service** -- built from `auth-service/` in this repo (FastAPI). Login
  page, session cookies, the `/verify` endpoint Caddy checks before every
  proxied request, and an admin-only access-log page at `/admin`. Reads
  `config/config.yaml` (who exists, what they can open, what's switched on)
  at request time -- no restart needed to pick up a new config, only a
  redeploy (which a config-only push already triggers via the pipeline).
- **quotation-tool** -- built from `Dockerfile.quotation-tool` in the
  **fb-rate-engine** repo (separate repo, separate pipeline). Not reachable
  directly -- only Caddy should be able to reach it.

## What we need from you

1. **Two build pipelines**, your normal push-to-git -> Docker build pattern:
   - This repo (`fb_tools_gateway`) -> builds `auth-service/Dockerfile` ->
     push to your Artifact Registry.
   - `fb-rate-engine` repo -> builds `Dockerfile.quotation-tool` at repo root
     -> push to Artifact Registry. (More Dockerfiles will likely show up in
     other app repos over time as more tools get onboarded -- same pattern
     each time.)

2. **Somewhere to run `docker compose up -d`** with the images above --
   simplest is a single small VM (e2-small is plenty for this traffic level;
   everything here is low-volume internal tooling, not a public product).
   If you'd rather run this on Cloud Run/GKE instead of a VM, flag it back to
   us first: this compose file assumes plain container-to-container
   networking (`reverse_proxy quotation-tool:8505` resolves by service name),
   which Cloud Run doesn't give you for free -- each backend service would
   need to be private (`--no-allow-unauthenticated`) with the gateway
   authenticating to it via a Google-signed identity token per request, which
   isn't built yet. A VM is the fast path; Cloud Run is doable but is
   additional work we haven't done.

3. **Persistent volumes** for:
   - `caddy_data` / `caddy_config` -- so the TLS certificate isn't
     re-issued from scratch on every redeploy.
   - `gateway_log_data` -- the access-log SQLite file. Losing this loses
     history, not access control (config.yaml is the source of truth for
     who can log in).

4. **DNS**: point `tools.fulfillmentbridge.com` at this box's static IP
   (A record), or CNAME to it if it's behind a load balancer.

5. **Firewall**: only 80/443 need to be open to the internet on this box.
   Nothing else (8505, 8000, etc.) should be externally reachable -- only
   Caddy talks to those, over the Docker-internal network.

6. **`SESSION_SECRET`**: a random 64-char hex string (`python3 -c
   "import secrets; print(secrets.token_hex(32))"`), stored via your normal
   secrets mechanism and injected as an env var -- not committed to git. We
   have one generated locally in a gitignored `.env` for reference/first
   deploy; rotate it into your standard secret store rather than reusing it
   long-term.

## What we'll own going forward

Editing `config/config.yaml` (users, passwords-as-hashes, which tool is
switched on) and adding new `handle /<slug>/*` blocks to `Caddyfile` as more
tools get onboarded -- all via normal commits to this repo. Your pipeline
picking those commits up and redeploying is the only ongoing dependency on
the CI side.
