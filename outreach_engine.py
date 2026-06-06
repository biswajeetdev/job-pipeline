#!/usr/bin/env python3
"""
Outreach Engine — curated cold outreach for Biswajeet Kumar.
Targets: think tanks, funded startups, founder-led companies that hire freshers.

Outputs:
  ~/job-pipeline/outreach_targets.csv   — full target list with email guesses
  ~/job-pipeline/outreach_drafts.md     — cold email drafts for each target

Usage:
  python3 outreach_engine.py            # generate emails via LLM
  python3 outreach_engine.py --no-llm   # templates only, no API call
"""

import os, re, time, csv, argparse, subprocess
from pathlib import Path
from datetime import datetime

DIR = Path(__file__).parent
TARGETS_CSV = DIR / "outreach_targets.csv"
DRAFTS_MD   = DIR / "outreach_drafts.md"

GH_MODEL_URL = "https://models.inference.ai.azure.com/chat/completions"
GH_MODEL     = "gpt-4o-mini"

CANDIDATE = """
Name: Biswajeet Kumar
Email: thisisbiswajeetkumar@gmail.com
LinkedIn: https://www.linkedin.com/in/biswajeetkumar
GitHub: https://github.com/biswajeetdev
Location: New Delhi, India

Education:
  - Wabash College (USA) — BA Philosophy, Politics & Economics (PPE) + CS Minor, Jan 2025
  - IIT Patna — Exec MBA, GenAI & Product Management (in progress, 2028)

Experience:
  - Full Stack Dev Intern — Archon Tech (Python, Node.js, REST APIs)
  - Research Analyst Intern — Stephenson Institute (US think tank; policy research, data synthesis)
  - Ops & Systems Intern — CRIS, Government of India (migrated Node.js→Python, +20% throughput, ops automation for Indian Railways)
  - Data/Marketing Analyst — Adorant Group

Projects (GitHub: biswajeetdev):
  - rdb-alpha: Redis-protocol KV store from scratch in Python (RESP3, asyncio, zero deps — 25 commands)
  - doc-qa-ai: RAG document Q&A with Groq LLM + local embeddings (Streamlit, FAISS, sentence-transformers)
  - ai-policy-summarizer: AI tool to summarise and compare policy PDFs (Groq API, Streamlit)
  - application-automation: Playwright-based Greenhouse ATS form filler (YAML-driven)
  - finance-dashboard-api: Secured Node.js REST API (JWT, PostgreSQL, rate limiting, CORS hardening)
  - Calm-Notes: Full-stack notes app (TypeScript, React, PostgreSQL, Drizzle, Stripe)

Skills: Python, Node.js, FastAPI, Django, Flask, PostgreSQL, REST APIs,
        web scraping, automation, data pipelines, FAISS, Playwright, Git,
        n8n, OpenAI/Groq API, research synthesis, policy analysis
Available: Immediately. Full-time or contract. India onsite or remote worldwide.
"""

# ── Curated target list ───────────────────────────────────────────────────────
# Fields: segment, company, domain, contact_name, contact_title, email_guess,
#         linkedin_url, why_fit, role_type

TARGETS = [
    # ── THINK TANKS & POLICY RESEARCH ─────────────────────────────────────────
    {
        "segment": "think_tank",
        "company": "Takshashila Institution",
        "domain": "takshashila.org",
        "contact_name": "Nitin Pai",
        "contact_title": "Co-founder & Director",
        "email_guess": "nitin.pai@takshashila.org",
        "email_alt": "nitin@takshashila.org",
        "linkedin_url": "https://www.linkedin.com/in/nitinpai",
        "why_fit": "Tech policy think tank. Biswajeet's PPE + research + AI policy summarizer project aligns directly. They hire research associates with policy + data skills.",
        "role_type": "Research Associate / Technology Policy",
        "url": "https://takshashila.org",
    },
    {
        "segment": "think_tank",
        "company": "The Dialogue",
        "domain": "thedialogue.in",
        "contact_name": "Kazim Rizvi",
        "contact_title": "Founder & Executive Director",
        "email_guess": "kazim@thedialogue.in",
        "email_alt": "kazim.rizvi@thedialogue.in",
        "linkedin_url": "https://www.linkedin.com/in/kazimrizvi",
        "why_fit": "Digital policy startup, New Delhi. Intersection of technology + policy. Rizvi is very approachable. Small org that values generalists with tech + policy background.",
        "role_type": "Policy Research / Tech Research",
        "url": "https://thedialogue.in",
    },
    {
        "segment": "think_tank",
        "company": "iSPIRT",
        "domain": "ispirt.in",
        "contact_name": "Sharad Sharma",
        "contact_title": "Co-founder",
        "email_guess": "sharad@ispirt.in",
        "email_alt": "sharad.sharma@ispirt.in",
        "linkedin_url": "https://www.linkedin.com/in/sharadsharma",
        "why_fit": "Software product think tank — builds India's digital public infrastructure (UPI, ONDC, Beckn). Technical + policy combo is exactly their need.",
        "role_type": "Technology Fellow / Research Engineer",
        "url": "https://ispirt.in",
    },
    {
        "segment": "think_tank",
        "company": "Observer Research Foundation",
        "domain": "orfonline.org",
        "contact_name": "Bedavyasa Mohanty",
        "contact_title": "Associate Fellow, Cyber & Technology",
        "email_guess": "bmohanty@orfonline.org",
        "email_alt": "bedavyasa@orfonline.org",
        "linkedin_url": "https://www.linkedin.com/in/bedavyasamohanty",
        "why_fit": "ORF Cyber & Technology programme is one of India's best. They regularly hire junior research fellows with CS + policy background.",
        "role_type": "Junior Research Fellow — Technology",
        "url": "https://orfonline.org/research/technology",
    },
    {
        "segment": "think_tank",
        "company": "Centre for Internet and Society",
        "domain": "cis-india.org",
        "contact_name": "Amber Sinha",
        "contact_title": "Executive Director",
        "email_guess": "amber@cis-india.org",
        "email_alt": "amber.sinha@cis-india.org",
        "linkedin_url": "https://www.linkedin.com/in/ambersinha",
        "why_fit": "Digital rights + AI policy research. CIS regularly hires junior researchers with tech background. Bangalore-based.",
        "role_type": "Research Associate — Technology",
        "url": "https://cis-india.org",
    },
    {
        "segment": "think_tank",
        "company": "Vidhi Centre for Legal Policy",
        "domain": "vidhilegalpolicy.in",
        "contact_name": "Arghya Sengupta",
        "contact_title": "Founder & Research Director",
        "email_guess": "arghya@vidhilegalpolicy.in",
        "email_alt": "arghya.sengupta@vidhilegalpolicy.in",
        "linkedin_url": "https://www.linkedin.com/in/arghya-sengupta",
        "why_fit": "Leading policy research org with a tech law programme. Founder actively hires bright graduates with analytical skills + technical background.",
        "role_type": "Research Associate — Technology Law",
        "url": "https://vidhilegalpolicy.in",
    },
    {
        "segment": "think_tank",
        "company": "Prayas Energy Group",
        "domain": "prayaspune.org",
        "contact_name": "Shantanu Dixit",
        "contact_title": "Co-founder & Director",
        "email_guess": "shantanu@prayaspune.org",
        "email_alt": "shantanu.dixit@prayaspune.org",
        "linkedin_url": "https://www.linkedin.com/in/shantanudixit",
        "why_fit": "Energy data research NGO in Pune — uses Python extensively for data analysis of energy/power sector data. Hires analyst-engineers who can code.",
        "role_type": "Data Analyst / Research Engineer",
        "url": "https://prayaspune.org",
    },

    # ── FUNDED INDIA STARTUPS (fresher-friendly) ──────────────────────────────
    {
        "segment": "india_startup",
        "company": "Sarvam AI",
        "domain": "sarvam.ai",
        "contact_name": "Vivek Raghavan",
        "contact_title": "Co-founder",
        "email_guess": "vivek@sarvam.ai",
        "email_alt": "vivek.raghavan@sarvam.ai",
        "linkedin_url": "https://www.linkedin.com/in/raghavan-vivek",
        "why_fit": "India's own LLM company — $41M funded, building Indic AI. Actively hiring Python engineers. Biswajeet's AI tools + Python backend is a strong fit.",
        "role_type": "Software Engineer — Backend / AI",
        "url": "https://sarvam.ai",
    },
    {
        "segment": "india_startup",
        "company": "Hasura",
        "domain": "hasura.io",
        "contact_name": "Tanmai Gopal",
        "contact_title": "CEO & Co-founder",
        "email_guess": "tanmai@hasura.io",
        "email_alt": "tanmai.gopal@hasura.io",
        "linkedin_url": "https://www.linkedin.com/in/tanmaigopal",
        "why_fit": "YC company, Bangalore/remote, open source GraphQL engine. Strong engineering culture, hires junior devs who contribute to OSS. PostgreSQL-heavy which matches Biswajeet.",
        "role_type": "Software Engineer — Backend",
        "url": "https://hasura.io",
    },
    {
        "segment": "india_startup",
        "company": "Yellow.ai",
        "domain": "yellow.ai",
        "contact_name": "Raghu Ravinutala",
        "contact_title": "CEO & Co-founder",
        "email_guess": "raghu@yellow.ai",
        "email_alt": "raghu.ravinutala@yellow.ai",
        "linkedin_url": "https://www.linkedin.com/in/raghuravinutala",
        "why_fit": "Conversational AI platform, $102M raised. Uses Python extensively. Hires automation + API engineers. Bot automation matches Biswajeet's Playwright + API work.",
        "role_type": "Software Engineer — Automation / API",
        "url": "https://yellow.ai",
    },
    {
        "segment": "india_startup",
        "company": "BrowserStack",
        "domain": "browserstack.com",
        "contact_name": "Ritesh Arora",
        "contact_title": "CEO & Co-founder",
        "email_guess": "ritesh@browserstack.com",
        "email_alt": "ritesh.arora@browserstack.com",
        "linkedin_url": "https://www.linkedin.com/in/ritesh-arora",
        "why_fit": "Browser testing infrastructure, $200M raised. Core product is automation + testing. Biswajeet's Playwright-based automation is a direct skill match. India-headquartered.",
        "role_type": "Software Engineer — Automation",
        "url": "https://browserstack.com/careers",
    },
    {
        "segment": "india_startup",
        "company": "Chargebee",
        "domain": "chargebee.com",
        "contact_name": "Krish Subramanian",
        "contact_title": "CEO & Co-founder",
        "email_guess": "krish@chargebee.com",
        "email_alt": "krish.subramanian@chargebee.com",
        "linkedin_url": "https://www.linkedin.com/in/krishsubramanian",
        "why_fit": "Subscription billing SaaS, $250M raised, Chennai/remote. Python + Node.js backend team, actively hiring. Good comp even for freshers.",
        "role_type": "Software Engineer — Backend",
        "url": "https://chargebee.com/careers",
    },
    {
        "segment": "india_startup",
        "company": "Julep AI",
        "domain": "julep.ai",
        "contact_name": "Ishaan Lalit",
        "contact_title": "Founder & CEO",
        "email_guess": "ishaan@julep.ai",
        "email_alt": "ishaan.lalit@julep.ai",
        "linkedin_url": "https://www.linkedin.com/in/ishaanlalit",
        "why_fit": "India-based AI agent platform — very early stage, YC-backed. Biswajeet's AI tools + Python backend is a perfect fit. Small team = high impact.",
        "role_type": "Founding Engineer",
        "url": "https://julep.ai",
    },
    {
        "segment": "india_startup",
        "company": "Krutrim",
        "domain": "krutrim.com",
        "contact_name": "Amanpreet Singh",
        "contact_title": "CTO",
        "email_guess": "amanpreet@krutrim.com",
        "email_alt": "amanpreet.singh@krutrim.com",
        "linkedin_url": "https://www.linkedin.com/in/amanpreet-singh",
        "why_fit": "Ola's AI company — Indic LLM, $50M funded. Hiring Python engineers for AI infra. Bangalore-based.",
        "role_type": "Software Engineer — AI Infrastructure",
        "url": "https://krutrim.com",
    },

    # ── REMOTE-FIRST / YC COMPANIES ───────────────────────────────────────────
    {
        "segment": "remote_yc",
        "company": "PostHog",
        "domain": "posthog.com",
        "contact_name": "James Hawkins",
        "contact_title": "CEO & Co-founder",
        "email_guess": "james@posthog.com",
        "email_alt": "james.hawkins@posthog.com",
        "linkedin_url": "https://www.linkedin.com/in/james-hawkins-9aa7a3",
        "why_fit": "Fully remote product analytics, YC-backed, open source. They hire based on project quality not credentials. Python + PostgreSQL backend. Has hired India-based engineers before.",
        "role_type": "Software Engineer — Full Stack",
        "url": "https://posthog.com/careers",
    },
    {
        "segment": "remote_yc",
        "company": "Qdrant",
        "domain": "qdrant.tech",
        "contact_name": "Andrey Vasnetsov",
        "contact_title": "CTO & Co-founder",
        "email_guess": "andrey@qdrant.tech",
        "email_alt": "andrey.vasnetsov@qdrant.tech",
        "linkedin_url": "https://www.linkedin.com/in/andrey-vasnetsov",
        "why_fit": "Vector database for AI applications — fully remote, $28M raised. Biswajeet uses FAISS/embeddings in his projects (doc-qa-ai). Demonstrated real usage of the product space.",
        "role_type": "Software Engineer — Python / DevRel",
        "url": "https://qdrant.tech/careers",
    },
    {
        "segment": "remote_yc",
        "company": "AgentOps",
        "domain": "agentops.ai",
        "contact_name": "Alex Reibman",
        "contact_title": "CEO & Co-founder",
        "email_guess": "alex@agentops.ai",
        "email_alt": "alex.reibman@agentops.ai",
        "linkedin_url": "https://www.linkedin.com/in/alexreibman",
        "why_fit": "AI agent observability platform, YC W24, very early stage. Biswajeet built application-automation (Playwright agent) and AI tools. Good fit for a founding engineer.",
        "role_type": "Founding Engineer",
        "url": "https://agentops.ai",
    },
    {
        "segment": "remote_yc",
        "company": "Composio",
        "domain": "composio.dev",
        "contact_name": "Utkarsh Dixit",
        "contact_title": "CEO & Co-founder",
        "email_guess": "utkarsh@composio.dev",
        "email_alt": "utkarsh.dixit@composio.dev",
        "linkedin_url": "https://www.linkedin.com/in/utkarshdixit5",
        "why_fit": "AI integration/tooling platform, YC-backed, India founders. Biswajeet already has Composio CLI installed — knows the product. Small team, high growth.",
        "role_type": "Founding Engineer / DevRel",
        "url": "https://composio.dev",
    },
    {
        "segment": "remote_yc",
        "company": "Supabase",
        "domain": "supabase.io",
        "contact_name": "Paul Copplestone",
        "contact_title": "CEO & Co-founder",
        "email_guess": "paul@supabase.io",
        "email_alt": "paul.copplestone@supabase.io",
        "linkedin_url": "https://www.linkedin.com/in/paulcopplestone",
        "why_fit": "Fully remote, PostgreSQL-based backend-as-a-service. YC, $80M raised. Biswajeet has PostgreSQL + REST API experience. They hire India-based engineers.",
        "role_type": "Software Engineer — Backend",
        "url": "https://supabase.io/careers",
    },
    {
        "segment": "remote_yc",
        "company": "Neon",
        "domain": "neon.tech",
        "contact_name": "Nikita Shamgunov",
        "contact_title": "CEO & Co-founder",
        "email_guess": "nikita@neon.tech",
        "email_alt": "nikita.shamgunov@neon.tech",
        "linkedin_url": "https://www.linkedin.com/in/nikitashamgunov",
        "why_fit": "Serverless PostgreSQL, $100M raised, fully remote. Heavy PostgreSQL + Python ecosystem. Biswajeet's rdb-alpha (Redis from scratch) shows protocol-level understanding.",
        "role_type": "Software Engineer — Backend / Infra",
        "url": "https://neon.tech/careers",
    },
]


def gh_token():
    try:
        return subprocess.check_output(["gh", "auth", "token"], text=True).strip() or None
    except Exception:
        return None


def llm_call(token, messages, max_tokens=400):
    import requests as _req
    r = _req.post(
        GH_MODEL_URL,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"model": GH_MODEL, "messages": messages, "max_tokens": max_tokens, "temperature": 0.3},
        timeout=25,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def generate_cold_email(target: dict, token: str) -> str:
    segment_context = {
        "think_tank": (
            "This is a think tank / policy research organization. Lead with Biswajeet's "
            "PPE background, research internship at Stephenson Institute (a US think tank), "
            "and his AI policy summarizer project. DO NOT oversell technical skills — lead "
            "with research and analytical skills. End with asking for a 15-min research call."
        ),
        "india_startup": (
            "This is a funded Indian startup. Lead with concrete results from CRIS internship "
            "(Python migration, +20% throughput, Indian Railways ops automation). Mention 1 specific "
            "project that directly maps to their product. Ask for a quick call with the founder."
        ),
        "remote_yc": (
            "This is a remote-first YC-backed startup. Lead with rdb-alpha (Redis protocol from scratch, "
            "zero deps — shows CS depth) and the AI tools built. Be direct and brief — YC founders get "
            "many cold emails. Mention willing to do a paid trial project. Ask for async async intro."
        ),
    }

    prompt = f"""
Write a cold outreach email from Biswajeet Kumar to {target['contact_name']} ({target['contact_title']}) at {target['company']}.

Candidate profile:
{CANDIDATE}

Company context: {target['why_fit']}

Writing guidance: {segment_context.get(target['segment'], '')}

Rules:
- Under 120 words in the body
- Subject line first, then blank line, then body
- No generic openers ("I hope this finds you well", "My name is")
- Reference something SPECIFIC about {target['company']} — not just the category
- One concrete result or project from Biswajeet's background relevant to THIS company
- Clear single ask at the end
- Sign as: Biswajeet Kumar | thisisbiswajeetkumar@gmail.com | github.com/biswajeetdev
"""
    return llm_call(token, [
        {"role": "system", "content": "You write precise, non-generic cold outreach emails for a job seeker. No clichés. Real specificity."},
        {"role": "user", "content": prompt},
    ], max_tokens=350)


def save_csv(targets):
    fields = ["segment", "company", "contact_name", "contact_title", "email_guess", "email_alt", "role_type", "url", "why_fit"]
    with open(TARGETS_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(targets)
    print(f"[output] {len(targets)} targets saved to {TARGETS_CSV}")


def save_drafts(targets):
    lines = [f"# Outreach Drafts — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"]
    for seg in ["think_tank", "india_startup", "remote_yc"]:
        seg_name = {"think_tank": "THINK TANKS & POLICY RESEARCH", "india_startup": "FUNDED INDIA STARTUPS", "remote_yc": "REMOTE / YC COMPANIES"}[seg]
        lines.append(f"---\n## {seg_name}\n")
        for t in [x for x in targets if x["segment"] == seg]:
            lines.append(f"\n### {t['company']} — {t['contact_name']} ({t['contact_title']})\n")
            lines.append(f"**Email:** {t['email_guess']} (alt: {t.get('email_alt','')})\n")
            lines.append(f"**Role:** {t['role_type']}\n")
            lines.append(f"**URL:** {t['url']}\n\n")
            lines.append("**Draft:**\n```\n" + t.get("email_draft", "[not generated — run without --no-llm]") + "\n```\n")
    DRAFTS_MD.write_text("".join(lines))
    print(f"[output] drafts saved to {DRAFTS_MD}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--segment", default="all", help="think_tank | india_startup | remote_yc | all")
    args = parser.parse_args()

    token = None
    if not args.no_llm:
        token = gh_token()
        if not token:
            print("[warn] no GitHub token, falling back to --no-llm")
            args.no_llm = True

    targets = TARGETS if args.segment == "all" else [t for t in TARGETS if t["segment"] == args.segment]

    save_csv(targets)

    if not args.no_llm:
        print(f"[llm] generating {len(targets)} cold emails...")
        for i, t in enumerate(targets):
            t["email_draft"] = generate_cold_email(t, token)
            print(f"  [{i+1}/{len(targets)}] {t['company']}")
            time.sleep(0.6)
    else:
        for t in targets:
            t["email_draft"] = f"[Run without --no-llm to generate email for {t['company']}]"

    save_drafts(targets)
    print(f"\nDone. {len(targets)} targets. Drafts at {DRAFTS_MD}")


if __name__ == "__main__":
    main()
