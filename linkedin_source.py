#!/usr/bin/env python3
"""
linkedin_source.py — LinkedIn job source for pipeline.py, backed by JobSpy.

Returns the same dict shape as the other fetch_* functions in pipeline.py, so
main() can concatenate it with the rest without special-casing.

    from linkedin_source import fetch_linkedin
    jobs = fetch_linkedin()

Standalone:
    python3 linkedin_source.py --terms "Chief of Staff" --location Bangalore

LinkedIn rate-limits scrapers hard. Defaults here are deliberately conservative:
few search terms, modest result counts, and a pause between queries. Turning
these up is the fastest way to start getting empty results back.
"""
from __future__ import annotations

import argparse
import os
import time

# Search terms aimed at Founder's Office / Chief of Staff / startup ops roles.
# Override with LINKEDIN_TERMS="a,b,c" or --terms.
DEFAULT_TERMS = [
    "Founder's Office",
    "Chief of Staff",
    "Business Operations Associate",
    "Strategy and Operations",
]

# Override with LINKEDIN_LOCATIONS="a,b" or --location (repeatable).
DEFAULT_LOCATIONS = ["India", "Bangalore, India", "Mumbai, India"]

RESULTS_PER_QUERY = int(os.getenv("LINKEDIN_RESULTS", "25"))
HOURS_OLD = int(os.getenv("LINKEDIN_HOURS_OLD", "168"))  # 7 days
QUERY_DELAY = float(os.getenv("LINKEDIN_DELAY", "4"))    # seconds between queries


def _csv_env(name: str) -> list[str] | None:
    raw = os.getenv(name, "").strip()
    return [p.strip() for p in raw.split(",") if p.strip()] or None


def fetch_linkedin(
    terms: list[str] | None = None,
    locations: list[str] | None = None,
    results_per_query: int = RESULTS_PER_QUERY,
    hours_old: int = HOURS_OLD,
) -> list[dict]:
    """Scrape LinkedIn job postings via JobSpy. Returns pipeline-shaped dicts.

    Degrades to an empty list (never raises) so a LinkedIn block or a missing
    dependency cannot take down the whole pipeline run.
    """
    try:
        from jobspy import scrape_jobs
    except ImportError:
        print("[linkedin] python-jobspy not installed — skipping. "
              "Install with: pip install python-jobspy")
        return []

    terms = terms or _csv_env("LINKEDIN_TERMS") or DEFAULT_TERMS
    locations = locations or _csv_env("LINKEDIN_LOCATIONS") or DEFAULT_LOCATIONS

    result: list[dict] = []
    seen_ids: set[str] = set()
    blocked = 0

    for term in terms:
        for loc in locations:
            try:
                df = scrape_jobs(
                    site_name=["linkedin"],
                    search_term=term,
                    location=loc,
                    results_wanted=results_per_query,
                    hours_old=hours_old,
                    linkedin_fetch_description=True,
                )
            except Exception as e:
                blocked += 1
                print(f"[linkedin] error ({term} @ {loc}): {e}")
                time.sleep(QUERY_DELAY)
                continue

            if df is None or len(df) == 0:
                print(f"[linkedin] 0 results ({term} @ {loc})")
                time.sleep(QUERY_DELAY)
                continue

            for row in df.to_dict("records"):
                job = _normalize(row, term)
                if not job or job["id"] in seen_ids:
                    continue
                seen_ids.add(job["id"])
                result.append(job)

            print(f"[linkedin] {len(df):3d} results ({term} @ {loc})")
            time.sleep(QUERY_DELAY)

    if blocked and not result:
        print("[linkedin] every query failed — LinkedIn is likely rate-limiting. "
              "Back off, or set LINKEDIN_RESULTS lower and LINKEDIN_DELAY higher.")

    print(f"[linkedin] fetched {len(result)} unique jobs "
          f"across {len(terms)} terms x {len(locations)} locations")
    return result


def _clean(value) -> str:
    """JobSpy returns numpy NaN for empty cells; coerce everything to str."""
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in ("nan", "none", "nat") else text


def _normalize(row: dict, search_term: str) -> dict | None:
    url = _clean(row.get("job_url")) or _clean(row.get("job_url_direct"))
    title = _clean(row.get("title"))
    if not url or not title:
        return None

    raw_id = _clean(row.get("id")) or url.rstrip("/").rsplit("/", 1)[-1]

    tags = [search_term]
    for key in ("job_type", "job_level", "job_function", "company_industry"):
        val = _clean(row.get(key))
        if val:
            tags.append(val)
    if str(row.get("is_remote")).lower() == "true":
        tags.append("remote")

    # JobSpy surfaces any e-mail addresses the employer put in the posting
    # itself. That is published contact info, not scraped from a profile.
    emails = _clean(row.get("emails"))

    return {
        "id": f"linkedin-{raw_id}",
        "source": "linkedin",
        "company": _clean(row.get("company")),
        "title": title,
        "location": _clean(row.get("location")) or "Unspecified",
        "url": url,
        "tags": " ".join(tags),
        "description": _clean(row.get("description"))[:800],
        "published": _clean(row.get("date_posted")),
        "contact_email": emails,
        "company_url": _clean(row.get("company_url")),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Scrape LinkedIn jobs via JobSpy.")
    ap.add_argument("--terms", help="Comma-separated search terms")
    ap.add_argument("--location", action="append", dest="locations",
                    help="Location (repeatable)")
    ap.add_argument("--results", type=int, default=RESULTS_PER_QUERY,
                    help="Results per query")
    ap.add_argument("--hours-old", type=int, default=HOURS_OLD,
                    help="Only postings newer than this many hours")
    args = ap.parse_args()

    jobs = fetch_linkedin(
        terms=[t.strip() for t in args.terms.split(",")] if args.terms else None,
        locations=args.locations,
        results_per_query=args.results,
        hours_old=args.hours_old,
    )
    for j in jobs:
        mail = f"  <{j['contact_email']}>" if j["contact_email"] else ""
        print(f"{j['company'][:28]:28s} | {j['title'][:44]:44s} | {j['location'][:20]}{mail}")
    print(f"\n{len(jobs)} jobs")


if __name__ == "__main__":
    main()
