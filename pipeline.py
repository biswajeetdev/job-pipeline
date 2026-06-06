#!/usr/bin/env python3
"""
Job Pipeline — finds startup jobs matching Biswajeet Kumar's profile.
Sources: Remotive API + HN "Who is Hiring" + Wellfound RSS + YC Work at a Startup
Scoring:  GitHub Models free LLM (gpt-4o-mini)
Output:   ~/job-pipeline/jobs.csv  +  ~/job-pipeline/email_drafts.md

Usage:
    python3 pipeline.py               # full run
    python3 pipeline.py --no-llm      # keyword filter only, no API calls
    python3 pipeline.py --limit 50    # limit HN comments fetched
"""

import os, json, re, html, time, argparse, subprocess, hashlib
from datetime import datetime
from pathlib import Path
import requests

# ── Paths ────────────────────────────────────────────────────────────────────
DIR        = Path(__file__).parent
JOBS_CSV   = DIR / "jobs.csv"
DRAFTS_MD  = DIR / "email_drafts.md"
SEEN_FILE  = DIR / "seen.json"

# ── Candidate profile (scoring reference) ────────────────────────────────────
PROFILE = """
Name: Biswajeet Kumar
Email: thisisbiswajeetkumar@gmail.com
Education: Wabash College (US), graduated Jan 2025, CS minor + PPE major
Experience: 1 yr — CRIS internship: Node.js→Python migration (+20% throughput), ops automation
Skills: Python, Node.js, REST APIs, web scraping, automation, data pipelines,
        FastAPI, Flask, Django, PostgreSQL, pandas, Git, n8n, OpenAI API
Location: India — open to remote worldwide OR India onsite/remote
Target: Founding Engineer, Early Backend Dev, Automation Engineer,
        Founder's Office (technical), Python Developer at seed/Series A startups
Available: Immediately. Contract or full-time.
"""

# ── Keyword filters ───────────────────────────────────────────────────────────
INCLUDE_ANY = [
    "python", "node", "nodejs", "automation", "backend", "api", "fastapi",
    "django", "flask", "data pipeline", "scraping", "integration", "startup",
    "founding engineer", "early engineer", "full stack", "fullstack",
    "backend engineer", "software engineer", "developer", "remote",
    # internships & fellowships
    "intern", "internship", "fellowship", "fellow", "apprentice", "apprenticeship",
    "trainee", "research assistant", "research intern", "student developer",
    "junior developer", "junior engineer", "entry level", "entry-level",
    "new grad", "recent grad", "graduate developer", "0-2 years",
]
EXCLUDE_ALL = [
    "10+ years", "15+ years", "c++ only", "java only", "ios developer",
    "android developer", "unity", "game developer",
    "must be based in us", "us citizens only", "us work authorization only",
]

GH_MODEL_URL = "https://models.inference.ai.azure.com/chat/completions"
GH_MODEL     = "gpt-4o-mini"


def get_hn_hiring_thread_id() -> int:
    """Auto-detect current month's HN 'Who is Hiring?' thread ID."""
    now = datetime.now()
    for delta in [0, 1]:  # try current month, then previous
        month = (now.month - delta - 1) % 12 + 1
        year = now.year if now.month - delta >= 1 else now.year - 1
        month_name = datetime(year, month, 1).strftime("%B %Y")
        try:
            r = requests.get(
                "https://hn.algolia.com/api/v1/search",
                params={"query": f"Ask HN: Who is Hiring? ({month_name})", "tags": "story", "hitsPerPage": 1},
                timeout=10,
            )
            hits = r.json().get("hits", [])
            if hits:
                print(f"[hn] found thread for {month_name}: {hits[0]['objectID']}")
                return int(hits[0]["objectID"])
        except Exception as e:
            print(f"[hn] thread lookup failed for {month_name}: {e}")
    return 47975571  # fallback: May 2026


# ── Helpers ───────────────────────────────────────────────────────────────────

def gh_token():
    try:
        tok = subprocess.check_output(["gh", "auth", "token"], text=True).strip()
        return tok if tok else None
    except Exception:
        return None

def strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()

def load_seen() -> set:
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()))
    return set()

def save_seen(seen: set):
    SEEN_FILE.write_text(json.dumps(sorted(seen)))

def text_matches(text: str, keywords: list) -> bool:
    t = text.lower()
    return any(k in t for k in keywords)


# ── Sources ───────────────────────────────────────────────────────────────────

def fetch_remotive() -> list[dict]:
    """Fetch software-dev + other remote jobs from Remotive public API."""
    categories = ["software-dev", "data", "devops-sysadmin"]
    result = []
    seen_ids: set = set()
    for category in categories:
        try:
            r = requests.get(
                "https://remotive.com/api/remote-jobs",
                params={"category": category},
                timeout=15,
            )
            r.raise_for_status()
            for j in r.json().get("jobs", []):
                jid = f"remotive-{j['id']}"
                if jid in seen_ids:
                    continue
                seen_ids.add(jid)
                desc = strip_html(j.get("description", ""))[:800]
                tags = " ".join(j.get("tags", []))
                result.append({
                    "id": jid,
                    "source": "remotive",
                    "company": j.get("company_name", ""),
                    "title": j.get("title", ""),
                    "location": j.get("candidate_required_location", "Worldwide"),
                    "url": j.get("url", ""),
                    "tags": tags,
                    "description": desc,
                    "published": j.get("publication_date", ""),
                })
        except Exception as e:
            print(f"[remotive] error ({category}): {e}")
    print(f"[remotive] fetched {len(result)} jobs across {len(categories)} categories")
    return result


def fetch_hn_hiring(limit: int = 200) -> list[dict]:
    """Search HN 'Who is Hiring' thread via Algolia for relevant comments."""
    search_queries = [
        "python remote",
        "node automation remote",
        "backend engineer python startup",
        "founding engineer remote",
        "automation pipeline india",
        "python developer seed series",
        "full stack engineer startup",
        "backend developer worldwide",
        "software engineer india remote",
        "api developer startup equity",
        "django fastapi engineer",
        "data engineer python remote",
        "early stage engineer python",
        "YC startup software engineer",
        # internship / fellowship
        "intern python backend",
        "internship software engineer remote",
        "fellowship developer",
        "research intern python",
        "junior developer intern startup",
        "software internship india remote",
        "paid internship backend",
        "student developer internship",
        "new grad engineer startup",
        "entry level engineer python",
        "graduate developer remote",
        "engineer intern worldwide",
        # India-specific
        "python backend bangalore india",
        "startup india remote backend engineer",
        "founding engineer india startup",
        "python developer india remote",
        "node developer india startup",
        "software engineer india bangalore",
        "backend developer india equity",
        "api engineer india startup hiring",
    ]
    seen_ids = set()
    results = []
    thread_id = get_hn_hiring_thread_id()

    import time as _time
    # Fetch HN comments from the last 60 days (thread may be weeks old)
    cutoff_ts = int(_time.time()) - (60 * 24 * 3600)

    for query in search_queries:
        try:
            r = requests.get(
                "https://hn.algolia.com/api/v1/search",
                params={
                    "query": query,
                    "tags": "comment",
                    "numericFilters": f"story_id={thread_id},created_at_i>{cutoff_ts}",
                    "hitsPerPage": 30,
                },
                timeout=10,
            )
            r.raise_for_status()
            for hit in r.json().get("hits", []):
                oid = hit.get("objectID", "")
                if oid in seen_ids:
                    continue
                seen_ids.add(oid)
                text = strip_html(hit.get("comment_text", ""))
                if len(text) < 80:
                    continue

                # Extract company name (usually first line / first | segment)
                first_line = text.split("\n")[0][:120]
                # Extract URL if any
                urls = re.findall(r"https?://[^\s\|>]+", text)
                url = urls[0] if urls else f"https://news.ycombinator.com/item?id={oid}"
                # Guess location
                location_hints = re.findall(
                    r"\b(remote|worldwide|india|bangalore|bengaluru|mumbai|delhi|hyderabad|pune)\b",
                    text.lower()
                )

                results.append({
                    "id": f"hn-{oid}",
                    "source": "hn-hiring",
                    "company": first_line[:60],
                    "title": "See posting",
                    "location": ", ".join(dict.fromkeys(location_hints)) or "see posting",
                    "url": url,
                    "tags": "",
                    "description": text[:800],
                    "published": hit.get("created_at", ""),
                })

                if len(results) >= limit:
                    break
        except Exception as e:
            print(f"[hn-hiring] query '{query}' error: {e}")

        time.sleep(0.3)

    print(f"[hn-hiring] fetched {len(results)} unique posts")
    return results


def fetch_wellfound() -> list[dict]:
    """Fetch remote Python/Node startup jobs from Wellfound RSS."""
    import xml.etree.ElementTree as ET
    feeds = [
        "https://wellfound.com/jobs/rss?remote=true&role=engineer&skill=python",
        "https://wellfound.com/jobs/rss?remote=true&role=engineer&skill=node",
    ]
    results = []
    for url in feeds:
        try:
            r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code != 200:
                continue
            root = ET.fromstring(r.text)
            for item in root.findall(".//item")[:30]:
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                desc = strip_html(item.findtext("description") or "")[:600]
                pub = (item.findtext("pubDate") or "")
                if not link:
                    continue
                company = title.split(" - ")[0] if " - " in title else title
                results.append({
                    "id": f"wellfound-{abs(hash(link))}",
                    "source": "wellfound",
                    "company": company,
                    "title": title.split(" - ")[1] if " - " in title else title,
                    "location": "remote",
                    "url": link,
                    "tags": "",
                    "description": desc,
                    "published": pub,
                })
        except Exception as e:
            print(f"[wellfound] error fetching {url}: {e}")
    print(f"[wellfound] fetched {len(results)} jobs")
    return results


def _ddg_search(query: str, max_results: int = 10) -> list[dict]:
    """Search DuckDuckGo Lite and return [{title, url, snippet}]."""
    from urllib.parse import urlparse, parse_qs, unquote, quote
    try:
        r = requests.get(
            f"https://lite.duckduckgo.com/lite/?q={quote(query)}&kl=in-en",
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                "Referer": "https://lite.duckduckgo.com/",
            },
            timeout=15,
        )
        if not r.ok:
            return []
        text = r.text
        snippets = [re.sub(r"<[^>]+>", " ", m).strip()
                    for m in re.findall(r'<td[^>]*class="result-snippet"[^>]*>([\s\S]*?)</td>', text)]
        results, idx = [], 0
        for m in re.finditer(r'<a\s[^>]*rel="nofollow"[^>]*href="([^"]*uddg=[^"]+)"[^>]*>([\s\S]*?)</a>', text):
            href = m.group(1)
            try:
                raw = "https:" + href if href.startswith("//") else href
                uddg = parse_qs(urlparse(raw).query).get("uddg", [""])[0]
                url = unquote(uddg) if uddg else href
            except Exception:
                url = href
            if not url or "duckduckgo.com" in url or "bing.com" in url:
                continue
            title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
            results.append({"title": title, "url": url, "snippet": snippets[idx] if idx < len(snippets) else ""})
            idx += 1
            if len(results) >= max_results:
                break
        return results
    except Exception as e:
        print(f"[ddg] error: {e}")
        return []


def fetch_internshala() -> list[dict]:
    """Fetch Python/backend/Node internships from Internshala (India's #1 internship platform)."""
    pages = [
        ("python-wfh",  "https://internshala.com/internships/python-work-from-home-jobs/"),
        ("python",      "https://internshala.com/internships/python-internship/"),
        ("backend-wfh", "https://internshala.com/internships/backend-development-work-from-home-jobs/"),
        ("nodejs-wfh",  "https://internshala.com/internships/nodejs-work-from-home-jobs/"),
        ("data-wfh",    "https://internshala.com/internships/data-science-work-from-home-jobs/"),
    ]
    results: list[dict] = []
    seen: set = set()
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://internshala.com/",
    }
    for tag, url in pages:
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code != 200:
                print(f"[internshala] {tag}: HTTP {r.status_code}")
                continue
            text = r.text
            # Actual Internshala HTML structure (verified):
            # title: <a class="job-title-href" ...>Title</a>
            # company: <a class="company-name" ...>Company Name\n ...noise... </a>
            titles_raw    = re.findall(r'class="job-title-href"[^>]*>([^<]+)<', text)
            companies_raw = re.findall(r'class="company-name"[^>]*>(.*?)</a>', text, re.DOTALL)
            companies     = [
                next((ln.strip() for ln in re.sub(r"<[^>]+>", "", c).split("\n") if ln.strip()), "see posting")
                for c in companies_raw
            ]
            links         = re.findall(r'href="(/internship/detail/[^"?#]+)"', text)

            for i, link in enumerate(links[:15]):
                full_url = f"https://internshala.com{link}"
                uid = f"internshala-{hashlib.md5(full_url.encode()).hexdigest()[:12]}"
                if uid in seen:
                    continue
                seen.add(uid)
                title   = titles_raw[i].strip() if i < len(titles_raw) else "Tech Internship"
                company = companies[i]           if i < len(companies)  else "see posting"
                location = "Work from home (India)" if "wfh" in tag else "India"
                desc = f"{title} at {company}. {location}. Python/backend internship via Internshala."
                results.append({
                    "id": uid,
                    "source": "internshala",
                    "company": company,
                    "title": title,
                    "location": location,
                    "url": full_url,
                    "tags": f"internship india {tag}",
                    "description": desc,
                    "published": "",
                })
        except Exception as e:
            print(f"[internshala] {tag} error: {e}")
        time.sleep(0.5)
    print(f"[internshala] found {len(results)} internships")
    return results


def fetch_remoteok() -> list[dict]:
    """Fetch remote Python/Node/automation jobs from RemoteOK public JSON API."""
    tags = ["python", "backend", "node", "automation", "api"]
    results: list[dict] = []
    seen: set = set()
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"}
    for tag in tags:
        try:
            r = requests.get(f"https://remoteok.com/api?tag={tag}", headers=headers, timeout=15)
            if r.status_code != 200:
                print(f"[remoteok] {tag}: HTTP {r.status_code}")
                continue
            for job in r.json():
                if not isinstance(job, dict) or not job.get("position"):
                    continue
                url = job.get("url") or f"https://remoteok.com/remote-jobs/{job.get('id','')}"
                uid = f"remoteok-{hashlib.md5(url.encode()).hexdigest()[:12]}"
                if uid in seen:
                    continue
                seen.add(uid)
                desc = strip_html(job.get("description", ""))[:600]
                loc = job.get("location", "Worldwide") or "Worldwide"
                results.append({
                    "id": uid,
                    "source": "remoteok",
                    "company": job.get("company", "see posting"),
                    "title": job.get("position", "")[:120],
                    "location": loc,
                    "url": url,
                    "tags": " ".join(job.get("tags", [])),
                    "description": desc,
                    "published": job.get("date", ""),
                })
        except Exception as e:
            print(f"[remoteok] {tag} error: {e}")
        time.sleep(0.3)
    print(f"[remoteok] fetched {len(results)} remote jobs")
    return results


def fetch_yc() -> list[dict]:
    """Fetch YC startup tech jobs via HN Algolia (workatastartup.com blocks scraping)."""
    thread_id = get_hn_hiring_thread_id()
    cutoff_ts = int(time.time()) - 60 * 24 * 3600  # last 60 days

    yc_queries = [
        "YC startup python backend remote",
        "Y Combinator founding engineer python",
        "YC W25 OR YC S25 OR YC W24 software engineer remote",
        "YC batch automation backend api developer",
        "YC startup founding engineer full stack remote",
    ]

    seen: set[str] = set()
    results: list[dict] = []

    for query in yc_queries:
        if len(results) >= 30:
            break
        try:
            r = requests.get(
                "https://hn.algolia.com/api/v1/search",
                params={
                    "query": query,
                    "tags": "comment",
                    "numericFilters": f"story_id={thread_id},created_at_i>{cutoff_ts}",
                    "hitsPerPage": 20,
                },
                timeout=10,
            )
            for hit in r.json().get("hits", []):
                raw = strip_html(hit.get("comment_text") or "")
                if len(raw) < 80:
                    continue
                # Only include posts that mention YC affiliation
                if not re.search(r'\b(yc[- ]?[sw]\d{2}|y combinator|yc startup|yc batch|yc backed)\b', raw, re.I):
                    continue
                oid = hit["objectID"]
                if oid in seen:
                    continue
                seen.add(oid)
                url = re.search(r'https?://[^\s|>)<\]]+', raw)
                job_url = url.group(0).rstrip(".,;)") if url else f"https://news.ycombinator.com/item?id={oid}"
                first_line = next((l.strip() for l in raw.split("\n") if len(l.strip()) > 5), "YC startup")[:80]
                loc_hints = re.findall(r'\b(remote|worldwide|india|bengaluru|bangalore|mumbai|delhi|anywhere)\b', raw, re.I)
                location = ", ".join(dict.fromkeys(h.lower() for h in loc_hints[:2])) or "see posting"
                results.append({
                    "id":          f"yc-{oid}",
                    "source":      "yc-hn",
                    "company":     first_line,
                    "title":       "See posting",
                    "location":    location,
                    "url":         job_url,
                    "tags":        "yc startup",
                    "description": raw[:600],
                    "published":   hit.get("created_at", ""),
                })
        except Exception as e:
            print(f"[yc] query '{query}' error: {e}")
        time.sleep(0.3)

    print(f"[yc] fetched {len(results)} YC jobs from HN")
    return results


# ── Filtering ─────────────────────────────────────────────────────────────────

def prefilter(jobs: list[dict]) -> list[dict]:
    """Keyword-based pre-filter before LLM scoring."""
    kept = []
    for j in jobs:
        blob = f"{j['title']} {j['company']} {j['tags']} {j['description']}".lower()
        if text_matches(blob, EXCLUDE_ALL):
            continue
        if text_matches(blob, INCLUDE_ANY):
            kept.append(j)
    print(f"[filter] {len(kept)} jobs passed keyword filter")
    return kept


# ── LLM Scoring ──────────────────────────────────────────────────────────────

def llm_call(token: str, messages: list[dict], max_tokens: int = 200) -> str:
    """Call GitHub Models API with retry on 429."""
    for attempt in range(4):
        r = requests.post(
            GH_MODEL_URL,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"model": GH_MODEL, "messages": messages, "max_tokens": max_tokens, "temperature": 0.2},
            timeout=20,
        )
        if r.status_code == 429:
            wait = 5 * (2 ** attempt)  # 5s, 10s, 20s, 40s
            print(f"    [rate limit] waiting {wait}s...")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    raise Exception("rate limit: all retries exhausted")


def score_job(job: dict, token: str) -> tuple[int, str]:
    """Score job 0-10 and return (score, reason)."""
    snippet = f"""
Company: {job['company']}
Title: {job['title']}
Location: {job['location']}
Tags: {job['tags']}
Description excerpt: {job['description'][:500]}
"""
    messages = [
        {
            "role": "system",
            "content": (
                "You score job postings for a specific candidate. "
                "Respond ONLY with: SCORE: N\\nREASON: one sentence. N is 0-10."
            ),
        },
        {
            "role": "user",
            "content": f"Candidate profile:\n{PROFILE}\n\nJob posting:\n{snippet}\n\n"
                       "Score how well this job matches the candidate (0=no fit, 10=perfect). "
                       "Penalize heavily if: requires 5+ years experience, requires US visa only, "
                       "is not remote-friendly or India-based. Reward: early-stage startup, Python/Node, "
                       "remote-friendly, automation/backend work.",
        },
    ]
    try:
        resp = llm_call(token, messages, max_tokens=80)
        score_match = re.search(r"SCORE:\s*(\d+)", resp)
        reason_match = re.search(r"REASON:\s*(.+)", resp)
        score = int(score_match.group(1)) if score_match else 0
        reason = reason_match.group(1).strip() if reason_match else resp[:100]
        return min(score, 10), reason
    except Exception as e:
        return 0, f"scoring error: {e}"


def generate_email(job: dict, token: str) -> str:
    """Generate a personalized cold email for this job."""
    messages = [
        {
            "role": "system",
            "content": (
                "Write a short, genuine cold outreach email (under 150 words). "
                "No generic phrases. Reference something specific about the company. "
                "Close with a specific ask. Sign as Biswajeet Kumar."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Candidate:\n{PROFILE}\n\n"
                f"Job at {job['company']} — {job['title']}\n"
                f"Location: {job['location']}\n"
                f"Posting excerpt: {job['description'][:400]}\n\n"
                "Write the email. Subject line first, then blank line, then body."
            ),
        },
    ]
    try:
        return llm_call(token, messages, max_tokens=300)
    except Exception as e:
        return f"[email generation failed: {e}]"


# ── Output ────────────────────────────────────────────────────────────────────

CSV_FIELDS = ["score", "company", "title", "location", "url", "source", "reason", "published", "applied", "notes"]

def save_csv(jobs: list[dict]):
    import csv as _csv
    # Preserve existing applied/notes values by merging on URL
    existing = {}
    if JOBS_CSV.exists():
        with open(JOBS_CSV, newline="") as f:
            for row in _csv.DictReader(f):
                existing[row["url"]] = {"applied": row.get("applied", ""), "notes": row.get("notes", "")}
    for j in jobs:
        prev = existing.get(j.get("url", ""), {})
        j.setdefault("applied", prev.get("applied", ""))
        j.setdefault("notes", prev.get("notes", ""))
    jobs_sorted = sorted(jobs, key=lambda x: x.get("score", 0), reverse=True)
    with open(JOBS_CSV, "w", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(jobs_sorted)
    print(f"[output] {len(jobs_sorted)} jobs saved to {JOBS_CSV}")


def save_drafts(jobs: list[dict]):
    lines = [
        f"# Email Drafts — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n",
        f"Generated for top {len(jobs)} matches.\n\n---\n",
    ]
    for j in jobs:
        lines.append(f"## {j['company']} — Score {j['score']}/10\n")
        lines.append(f"**URL:** {j['url']}\n")
        lines.append(f"**Reason:** {j.get('reason','')}\n\n")
        lines.append("**Draft email:**\n")
        lines.append("```\n" + j.get("email_draft", "[not generated]") + "\n```\n\n---\n")
    DRAFTS_MD.write_text("\n".join(lines))
    print(f"[output] email drafts saved to {DRAFTS_MD}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM scoring")
    parser.add_argument("--limit", type=int, default=200, help="Max HN comments to process")
    parser.add_argument("--threshold", type=int, default=6, help="Min score for email drafts")
    args = parser.parse_args()

    token = None
    if not args.no_llm:
        token = gh_token()
        if not token:
            print("[warn] No GitHub token — run 'gh auth login'. Falling back to keyword filter only.")
            args.no_llm = True

    seen = load_seen()

    # Fetch
    all_jobs = (
        fetch_remotive() +
        fetch_hn_hiring(limit=args.limit) +
        fetch_wellfound() +
        fetch_yc() +
        fetch_internshala() +
        fetch_remoteok()
    )

    # Deduplicate against seen
    new_jobs = [j for j in all_jobs if j["id"] not in seen]
    print(f"[dedup] {len(new_jobs)} new jobs (skipped {len(all_jobs)-len(new_jobs)} seen)")

    # Keyword filter
    filtered = prefilter(new_jobs)

    if not filtered:
        print("No new matching jobs found.")
        return

    # LLM score
    if not args.no_llm:
        print(f"[llm] Scoring {len(filtered)} jobs...")
        for i, j in enumerate(filtered):
            score, reason = score_job(j, token)
            j["score"] = score
            j["reason"] = reason
            print(f"  [{i+1}/{len(filtered)}] {j['company'][:30]:30s} score={score} {reason[:60]}")
            time.sleep(1.5)  # rate limit
    else:
        for j in filtered:
            j["score"] = 5
            j["reason"] = "keyword match (no LLM)"

    # Mark all fetched as seen (even unscored)
    for j in all_jobs:
        seen.add(j["id"])
    save_seen(seen)

    # Save CSV
    save_csv(filtered)

    # Generate emails for top matches
    top = [j for j in filtered if j.get("score", 0) >= args.threshold]
    top = sorted(top, key=lambda x: x["score"], reverse=True)[:10]

    if top and not args.no_llm:
        print(f"[emails] Generating drafts for {len(top)} top matches...")
        for j in top:
            j["email_draft"] = generate_email(j, token)
            time.sleep(0.5)
    elif top:
        for j in top:
            j["email_draft"] = f"[Run without --no-llm to generate email for {j['company']}]"

    save_drafts(top)

    print(f"\nDone. {len(filtered)} scored, {len(top)} email drafts written.")
    print(f"  CSV:    {JOBS_CSV}")
    print(f"  Drafts: {DRAFTS_MD}")


if __name__ == "__main__":
    main()
