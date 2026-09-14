"""
Follow-up suggestion agent -- reads a lead's note history and decides the
best next action: draft a follow-up email, suggest a Calendly call, or
conclude no action is needed yet. Per direct instruction (2026-09-14): this
is a human-in-the-loop drafting aid, same principle as the email copilot
vision already on file -- it never sends anything itself, it produces a
page a person reads, copies from, and sends by hand.

Every call is persisted via db.save_suggestion() with the exact notes it saw
and its full output -- not just for audit, but so this is retrieval-ready:
the intended seed of FB's own RAG corpus once that's built, per the same
instruction. Nothing here builds embeddings/vector search -- that's a
separate, larger project; this only makes sure the structured data it would
need already exists.
"""
import json
import os

import anthropic

from . import db

MODEL = "claude-sonnet-5"

# Per-user Calendly links come from config.yaml via the gateway (see
# auth-service's /verify -> X-Auth-Calendly header, copied through by
# Caddy). Anyone without one set (or running locally, with no gateway in
# front at all) falls back to this -- "for now use this" per direct
# instruction 2026-09-14. Update if this stops being the right default.
DEFAULT_CALENDLY_URL = "https://calendly.com/kais-khadhraoui/catch-up-with-kais"

PROMPT_TEMPLATE = """You are a sales assistant deciding the best next action for one B2B lead, \
for a Tunisia-based fulfillment/logistics company (Fulfillment Bridge) reaching out to \
exporters and craft businesses.

LEAD
Name: {name}
Category: {category}
Stage: {stage}
Phone: {phone}
Email: {email}
Address: {address}

NOTES (oldest first, this is the full history of contact with this lead):
{notes_block}

Decide ONE next action:
- "email": a follow-up email is the right next step. Draft a real, ready-to-send email \
(French if the lead appears Tunisian/francophone -- true for most leads here -- otherwise \
English). Keep it concise, warm but professional, reference something specific from the notes \
so it doesn't read as generic, and end with one clear, single next step.
- "calendly": the notes suggest this lead is ready for a live conversation (interested, asked \
a question only a call can answer, has been back-and-forth over email already, etc). Draft a \
short message inviting them to book a slot, in the same language logic as above. The booking \
link will be appended automatically -- do not invent one yourself, just write the message \
around it (e.g. "you can grab a slot here:").
- "no_action": there's nothing to do yet (e.g. no notes, or the last note already says a \
follow-up is scheduled and nothing has changed since).

Respond with ONLY a JSON object, no markdown fences, no other text:
{{"action_type": "email" | "calendly" | "no_action",
  "reasoning": "one or two sentences on why this action, referencing the notes",
  "subject": "email subject line, or null if action_type is not email",
  "body": "the drafted message body (email text, or the calendly invite text), or null if no_action"}}
"""


class SuggestionError(Exception):
    pass


def _client():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SuggestionError(
            "ANTHROPIC_API_KEY isn't set -- see .env.example. No suggestion was generated.")
    return anthropic.Anthropic(api_key=api_key)


def _parse_response(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise SuggestionError(f"Model didn't return valid JSON: {e}. Raw: {text[:300]}")
    if data.get("action_type") not in ("email", "calendly", "no_action"):
        raise SuggestionError(f"Unexpected action_type: {data.get('action_type')!r}")
    return data


def generate_suggestion(conn, lead_row, notes_rows, author: str, calendly_url: str = None):
    """lead_row / notes_rows: sqlite3.Row objects from db.py's own queries.
    Returns the new lead_suggestions row id. Raises SuggestionError on any
    failure (missing key, bad model output) -- callers show that message
    rather than silently producing a blank/broken suggestion."""
    calendly_url = calendly_url or DEFAULT_CALENDLY_URL

    notes_snapshot = [{"created_at": n["created_at"], "author": n["author"], "text": n["text"]}
                       for n in notes_rows]
    notes_block = "\n".join(f"- [{n['created_at']}] {n['author']}: {n['text']}"
                             for n in notes_rows) or "(no notes yet)"

    prompt = PROMPT_TEMPLATE.format(
        name=lead_row["name"], category=lead_row["category"] or "unknown",
        stage=lead_row["stage"], phone=lead_row["phone"] or "none on file",
        email=lead_row["email"] or "none on file", address=lead_row["address"] or "none on file",
        notes_block=notes_block,
    )

    client = _client()
    response = client.messages.create(
        model=MODEL, max_tokens=1024, messages=[{"role": "user", "content": prompt}],
    )
    raw_text = "".join(block.text for block in response.content if block.type == "text")
    data = _parse_response(raw_text)

    body = data.get("body")
    if data["action_type"] == "calendly" and body:
        body = f"{body}\n\n{calendly_url}"

    return db.save_suggestion(
        conn, lead_id=lead_row["id"], created_by=author, action_type=data["action_type"],
        subject=data.get("subject"), body=body,
        calendly_url=calendly_url if data["action_type"] == "calendly" else None,
        reasoning=data.get("reasoning"), model=MODEL, notes_snapshot=notes_snapshot,
    )
