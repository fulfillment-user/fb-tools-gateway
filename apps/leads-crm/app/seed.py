"""
Imports seed_data.json (built by scripts/generate_seed_data.py, run locally
and committed) into the leads table -- but only the first time the database
is empty. Never overwrites or duplicates on a redeploy: once leads exist,
this is a no-op. Re-seeding after new source data means someone edits and
re-commits seed_data.json AND uses `python3 -m app.seed --force` (see
main()) to run the merge-aware import again -- ordinary redeploys never
touch existing leads/notes.
"""
import json
import sys
from pathlib import Path

from . import db

SEED_PATH = Path(__file__).resolve().parent / "seed_data.json"


def already_seeded(conn) -> bool:
    return conn.execute("SELECT COUNT(*) AS n FROM leads").fetchone()["n"] > 0


def import_seed(conn, seed_leads):
    for lead in seed_leads:
        lead_id = db.upsert_lead(
            conn, name=lead["name"], phone=lead.get("phone"), email=lead.get("email"),
            address=lead.get("address"), category=lead.get("category"),
        )
        # Attach every source this lead came from directly (upsert_lead only
        # takes one source at a time -- these are all new leads at import
        # time, never matched against an existing DB row, so loop and merge
        # source_data/sources ourselves rather than calling it once per
        # source (which would look like a match against itself).
        conn.execute(
            "UPDATE leads SET sources=?, source_data=? WHERE id=?",
            (json.dumps(lead["sources"]), json.dumps(lead["source_data"]), lead_id),
        )


def main():
    db.init_db()
    force = "--force" in sys.argv
    with db.get_db() as conn:
        if already_seeded(conn) and not force:
            print("Leads already exist -- skipping seed import (pass --force to re-run).")
            return
        seed_leads = json.loads(SEED_PATH.read_text())
        import_seed(conn, seed_leads)
        print(f"Imported {len(seed_leads)} leads from {SEED_PATH.name}.")


if __name__ == "__main__":
    main()
