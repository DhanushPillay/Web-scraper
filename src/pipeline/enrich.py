"""
Enrich — Sniffer dek + 3 bullets (free, no paid LLM)
Uses trafilatura for body extraction when fetching; bullets are extractive and offline.
"""
import logging
import re
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

# Fetches are network-bound and mostly timeouts, so a small pool turns ~11 minutes of
# serial latency for a 110-article batch into seconds. MAX_FETCH sits above the normal
# batch size so the cap only bites on a pathological one; those articles use the excerpt.
MAX_FETCH = 200
FETCH_WORKERS = 8

def _split_sentences(text: str) -> list[str]:
    # simple sentence split, avoids NLTK heavy
    text = re.sub(r"\s+", " ", text).strip()
    # keep abbreviations minimal
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if len(p.strip()) > 20]

def _normalize_sentence(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"(\d+)\s*percent", r"\1%", s, flags=re.IGNORECASE)
    s = s.replace(" -- ", " — ").replace(" - ", " — ")
    if s and s[0].islower():
        s = s[0].upper() + s[1:]
    return s

def _toks(s: str):
    return set(re.findall(r"[a-zA-Z]{3,}", s.lower()))

def _jaccard(a: str, b: str) -> float:
    ta, tb = _toks(a), _toks(b)
    if not ta or not tb:
        return 1.0 if a[:30] == b[:30] else 0.0
    return len(ta & tb) / len(ta | tb)

def _is_dek(s: str, dek: str) -> bool:
    # exact match first: a short dek can share no tokens with a longer bullet,
    # so overlap alone lets the dek through as a bullet
    if not dek:
        return False
    return s == dek or _jaccard(s, dek) > 0.55 or s[:30] in dek or dek[:30] in s

def _extractive_bullets(text: str, n: int = 3, exclude: str = "", sents: list[str] | None = None) -> list[str]:
    if not text or len(text.split()) < 30:
        return []
    if sents is None:
        sents = _split_sentences(text)
    if len(sents) <= n:
        cleaned = [_normalize_sentence(s) for s in sents]
        if exclude:
            cleaned = [s for s in cleaned if not _is_dek(s, exclude)]
        return cleaned[:n]
    # score by word frequency
    words = re.findall(r"[a-zA-Z]{4,}", text.lower())
    freq = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    scored = []
    for s in sents:
        sc = sum(freq.get(w.lower(), 0) for w in re.findall(r"[a-zA-Z]{4,}", s))
        # penalty for very long
        sc = sc / (1 + len(s.split()) / 25)
        scored.append((sc, s))
    scored.sort(reverse=True)
    # dedup similar + vs dek, enforce varied openings
    out = []
    seen_openings = set()
    for _, s in scored:
        s = _normalize_sentence(s)
        if _is_dek(s, exclude):
            continue
        if any(_jaccard(s, o) > 0.55 for o in out):
            continue
        opening = " ".join(s.split()[:3]).lower()
        if opening in seen_openings:
            continue
        seen_openings.add(opening)
        w = s.split()
        if len(w) > 22:
            cut = " ".join(w[:18]).rsplit(",", 1)[0].rsplit(";", 1)[0]
            s = cut + "…"
        out.append(s)
        if len(out) >= n:
            break
    return out

def _make_dek(text: str, title: str = "", sents: list[str] | None = None) -> str:
    if not text:
        return ""
    if sents is None:
        sents = _split_sentences(text)
    if not sents:
        return text[:140]
    # prefer first sentence that is 15-35w and not equal to title
    for s in sents:
        w = len(s.split())
        if 12 <= w <= 32 and s.lower() not in title.lower():
            return _normalize_sentence(s)
    return _normalize_sentence(sents[0][:160])

def _fetch_body(link: str, excerpt: str) -> str:
    try:
        import requests
        from trafilatura import bare_extraction
        resp = requests.get(link, timeout=6, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code == 200 and "text/html" in resp.headers.get("content-type", ""):
            doc = bare_extraction(resp.text, with_metadata=True, favor_recall=False)
            if doc and getattr(doc, "text", None) and len(doc.text.split()) > 80:
                return doc.text
    except Exception:
        logger.debug("body fetch failed for %s", link, exc_info=True)
    return excerpt

def _enrich_body(article: dict, body: str) -> dict:
    title = article.get("title", "") or ""
    excerpt = article.get("excerpt", "") or ""
    sents = _split_sentences(body)
    dek = _make_dek(body, title, sents=sents)[:220]
    bullets = _extractive_bullets(body, 3, exclude=dek, sents=sents)
    if not bullets and excerpt:
        ex = [_normalize_sentence(s) for s in _split_sentences(excerpt)]
        bullets = [s for s in ex if not _is_dek(s, dek)][:3]
    # read_time from body
    words = len(body.split())
    read_time = max(1, round(words / 225)) if words else article.get("read_time", 3)

    out = dict(article)
    out["dek"] = dek
    out["bullets"] = bullets[:3]
    out["read_time"] = read_time
    return out

def enrich_article(article: dict, fetch: bool = False) -> dict:
    """Add dek, bullets, read_time to article dict. Mutates copy."""
    body = article.get("excerpt", "") or ""
    if fetch and article.get("link"):
        body = _fetch_body(article["link"], body)
    return _enrich_body(article, body)

def enrich_batch(articles: list[dict], fetch: bool = False) -> list[dict]:
    if not fetch:
        return [enrich_article(a, fetch=False) for a in articles]
    items = list(articles)
    links = [a.get("link") or "" for a in items]
    linked = [i for i, link in enumerate(links) if link]
    todo = linked[:MAX_FETCH]
    if len(todo) < len(linked):
        logger.info("fetch capped at %d articles: %d use excerpt only", MAX_FETCH, len(linked) - len(todo))
    bodies: dict[int, str] = {}
    if todo:
        with ThreadPoolExecutor(max_workers=min(FETCH_WORKERS, len(todo))) as pool:
            fetched = pool.map(lambda i: _fetch_body(links[i], items[i].get("excerpt", "") or ""), todo)
            bodies.update(zip(todo, fetched))
    return [
        _enrich_body(a, bodies[i] if i in bodies else (a.get("excerpt", "") or ""))
        for i, a in enumerate(items)
    ]
