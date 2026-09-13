# FB Tools Gateway

Login-gated, per-user access to Fulfillment Bridge's internal web tools
(quotation calculator, and more over time), hosted at
`tools.fulfillmentbridge.com`.

- **Operating this day-to-day** (add a user, switch a tool on/off, see who's
  used what): `docs/RUNBOOK.md` -- plain-language, no server access needed,
  just edit-and-push.
- **One-time infrastructure setup**: `docs/DEVOPS_HANDOFF.md`.
- **How it works**: one small login service (`auth-service/`) that Caddy
  (`Caddyfile`) checks before letting anyone through to a tool. Each tool is
  its own container, built from its own repo, listed in `config/config.yaml`
  along with who's allowed to open it.

Nothing in this repo runs any of the actual tools' business logic -- it only
decides who gets to reach them.
