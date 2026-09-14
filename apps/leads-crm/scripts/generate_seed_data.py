#!/usr/bin/env python3
"""
Run LOCALLY (not part of the deployed app) to produce
apps/leads-crm/app/seed_data.json -- the merged, deduplicated lead list the
CRM imports on first boot. Re-run and re-commit this whenever a new source
batch (more CEPEX sectors, a new event) should feed into the CRM; the app's
import is additive/matching (see db.upsert_lead), so re-running this and
redeploying does not wipe notes or stage changes already made against
existing leads -- see app/seed.py.

Matching (same signals as articrea_scraper/cross_reference.py, generalized
across ALL sources rather than just CEPEX-vs-Articrea): phone (last 8
digits), email (exact, case-insensitive), then normalized-name exact match.
Order matters -- phone/email are treated as high-confidence identity
signals; name alone only merges on an EXACT normalized match here (no fuzzy
step) since this feeds a real pipeline, not just a comparison view --
a wrong auto-merge here means someone's call notes end up on the wrong
company, so we're conservative: ambiguous near-matches stay as separate
leads rather than risk merging two different companies. A human noticing a
near-miss can merge manually later (not built yet -- flagged in the CRM's
own README).
"""
import json
import re
import unicodedata
from pathlib import Path

CEPEX_SOURCES = [
    ("/Users/fb/cepex_scraper/artisanat_companies.json", "Handicrafts"),
    ("/Users/fb/cepex_scraper/textiles_companies.json", "Textiles & Clothing/Leather & Footwear"),
    ("/Users/fb/cepex_scraper/agrofood_companies.json", "Agro-food"),
]
ARTICREA_SOURCE = "/Users/fb/articrea_scraper/vendors.json"
OUT_PATH = Path(__file__).resolve().parent.parent / "app" / "seed_data.json"


def norm_name(s):
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    s = re.sub(r"\b(ste|societe|sarl|sa|est|etablissement|co|company)\b", "", s).strip()
    return re.sub(r"\s+", " ", s)


def norm_phone(s):
    if not s:
        return None
    digits = re.sub(r"\D", "", s)
    return digits[-8:] if len(digits) >= 8 else (digits or None)


def norm_email(s):
    return (s or "").strip().lower() or None


def load_cepex():
    records = []
    for path, sector in CEPEX_SOURCES:
        for r in json.load(open(path)):
            if r.get("_note"):
                continue
            records.append({
                "source": "cepex",
                "name": r.get("name"),
                "phone": r.get("phone"),
                "email": r.get("email"),
                "address": r.get("address"),
                "category": sector,
                "source_fields": r,
            })
    return records


def load_articrea():
    records = []
    for v in json.load(open(ARTICREA_SOURCE)):
        if v.get("_note") and not v.get("name"):
            continue
        records.append({
            "source": "articrea",
            "name": v.get("name"),
            "phone": v.get("phone"),
            "email": v.get("email"),
            "address": v.get("address"),
            "category": None,  # Articrea's own scraper doesn't set one; CRM users can note it
            "source_fields": v,
        })
    return records


def main():
    all_records = load_cepex() + load_articrea()

    leads = []  # each: {name, phone, email, address, category, sources: [], source_data: {}}
    # Phone/email keys store (lead_idx, source) -- a match only counts if it
    # comes from a DIFFERENT source than where the key was first seen. Two
    # exhibitors at the same event sharing a phone number (an organizer or
    # family contact) are NOT the same company; that only becomes a
    # meaningful identity signal when it's the SAME number showing up in two
    # independently-run directories (CEPEX vs. Articrea), which is genuinely
    # unlikely by chance. Name-exact matching has no such restriction: the
    # same company listed identically under two CEPEX sectors (e.g. both
    # Handicrafts and Textiles) is a legitimate same-source merge.
    by_phone, by_email, by_name = {}, {}, {}

    for rec in all_records:
        phone_k = norm_phone(rec["phone"])
        email_k = norm_email(rec["email"])
        name_k = norm_name(rec["name"])

        match_idx = None
        if phone_k and phone_k in by_phone and by_phone[phone_k][1] != rec["source"]:
            match_idx = by_phone[phone_k][0]
        elif email_k and email_k in by_email and by_email[email_k][1] != rec["source"]:
            match_idx = by_email[email_k][0]
        elif name_k and name_k in by_name:
            match_idx = by_name[name_k]

        if match_idx is None:
            leads.append({
                "name": rec["name"], "phone": rec["phone"], "email": rec["email"],
                "address": rec["address"], "category": rec["category"],
                "sources": [rec["source"]],
                "source_data": {rec["source"]: rec["source_fields"]},
            })
            match_idx = len(leads) - 1
        else:
            lead = leads[match_idx]
            if rec["source"] not in lead["sources"]:
                lead["sources"].append(rec["source"])
            lead["source_data"][rec["source"]] = rec["source_fields"]
            lead["phone"] = lead["phone"] or rec["phone"]
            lead["email"] = lead["email"] or rec["email"]
            lead["address"] = lead["address"] or rec["address"]
            lead["category"] = lead["category"] or rec["category"]

        if phone_k:
            by_phone.setdefault(phone_k, (match_idx, rec["source"]))
        if email_k:
            by_email.setdefault(email_k, (match_idx, rec["source"]))
        if name_k:
            by_name.setdefault(name_k, match_idx)

    merged = sum(1 for l in leads if len(l["sources"]) > 1)
    print(f"{len(all_records)} source records -> {len(leads)} unique leads "
          f"({merged} merged across sources)")

    OUT_PATH.write_text(json.dumps(leads, ensure_ascii=False, indent=2))
    print(f"wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
