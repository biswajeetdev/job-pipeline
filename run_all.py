#!/usr/bin/env python3
"""
run_all.py — Unified job search orchestrator.

Sources:
  1. Remotive API + HN Hiring + Wellfound RSS  (pipeline.py)
  2. career-ops portal scanner                 (scan.mjs — needs providers/ to be set up)
  3. cold outreach emails                      (outreach_engine.py --outreach flag)

All job discoveries merged into ~/job-pipeline/jobs.csv.
Outreach drafts remain at ~/job-pipeline/outreach_drafts.md (separate track).

Usage:
  python3 run_all.py                  # scraper + portal scan, LLM scoring
  python3 run_all.py --no-llm        # keyword filter only, no API calls
  python3 run_all.py --outreach      # also regenerate cold outreach emails
  python3 run_all.py --scan-only     # only run portal scanner
  python3 run_all.py --limit 100     # cap HN comments fetched (default 200)
"""

import csv
import hashlib
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

DIR        = Path(__file__).parent
CAREER_OPS = DIR.parent / "career-ops"
SCAN_HIST  = CAREER_OPS / "data" / "scan-history.tsv"
JOBS_CSV   = DIR / "jobs.csv"
DRAFTS_MD  = DIR / "email_drafts.md"

CSV_FIELDS = ["score", "company", "title", "location", "url", "source", "reason", "published", "applied", "notes"]


# ── Source 1: Remotive + HN + Wellfound ──────────────────────────────────────

def run_scraper(no_llm: bool, limit: int) -> list[dict]:
    """Run pipeline.py; return whatever it wrote to jobs.csv."""
    cmd = [sys.executable, str(DIR / "pipeline.py"), "--limit", str(limit)]
    if no_llm:
        cmd.append("--no-llm")
    print("\n[run_all] ── Source 1: Remotive + HN + Wellfound ──")
    result = subprocess.run(cmd, cwd=str(DIR))
    if result.returncode != 0:
        print("[run_all] Scraper failed — continuing without it")
        return []
    jobs = []
    if JOBS_CSV.exists():
        with open(JOBS_CSV, newline="") as f:
            for row in csv.DictReader(f):
                jobs.append(dict(row))
    print(f"[run_all] Scraper: {len(jobs)} jobs")
    return jobs


# ── Source 2: career-ops portal scanner ──────────────────────────────────────

def _stable_id(url: str) -> str:
    return "scan-" + hashlib.md5(url.encode()).hexdigest()[:12]


def run_scan() -> list[dict]:
    """
    Run career-ops/scan.mjs and return new entries from scan-history.tsv.

    scan.mjs requires providers/*.mjs to be present. If that directory is
    missing the command will fail — we log a warning and return [] so the rest
    of the pipeline keeps running.

    To fix: create ~/career-ops/providers/_http.mjs (shared HTTP helper) and
    at least one provider (e.g. providers/websearch.mjs) that handles the
    scan_method: websearch entries in portals.yml.
    """
    print("\n[run_all] ── Source 2: career-ops portal scanner ──")

    providers_dir = CAREER_OPS / "providers"
    if not providers_dir.exists():
        print("[run_all] SKIP — career-ops/providers/ directory missing.")
        print("          Create providers/_http.mjs + at least one provider to enable this source.")
        return []

    # Snapshot URLs already in scan-history before this run
    seen_before: set[str] = set()
    if SCAN_HIST.exists():
        with open(SCAN_HIST) as f:
            for line in f:
                url = line.split("\t")[0].strip()
                if url and url != "url":
                    seen_before.add(url)

    result = subprocess.run(["node", "scan.mjs"], cwd=str(CAREER_OPS))
    if result.returncode != 0:
        print("[run_all] scan.mjs failed — skipping portal results")
        return []

    # Read entries added by this run (present now, not before, status == 'added')
    new_jobs: list[dict] = []
    if SCAN_HIST.exists():
        with open(SCAN_HIST, newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                url = row.get("url", "").strip()
                if not url or url in seen_before:
                    continue
                if row.get("status", "") != "added":
                    continue
                company = row.get("company", "")
                title   = row.get("title", "")
                new_jobs.append({
                    "id":          _stable_id(url),
                    "source":      f"portal-{row.get('portal', 'scan')}",
                    "company":     company,
                    "title":       title,
                    "location":    row.get("location", ""),
                    "url":         url,
                    "tags":        "",
                    "description": f"{title} at {company}",
                    "published":   row.get("first_seen", date.today().isoformat()),
                    "score":       0,   # unscored — different role family from scraper
                    "reason":      "portal scan (unscored — consulting/analyst track)",
                })

    print(f"[run_all] Portal scan: {len(new_jobs)} new jobs")
    return new_jobs


# ── Source 3: cold outreach (optional) ───────────────────────────────────────

def run_outreach(no_llm: bool) -> None:
    """Run outreach_engine.py — separate track, not merged into jobs.csv."""
    print("\n[run_all] ── Source 3: cold outreach ──")
    cmd = [sys.executable, str(DIR / "outreach_engine.py")]
    if no_llm:
        cmd.append("--no-llm")
    subprocess.run(cmd, cwd=str(DIR))


# ── Merge & save ─────────────────────────────────────────────────────────────

def merge_jobs(scraper_jobs: list[dict], scan_jobs: list[dict]) -> list[dict]:
    """Deduplicate by URL across all sources."""
    seen_urls: set[str] = set()
    merged: list[dict] = []
    for job in scraper_jobs + scan_jobs:
        url = job.get("url", "")
        if url and url in seen_urls:
            continue
        seen_urls.add(url)
        merged.append(job)
    return merged


def save_unified(jobs: list[dict]) -> None:
    # Preserve any manually set applied/notes fields
    existing: dict[str, dict] = {}
    if JOBS_CSV.exists():
        with open(JOBS_CSV, newline="") as f:
            for row in csv.DictReader(f):
                existing[row.get("url", "")] = {
                    "applied": row.get("applied", ""),
                    "notes":   row.get("notes", ""),
                }

    for job in jobs:
        prev = existing.get(job.get("url", ""), {})
        job.setdefault("applied", prev.get("applied", ""))
        job.setdefault("notes",   prev.get("notes", ""))

    # Sort: LLM-scored startup jobs first (score > 0), then unscored portal jobs
    jobs_sorted = sorted(
        jobs,
        key=lambda x: (float(x.get("score") or 0), x.get("source", "")),
        reverse=True,
    )
    with open(JOBS_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(jobs_sorted)
    print(f"\n[run_all] {len(jobs_sorted)} total jobs saved → {JOBS_CSV}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Unified job search orchestrator")
    parser.add_argument("--no-llm",   action="store_true", help="Skip LLM scoring")
    parser.add_argument("--outreach", action="store_true", help="Also run cold outreach engine")
    parser.add_argument("--scan-only",action="store_true", help="Only run portal scanner")
    parser.add_argument("--limit",    type=int, default=200, help="Max HN comments (default 200)")
    args = parser.parse_args()

    if args.scan_only:
        scan_jobs = run_scan()
        save_unified(scan_jobs)
    else:
        scraper_jobs = run_scraper(no_llm=args.no_llm, limit=args.limit)
        scan_jobs    = run_scan()
        all_jobs     = merge_jobs(scraper_jobs, scan_jobs)
        save_unified(all_jobs)

    if args.outreach:
        run_outreach(no_llm=args.no_llm)

    print(f"\nDone.")
    print(f"  Jobs CSV:      {JOBS_CSV}")
    print(f"  Email drafts:  {DRAFTS_MD}")
    if args.outreach:
        print(f"  Outreach:      {DIR / 'outreach_drafts.md'}")
    if not (CAREER_OPS / "providers").exists():
        print(f"\n  ⚠  Portal scanner inactive — create career-ops/providers/ to enable.")


if __name__ == "__main__":
    main()
