# job-pipeline

AI-powered job search pipeline. Scrapes remote job boards, scores matches with an LLM, and generates cold outreach emails — all from the terminal with zero manual triage.

## What it does

| Step | Script | Output |
|------|--------|--------|
| Scrape 7 sources | `pipeline.py` | `jobs.csv` |
| LLM-score each match | `pipeline.py` | scores in `jobs.csv` |
| Attach contacts to top matches | `apollo_enrich.py` | `contacts.csv` |
| Generate outreach emails | `outreach_engine.py` | `outreach_drafts.md` |
| Run everything | `run_all.py` | both outputs |

**Sources scraped:**
- [Remotive](https://remotive.com) — remote software jobs (API)
- [HN "Who is Hiring?"](https://news.ycombinator.com) — auto-detects current month's thread
- [Wellfound](https://wellfound.com) — startup jobs (RSS)
- [YC Work at a Startup](https://www.ycombinator.com/jobs) — YC-backed startups via HN Algolia
- [Internshala](https://internshala.com) — India internships
- [RemoteOK](https://remoteok.com) — remote-only jobs (public API)
- [LinkedIn](https://linkedin.com/jobs) — via [JobSpy](https://github.com/speedyapply/JobSpy), see below

**LLM scoring:** Uses GitHub Models (gpt-4o-mini, free tier) via `gh auth token`. Falls back to keyword-only if no token.

**Dedup:** `seen.json` tracks all previously seen job IDs — re-runs only surface new listings.

## Setup

```bash
git clone https://github.com/biswajeetdev/job-pipeline
cd job-pipeline
pip install -r requirements.txt

# For LLM scoring (free):
gh auth login
```

## Usage

```bash
# Full run — scrape + LLM score + email drafts for top matches
python3 run_all.py

# Keyword filter only (no API calls)
python3 run_all.py --no-llm

# Also generate cold outreach emails
python3 run_all.py --outreach

# Scraper only (no portal scanner)
python3 pipeline.py

# Limit HN comments fetched (faster for testing)
python3 pipeline.py --limit 50 --threshold 7
```

## LinkedIn source

`linkedin_source.py` scrapes LinkedIn job listings through [JobSpy](https://github.com/speedyapply/JobSpy)
and returns the same dict shape as every other source, so `main()` just
concatenates it.

```bash
# Standalone, to see what a query returns before wiring it into a full run
python3 linkedin_source.py --terms "Chief of Staff" --location "Bangalore, India"

# Skip it during a normal run (it is the slowest source)
python3 pipeline.py --no-linkedin
```

Default search terms target Founder's Office / Chief of Staff / startup ops
roles. Override with `LINKEDIN_TERMS` and `LINKEDIN_LOCATIONS` in `.env`.

**LinkedIn rate-limits scrapers aggressively.** Defaults are deliberately low —
25 results per query, a 4-second gap between queries. If queries start returning
zero, you are being throttled: raise `LINKEDIN_DELAY`, lower `LINKEDIN_RESULTS`,
and wait. The scraper never raises; it logs and returns an empty list, so a block
degrades this one source instead of killing the run.

This reads public job listings only. It does not touch profiles, does not log in,
and does not automate applications — LinkedIn's ToS prohibits automated account
activity, and the account is worth more than the automation.

## Contact enrichment

`apollo_enrich.py` attaches contacts to high-scoring jobs, cheapest source first:

1. **The job posting itself.** JobSpy surfaces any e-mail the employer published
   in the description. Free, no API call, no credit.
2. **Apollo organization enrichment.** Confirms the company domain.
3. **Apollo people match.** Reveals a work e-mail. **Spends a credit.**

```bash
python3 apollo_enrich.py                    # dry run — shows the plan, spends nothing
python3 apollo_enrich.py --commit           # execute
python3 apollo_enrich.py --commit --max-credits 5
```

It is **dry-run by default** and has a hard credit cap per run, because the
credit pool is finite and easy to burn by accident.

Step 3 needs a name you supply via `--names contacts_in.csv`
(`company,first_name,last_name`). Apollo *search* is locked on this plan, so
enrichment can confirm a person you can already name but cannot discover one.
Get names from the posting or the company's own site.

## Applying

This pipeline stops at "here is a scored job and a contact." It does not submit
anything. Use [`application-automation`](https://github.com/biswajeetdev/application-automation)
to fill forms — it screenshots before submit so a human approves every send.

That boundary is deliberate. Bulk auto-apply is counterproductive for the roles
this pipeline targets: Founder's Office and Chief of Staff postings gate on
custom written answers precisely to filter out volume applicants.

## Personalizing

Edit the `PROFILE` dict in `pipeline.py` and `CANDIDATE` dict in `outreach_engine.py` with your own details:

```python
PROFILE = """
Name: Your Name
Email: you@example.com
Skills: python, node, ...
Target: Founding Engineer, ...
"""
```

Also edit `INCLUDE_ANY` / `EXCLUDE_ALL` keyword lists to match your target roles.

## Output files

| File | Contents |
|------|----------|
| `jobs.csv` | All matched jobs with LLM score (0–10), reason, source, URL |
| `contacts.csv` | Contacts for top matches, with `email_source` showing where each came from |
| `email_drafts.md` | Cold email drafts for top-scoring matches |
| `outreach_drafts.md` | Curated outreach for specific company targets |
| `seen.json` | Dedup state — prevents re-surfacing old listings |

All output files are gitignored (personal data). Only scripts are tracked.

## Stack

- Python 3.11+
- `requests` — HTTP scraping
- `fpdf2` — PDF cover letter generation
- GitHub Models API — free LLM inference (gpt-4o-mini)
- No database, no cloud infra — just files and a cron job

## License

MIT
