#!/usr/bin/env python3
"""
apollo_enrich.py — attach contact info to high-scoring jobs from jobs.csv.

Order of preference, cheapest first:

  1. contact_email already in the posting (JobSpy pulls e-mails the employer
     published in the job description). Free. No API call.
  2. Apollo organization enrichment — confirms the company domain and returns
     firmographics. Does not burn a person credit.
  3. Apollo people match — reveals a work e-mail. THIS SPENDS A CREDIT, and you
     have a finite pool. Only runs when you supply a name.

Why step 3 needs a name: this account's Apollo *search* endpoints are locked, so
there is no way to ask "who runs talent at this company?". Enrichment can only
confirm a person you can already name. Get names from the posting, the company
site, or your own outreach_targets.csv — not from scraping LinkedIn profiles.

Usage:
    python3 apollo_enrich.py                      # dry run, spends nothing
    python3 apollo_enrich.py --commit             # actually calls Apollo
    python3 apollo_enrich.py --commit --max-credits 10
    python3 apollo_enrich.py --names contacts_in.csv --commit

Needs APOLLO_API_KEY in the environment or .env.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

DIR = Path(__file__).parent
JOBS_CSV = DIR / "jobs.csv"
OUT_CSV = DIR / "contacts.csv"
ENV_FILE = DIR / ".env"

APOLLO_BASE = "https://api.apollo.io/api/v1"
DEFAULT_MAX_CREDITS = 10          # conservative slice of the ~80 available
DEFAULT_MIN_SCORE = 7

OUT_FIELDS = ["company", "title", "score", "url", "domain", "contact_name",
              "contact_title", "contact_email", "email_source", "notes"]


def load_env() -> None:
    """Minimal .env loader so this works without python-dotenv."""
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def apollo_key() -> str | None:
    load_env()
    return os.getenv("APOLLO_API_KEY", "").strip() or None


def domain_from(url: str, company: str) -> str:
    """Best-effort company domain. Never guesses from the company name alone —
    a wrong domain sends a real e-mail to a stranger."""
    if url:
        host = urlparse(url if "//" in url else f"//{url}", scheme="https").netloc
        host = host.lower().removeprefix("www.")
        if host and "linkedin.com" not in host and "." in host:
            return host
    return ""


def read_jobs(min_score: int) -> list[dict]:
    if not JOBS_CSV.exists():
        print(f"[apollo] {JOBS_CSV} not found — run pipeline.py first.")
        return []
    rows = []
    with JOBS_CSV.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                score = int(float(r.get("score") or 0))
            except ValueError:
                score = 0
            if score >= min_score:
                r["score"] = score
                rows.append(r)
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows


def read_names(path: Path) -> dict[str, dict]:
    """Optional CSV of people you already identified: company,first_name,last_name."""
    if not path or not path.exists():
        return {}
    out = {}
    with path.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            key = (r.get("company") or "").strip().lower()
            if key:
                out[key] = r
    print(f"[apollo] loaded {len(out)} known names from {path.name}")
    return out


def org_enrich(session: requests.Session, domain: str) -> dict:
    try:
        r = session.get(f"{APOLLO_BASE}/organizations/enrich",
                        params={"domain": domain}, timeout=20)
        if r.status_code == 403:
            return {"_error": "403 — endpoint not available on this plan"}
        r.raise_for_status()
        return r.json().get("organization") or {}
    except Exception as e:
        return {"_error": str(e)}


def people_match(session: requests.Session, first: str, last: str,
                 domain: str) -> dict:
    """Spends a credit. Personal e-mails deliberately not requested."""
    try:
        r = session.post(f"{APOLLO_BASE}/people/match",
                         json={"first_name": first, "last_name": last,
                               "domain": domain,
                               "reveal_personal_emails": False},
                         timeout=25)
        if r.status_code == 403:
            return {"_error": "403 — people match not available on this plan"}
        r.raise_for_status()
        return r.json().get("person") or {}
    except Exception as e:
        return {"_error": str(e)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Enrich high-scoring jobs with contacts.")
    ap.add_argument("--commit", action="store_true",
                    help="Actually call Apollo. Without this, nothing is spent.")
    ap.add_argument("--min-score", type=int, default=DEFAULT_MIN_SCORE)
    ap.add_argument("--max-credits", type=int, default=DEFAULT_MAX_CREDITS,
                    help="Hard cap on people-match calls this run")
    ap.add_argument("--names", type=Path,
                    help="CSV of company,first_name,last_name you already know")
    args = ap.parse_args()

    jobs = read_jobs(args.min_score)
    if not jobs:
        print(f"[apollo] no jobs scoring >= {args.min_score}.")
        return 0
    print(f"[apollo] {len(jobs)} jobs scoring >= {args.min_score}")

    names = read_names(args.names) if args.names else {}

    key = apollo_key()
    session = None
    if args.commit:
        if not key:
            print("[apollo] APOLLO_API_KEY not set — add it to .env. Aborting.")
            return 1
        session = requests.Session()
        session.headers.update({"x-api-key": key,
                                "Content-Type": "application/json",
                                "Cache-Control": "no-cache"})
    else:
        print("[apollo] DRY RUN — no API calls, no credits spent. "
              "Re-run with --commit when the plan below looks right.\n")

    rows, credits = [], 0

    for j in jobs:
        company = (j.get("company") or "").strip()
        row = {"company": company, "title": j.get("title", ""),
               "score": j["score"], "url": j.get("url", ""),
               "domain": "", "contact_name": "", "contact_title": "",
               "contact_email": "", "email_source": "", "notes": ""}

        # 1. free: e-mail the employer published in the posting itself
        published = (j.get("contact_email") or "").strip()
        if published:
            row["contact_email"] = published.split(",")[0].strip()
            row["email_source"] = "job posting"
            rows.append(row)
            print(f"  ✓ {company[:28]:28s} {row['contact_email']}  (from posting, free)")
            continue

        domain = domain_from(j.get("company_url", ""), company)
        if not domain:
            row["notes"] = "no domain in posting — add company_url to enrich"
            rows.append(row)
            print(f"  – {company[:28]:28s} no domain, skipped")
            continue
        row["domain"] = domain

        known = names.get(company.lower())
        if not known:
            row["notes"] = ("domain known; supply a name via --names to reveal "
                            "an e-mail (Apollo search is locked on this plan)")
            rows.append(row)
            print(f"  – {company[:28]:28s} {domain}  (no name known)")
            continue

        first = (known.get("first_name") or "").strip()
        last = (known.get("last_name") or "").strip()

        if credits >= args.max_credits:
            row["notes"] = f"credit cap ({args.max_credits}) reached"
            rows.append(row)
            print(f"  ! {company[:28]:28s} credit cap reached, stopping lookups")
            continue

        if not args.commit:
            row["contact_name"] = f"{first} {last}".strip()
            row["notes"] = "would spend 1 credit"
            rows.append(row)
            credits += 1
            print(f"  $ {company[:28]:28s} {domain}  would look up {first} {last}")
            continue

        person = people_match(session, first, last, domain)
        credits += 1
        if person.get("_error"):
            row["notes"] = person["_error"]
            print(f"  ! {company[:28]:28s} {person['_error']}")
        else:
            row["contact_name"] = (person.get("name")
                                   or f"{first} {last}").strip()
            row["contact_title"] = person.get("title") or ""
            row["contact_email"] = person.get("email") or ""
            row["email_source"] = "apollo" if person.get("email") else ""
            if not row["contact_email"]:
                row["notes"] = "no e-mail on record"
            print(f"  ✓ {company[:28]:28s} {row['contact_email'] or '(no e-mail)'}"
                  f"  (apollo, credit {credits})")
        rows.append(row)
        time.sleep(1.0)

    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUT_FIELDS)
        w.writeheader()
        w.writerows(rows)

    found = sum(1 for r in rows if r["contact_email"])
    free = sum(1 for r in rows if r["email_source"] == "job posting")
    verb = "spent" if args.commit else "would spend"
    print(f"\n[apollo] {len(rows)} rows -> {OUT_CSV.name}")
    print(f"[apollo] {found} with e-mail ({free} free from postings), "
          f"{verb} {credits} credit(s)")
    if not args.commit:
        print("[apollo] dry run — nothing was spent. Add --commit to execute.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
