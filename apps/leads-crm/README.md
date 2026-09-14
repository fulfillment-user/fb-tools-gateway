# Leads CRM

One pipeline for every lead, regardless of where it came from. Built per
direct instruction (2026-09-14): CEPEX and Articrea are both just lead
*sources* -- the CRM logic behind them (stages, call notes, who's talking to
whom) has to be identical, and a lead seen in more than one source should
consolidate into one record, not live as permanent separate entries.

## What's in here

- `app/db.py` -- schema. Three tables: `leads` (one unified row per real
  company/contact, source-agnostic), `lead_notes` (a timeline of call notes,
  who wrote each one), `lead_stage_history` (an audit trail of every stage
  change). `STAGES` in this file *is* the pipeline -- change it there to
  change the pipeline for every lead, since there's no separate CEPEX or
  Articrea pipeline to keep in sync.
- `app/main.py` -- the Flask app: a filterable list view and a per-lead
  detail page (contact info, stage control, notes, raw source data per
  source it came from).
- `app/seed.py` + `app/seed_data.json` -- the initial import. Runs once,
  automatically, the first time the database is empty; never re-runs or
  overwrites on an ordinary redeploy (so notes/stage changes you've already
  made survive every future deploy).
- `scripts/generate_seed_data.py` -- run **locally**, not part of the
  deployed app, whenever a new source batch should feed in (more CEPEX
  sectors scraped, a new event). Re-generates `app/seed_data.json`, which
  then needs to be committed and pushed like any other change.

## How sources get merged into one lead

Phone (exact, last 8 digits) or email (exact) match **across two different
sources** = same lead, high confidence. An exact name match merges
regardless of source (the same company can legitimately appear twice within
CEPEX itself, e.g. under two sectors). Phone/email matches **within the same
source** are deliberately NOT merged -- two different exhibitors at the same
event sharing a phone number (a shared organizer or family contact) are
almost certainly two different businesses, not one; only trust that signal
when it's an independent second source agreeing with the first. See
`generate_seed_data.py`'s docstring for the full reasoning -- this cost a
real bug during development (two unrelated Articrea exhibitor pairs sharing
a phone number got wrongly merged, silently dropping one exhibitor's data,
before this restriction was added).

## Known limitation

There's no UI yet for a human to merge two leads that a fuzzy-but-not-exact
name match would have caught (e.g. a typo'd company name across sources) --
`generate_seed_data.py` is deliberately conservative and leaves those as
separate leads rather than risk a wrong auto-merge. If that turns out to
matter in practice, the fix is a manual "merge into..." action on the lead
detail page, not a change to the automatic matching -- flag it if you hit a
real case of this.
