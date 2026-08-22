"""
Validate — Sniffer data quality (no heavy deps by default)
ponytail: 30 lines of asserts catches 90% of bad data; upgrade to pandera/Great Expectations when you need lineage.
"""
from typing import List, Dict, Tuple

REQUIRED_FIELDS = ["title", "link"]

def validate_article(a: Dict) -> List[str]:
    errs = []
    for f in REQUIRED_FIELDS:
        v = a.get(f)
        if not v or not str(v).strip():
            errs.append(f"missing {f}")
    title = a.get("title", "")
    if title and len(title.strip()) < 10:
        errs.append("title too short")
    link = a.get("link", "")
    if link and not link.startswith(("http://", "https://")):
        errs.append("link not http")
    score = a.get("score", 0)
    try:
        if int(score) < 0:
            errs.append("score negative")
    except Exception:
        errs.append("score not int")
    return errs


def validate_batch(articles: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """Returns (valid, invalid_with_errors). Dedups by link."""
    seen = set()
    valid, invalid = [], []
    for a in articles:
        errs = validate_article(a)
        link = a.get("link")
        if link in seen:
            errs.append("duplicate link")
        if errs:
            invalid.append({**a, "_errors": errs})
        else:
            valid.append(a)
            if link:
                seen.add(link)
    return valid, invalid
