import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pipeline  # noqa: E402


def job(title, description=""):
    return {"title": title, "company": "Acme", "tags": "", "description": description}


def test_founders_office_roles_pass():
    kept = pipeline.prefilter([job("Founder's Office Associate"), job("Chief of Staff to CEO")])
    assert len(kept) == 2


def test_cos_substring_no_longer_matches_unrelated_jobs():
    kept = pipeline.prefilter([job("Cost Accountant", "reduce costs"), job("macOS Support Technician")])
    assert kept == []
