"""
Leads CRM -- shared schema, regardless of where a lead came from.

One `leads` table is the entire point of this app: a CEPEX exporter and an
Articrea exhibitor go through the exact same pipeline (STAGES below), get
notes logged the same way, and -- when the same real company shows up from
two sources -- collapse into ONE row instead of living as two disconnected
records forever. `sources` records every place a lead was seen (a lead can
carry more than one); `source_data` keeps each source's own raw fields
(CEPEX's export countries/certifications, Articrea's photos/catalog) without
forcing them into a common shape -- only the CRM-facing fields (name,
contact, stage, notes) are unified.
"""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(os.environ.get("LEADS_DB", "/data/leads.sqlite3"))

# Order matters -- this IS the pipeline, in sequence. "lost" and
# "not_interested" are the two dead-end states; everything else moves
# forward. Change this list to change the pipeline for every lead,
# regardless of source -- there's no separate CEPEX or Articrea pipeline.
STAGES = ["new", "contacted", "call_scheduled", "negotiating", "won", "lost", "not_interested"]
STAGE_LABELS = {
    "new": "New",
    "contacted": "Contacted",
    "call_scheduled": "Call scheduled",
    "negotiating": "Negotiating",
    "won": "Won",
    "lost": "Lost",
    "not_interested": "Not interested",
}


@contextmanager
def get_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT,
                email TEXT,
                address TEXT,
                category TEXT,
                stage TEXT NOT NULL DEFAULT 'new',
                sources TEXT NOT NULL DEFAULT '[]',      -- JSON list, e.g. ["cepex","articrea"]
                source_data TEXT NOT NULL DEFAULT '{}',  -- JSON: {"cepex": {...}, "articrea": {...}}
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS lead_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
                author TEXT NOT NULL,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS lead_stage_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
                from_stage TEXT,
                to_stage TEXT NOT NULL,
                author TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_leads_stage ON leads(stage);
            CREATE INDEX IF NOT EXISTS idx_notes_lead ON lead_notes(lead_id);
        """)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def upsert_lead(conn, *, name, phone=None, email=None, address=None, category=None,
                 source=None, source_fields=None, match_lead_id=None):
    """Insert a new lead, or -- if match_lead_id is given -- merge this
    source's data into an existing lead rather than creating a duplicate.
    This is the consolidation path: a later import (or a future live
    connection) that recognizes an existing lead calls this with
    match_lead_id set instead of creating a second row."""
    ts = now_iso()
    if match_lead_id is None:
        sources = [source] if source else []
        source_data = {source: source_fields} if source and source_fields else {}
        cur = conn.execute(
            "INSERT INTO leads (name, phone, email, address, category, stage, sources, "
            "source_data, created_at, updated_at) VALUES (?,?,?,?,?,'new',?,?,?,?)",
            (name, phone, email, address, category, json.dumps(sources),
             json.dumps(source_data), ts, ts),
        )
        return cur.lastrowid

    row = conn.execute("SELECT sources, source_data FROM leads WHERE id=?",
                        (match_lead_id,)).fetchone()
    sources = json.loads(row["sources"])
    source_data = json.loads(row["source_data"])
    if source and source not in sources:
        sources.append(source)
    if source and source_fields:
        source_data[source] = source_fields
    conn.execute(
        "UPDATE leads SET sources=?, source_data=?, updated_at=?, "
        "phone=COALESCE(phone, ?), email=COALESCE(email, ?), address=COALESCE(address, ?) "
        "WHERE id=?",
        (json.dumps(sources), json.dumps(source_data), ts, phone, email, address, match_lead_id),
    )
    return match_lead_id


def add_note(conn, lead_id, author, text):
    conn.execute(
        "INSERT INTO lead_notes (lead_id, author, text, created_at) VALUES (?,?,?,?)",
        (lead_id, author, text, now_iso()),
    )
    conn.execute("UPDATE leads SET updated_at=? WHERE id=?", (now_iso(), lead_id))


def set_stage(conn, lead_id, new_stage, author):
    if new_stage not in STAGES:
        raise ValueError(f"Unknown stage {new_stage!r}, expected one of {STAGES}")
    row = conn.execute("SELECT stage FROM leads WHERE id=?", (lead_id,)).fetchone()
    old_stage = row["stage"] if row else None
    conn.execute("UPDATE leads SET stage=?, updated_at=? WHERE id=?",
                 (new_stage, now_iso(), lead_id))
    conn.execute(
        "INSERT INTO lead_stage_history (lead_id, from_stage, to_stage, author, created_at) "
        "VALUES (?,?,?,?,?)",
        (lead_id, old_stage, new_stage, author, now_iso()),
    )
