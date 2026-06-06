# job-pipeline

AI-powered job search pipeline. Scrapes remote job boards, scores matches with an LLM, and generates cold outreach emails — all from the terminal with zero manual triage.

## What it does

| Step | Script | Output |
|------|--------|--------|
| Scrape 6 sources | `pipeline.py` | `jobs.csv` |
| LLM-score each match | `pipeline.py` | scores in `jobs.csv` |
| Generate outreach emails | `outreach_engine.py` | `outreach_drafts.md` |
| Run everything | `run_all.py` | both outputs |

**Sources scraped:**
- [Remotive](https://remotive.com) — remote software jobs (API)
- [HN "Who is Hiring?"](https://news.ycombinator.com) — auto-detects current month's thread
- [Wellfound](https://wellfound.com) — startup jobs (RSS)
- [YC Work at a Startup](https://www.ycombinator.com/jobs) — YC-backed startups via HN Algolia
- [Internshala](https://internshala.com) — India internships
- [RemoteOK](https://remoteok.com) — remote-only jobs (public API)

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
