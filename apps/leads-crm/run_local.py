#!/usr/bin/env python3
"""
Run the Leads CRM standalone on your own machine, no gateway/Docker/login
needed -- for using it today while the real deploy is pending. Requests
arrive with no X-Auth-User header, so every note gets attributed to
"unknown" (see app/main.py's current_user()) rather than a real name --
that's expected here, not a bug; the real per-user attribution only exists
once this runs behind the gateway.

The database lives in local_data/ next to this file (gitignored), separate
from the container's /data volume -- notes you add locally today do NOT
carry over automatically once this is deployed for real. If that data
matters, this file is portable: copy local_data/leads.sqlite3 onto the
server's persistent volume before or instead of letting the container
re-seed from scratch.

For the "Suggest follow-up" feature: put ANTHROPIC_API_KEY=sk-... in a .env
file next to this script (copy .env.example) -- loaded below, never
committed (gitignored). Without it, everything else still works; that one
button just shows an error instead of a draft.

Usage: python3 run_local.py
"""
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load_dotenv(path: Path):
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv(HERE / ".env")
os.environ.setdefault("LEADS_DB", str(HERE / "local_data" / "leads.sqlite3"))

from app.main import app  # noqa: E402  (import after env vars are set)

if __name__ == "__main__":
    # 8506 is what this app listens on inside the gateway's docker network --
    # kept different here (8512) only because 8506 is already taken locally
    # by v2_discovery in the app dashboard. No significance beyond that.
    app.run(host="127.0.0.1", port=8512, debug=False)
