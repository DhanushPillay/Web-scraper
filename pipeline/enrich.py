"""
Enrich — Sniffer dek + 3 bullets (free, no paid LLM)
Uses trafilatura for extraction if needed, sumy LSA for bullets.
ponytail: 50 lines, deterministic, offline. Upgrade to distilbart when you have 1GB RAM.
"""
import re
from typing import Dict, List

def _split_sentences(text: str) -> List[str]:
    # simple sentence split, avoids NLTK heavy
    text = re.sub(r"\s+", " ", text).strip()
    # keep abbreviations minimal
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if len(p.strip()) > 20]

def _extractive_bullets(text: str, n: int = 3) -> List[str]:
    if not text or len(text.split()) < 30:
        return []
    try:
        # sumy path
        from sumy.parsers.plaintext import PlaintextParser
        from sumy.nlp.tokenizers import Tokenizer
        from sumy.summarizers.lsa import LsaSummarizer
        from sumy.nlp.stemmers import Stemmer
        from sumy.utils import get_stop_words

        parser = PlaintextParser.from_string(text, Tokenizer("english"))
        stemmer = Stemmer("english")
        summ = LsaSummarizer(stemmer)
        summ.stop_words = get_stop_words("english")
        sents = summ(parser.document, n)
        bullets = [str(s).strip() for s in sents if str(s).strip()]
        # ensure 12-18w each, truncate
        out = []
        for b in bullets:
            w = b.split()
            if len(w) > 22:
                b = " ".join(w[:18]) + "…"
            out.append(b)
        if out:
            return out[:n]
    except Exception:
        pass

    # fallback: TF-IDF-ish simple (sentence with most title words)
    sents = _split_sentences(text)
    if len(sents) <= n:
        return sents[:n]
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
    # dedup similar
    out = []
    for _, s in scored:
        if not any(s[:30] in o for o in out):
            out.append(s)
        if len(out) >= n:
            break
    return out

def _make_dek(text: str, title: str = "") -> str:
    if not text:
        return ""
    sents = _split_sentences(text)
    if not sents:
        return text[:140]
    # prefer first sentence that is 15-35w and not equal to title
    for s in sents:
        w = len(s.split())
        if 12 <= w <= 32 and s.lower() not in title.lower():
            return s
    return sents[0][:160]

def enrich_article(article: Dict, fetch: bool = False) -> Dict:
    """Add dek, bullets, read_time to article dict. Mutates copy."""
    title = article.get("title", "") or ""
    excerpt = article.get("excerpt", "") or ""
    # try to use fetched body if available via trafilatura when fetch=True
    body = excerpt
    if fetch and article.get("link"):
        try:
            from trafilatura import bare_extraction
            import requests
            # quick fetch with timeout, but skip in pipeline default (slow)
            resp = requests.get(article["link"], timeout=6, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200 and "text/html" in resp.headers.get("content-type",""):
                doc = bare_extraction(resp.text, with_metadata=True, favor_recall=False)
                if doc and getattr(doc, "text", None) and len(doc.text.split()) > 80:
                    body = doc.text
        except Exception:
            pass

    dek = _make_dek(body, title)
    bullets = _extractive_bullets(body, 3)
    # ensure bullets not empty -> fallback to excerpt sentences
    if not bullets and excerpt:
        bullets = _split_sentences(excerpt)[:3]
    # read_time from body
    words = len(body.split())
    read_time = max(1, round(words / 225)) if words else article.get("read_time", 3)

    out = dict(article)
    out["dek"] = dek[:220]
    out["bullets"] = bullets[:3]
    out["read_time"] = read_time
    return out

def enrich_batch(articles: List[Dict], fetch: bool = False) -> List[Dict]:
    return [enrich_article(a, fetch=fetch) for a in articles]
