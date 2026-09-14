# FB Tools Gateway

Login-gated, per-user access to Fulfillment Bridge's internal web tools,
hosted at `tools.fulfillmentbridge.com`:

- **Quotation Tool** -- code lives in the fb-rate-engine repo; this repo
  just knows where to fetch and how to build it (`apps/quotation-tool/`).
- **Leads CRM** -- one pipeline for every lead regardless of source (CEPEX,
  Articrea, whatever's added next). Built directly in this repo
  (`apps/leads-crm/`), since it doesn't have (or need) a product repo of its
  own. See `apps/leads-crm/README.md`.

- **Operating this day-to-day** (add a user, switch a tool on/off, see who's
  used what): `docs/RUNBOOK.md` -- plain-language, no server access needed,
  just edit-and-push.
- **One-time infrastructure setup**: `docs/DEVOPS_HANDOFF.md`.
- **How it works**: one small login service (`auth-service/`) that Caddy
  (`Caddyfile`) checks before letting anyone through to a tool. Each tool is
  its own container -- either built from its own product repo (see
  `apps/quotation-tool/source.yaml`) or, for something built specifically
  for this gateway, straight from a folder in this repo (`repo: local`, see
  `apps/leads-crm/source.yaml`) -- listed in `config/config.yaml` along with
  who's allowed to open it.
