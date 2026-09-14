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

Usage: python3 run_local.py
"""
import os
from pathlib import Path

os.environ.setdefault("LEADS_DB", str(Path(__file__).resolve().parent / "local_data" / "leads.sqlite3"))

from app.main import app  # noqa: E402  (import after env var is set)

if __name__ == "__main__":
    # 8506 is what this app listens on inside the gateway's docker network --
    # kept different here (8512) only because 8506 is already taken locally
    # by v2_discovery in the app dashboard. No significance beyond that.
    app.run(host="127.0.0.1", port=8512, debug=False)
