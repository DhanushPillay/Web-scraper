"""
Flask Application — Sniffer
Routes, background scheduler, sentiment analysis, trending topics,
auto-tagging, charts, export, personalized feed, and webhook/email stubs.
"""
import os
import re
import time
import io
import csv
import json
import logging
import traceback
import smtplib
import atexit
import socket
import ipaddress
from email.mime.text import MIMEText
from collections import Counter
from urllib.parse import urlparse
from typing import Any, Optional, Union, cast

from flask import (Flask, render_template, request, Response,
                   stream_with_context, jsonify, send_file)
from flask.typing import ResponseReturnValue
from web_scraper import NewsAggregator
from database import Database
from pipeline.enrich import enrich_batch as _enrich_batch
import nltk

# Security extensions
try:
    from flask_talisman import Talisman
    _talisman_available = True
except ImportError:
    _talisman_available = False

try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    _limiter_available = True
except ImportError:
    _limiter_available = False

try:
    from flask_cors import CORS
    _cors_available = True
except ImportError:
    _cors_available = False

# Attempt to import optional dependencies
try:
    from nltk.sentiment.vader import SentimentIntensityAnalyzer
    _vader_available = True
except (ImportError, LookupError):
    _vader_available = False

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    _scheduler_available = True
except ImportError:
    _scheduler_available = False

logger = logging.getLogger(__name__)

# Ensure NLTK data is downloaded (lazy, non-blocking)
def ensure_nltk_data():
    """Download NLTK data if missing. Called on first use, not at import."""
    for resource in ['tokenizers/punkt', 'tokenizers/punkt_tab',
                     'sentiment/vader_lexicon', 'corpora/stopwords']:
        try:
            nltk.data.find(resource)
        except LookupError:
            nltk.download(resource.split('/')[-1], quiet=True)

app = Flask(__name__)

# Defer NLTK download — call lazily on first sentiment/stopwords use
# ponytail: avoids blocking startup / network fail on import; will download on demand
_nltk_ensured = False

def _ensure_nltk_once():
    global _nltk_ensured
    if _nltk_ensured:
        return
    try:
        ensure_nltk_data()
    except Exception as e:
        logger.warning(f"NLTK data ensure failed: {e}")
    _nltk_ensured = True


def _humanize_time(value: str) -> str:
    """Humanize ISO/relative time string for display (no AI slop raw ISO)."""
    if not value or value.strip().lower() in ("recent", "recently", "today", "unknown"):
        return value.strip() if value else "Today"
    # Try ISO parse
    try:
        from datetime import datetime, timezone
        s = value.strip()
        # Handle '2026-08-22T08:36:47Z' etc
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = None
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(s[:25], fmt) if "%z" in fmt else datetime.strptime(s[:19], fmt)
                if dt:
                    break
            except Exception:
                continue
        if dt is None:
            # fromisoformat fallback
            dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = now - dt
        secs = int(delta.total_seconds())
        if secs < 0:
            return "Today"
        if secs < 60:
            return "now"
        if secs < 3600:
            return f"{secs//60}m ago"
        if secs < 86400:
            return f"{secs//3600}h ago"
        if secs < 604800:
            return f"{secs//86400}d ago"
        return dt.strftime("%b %d")
    except Exception:
        # contains relative like "5 hours ago" — keep short
        v = value.strip()
        # shorten verbose
        if "hour" in v.lower():
            try:
                n = int("".join(c for c in v if c.isdigit()) or "1")
                return f"{n}h ago"
            except:
                pass
        return value[:16]


@app.template_filter("humanize_time")
def humanize_time_filter(value):
    return _humanize_time(str(value) if value is not None else "")


@app.context_processor
def inject_article_image_helpers():
    """Letter-box fallback — no generic Unsplash, no duplication."""
    # ponytail: deterministic letter, no external photo
    source_meta = {
        'Hacker News': {'initials': 'HN', 'color': '#FF6600'},
        'TechCrunch': {'initials': 'TC', 'color': '#0A9E74'},
        'Reddit': {'initials': 'RE', 'color': '#FF4500'},
        'The Verge': {'initials': 'VG', 'color': '#E01E5A'},
        'Ars Technica': {'initials': 'AT', 'color': '#0086A8'},
        'GitHub Trending': {'initials': 'GH', 'color': '#24292E'},
        'arXiv': {'initials': 'AX', 'color': '#B31B1B'},
    }
    def fallback_data(source: str, title: str = "", link: str = ""):
        m = source_meta.get(source, {'initials': (source[:2] if source else 'SN').upper(), 'color': '#3F3F46'})
        return m

    # keep legacy helper for compat — now returns letter-box not Unsplash
    def fallback_image(source: str, title: str = "", link: str = ""):
        # reuse letter-box as image fallback will be rendered as div, not <img>
        return ""

    return {
        'article_fallback_data': fallback_data,
        'article_fallback_image': lambda source, title="", link="": fallback_image(source, title, link),
        'humanize_time': _humanize_time,
    }

# ──────────────────────────────────────────────
# Security Hardening
# ──────────────────────────────────────────────

# Trusted hosts (Flask 3.1+) — prevent Host header attacks
if os.getenv('RENDER'):
    app.config['TRUSTED_HOSTS'] = []  # ponytail: skip on Render (proxy complicates host matching)
else:
    trusted_hosts = os.getenv('TRUSTED_HOSTS', '').split(',') if os.getenv('TRUSTED_HOSTS') else ['localhost', '127.0.0.1']
    app.config['TRUSTED_HOSTS'] = [h.strip() for h in trusted_hosts if h.strip()]

# Request size limits (DoS mitigation)
app.config['MAX_CONTENT_LENGTH'] = 1 * 1024 * 1024  # 1 MB
app.config['MAX_FORM_MEMORY_SIZE'] = 500 * 1024     # 500 KB
app.config['MAX_FORM_PARTS'] = 100

# Secret key & rotation (Flask 3.1+)
_secret = os.getenv('SECRET_KEY')
if not _secret:
    logger.warning("SECRET_KEY not set — using ephemeral key (sessions will reset on restart)")
    _secret = os.urandom(32).hex()
app.config['SECRET_KEY'] = _secret
fallbacks = os.getenv('SECRET_KEY_FALLBACKS', '')
if fallbacks:
    app.config['SECRET_KEY_FALLBACKS'] = [k.strip() for k in fallbacks.split(',') if k.strip()]

# Session cookie hardening (even though no auth, defense in depth)
_is_secure_env = bool(os.getenv('RENDER') or os.getenv('DATABASE_URL') or os.getenv('FLASK_ENV') == 'production')
app.config.update(
    SESSION_COOKIE_SECURE=_is_secure_env,  # only force HTTPS in production
    SESSION_COOKIE_HTTPONLY=True,         # No JS access
    SESSION_COOKIE_SAMESITE='Lax',        # CSRF mitigation
)

# Security headers via Talisman
if _talisman_available:
    csp = {
        'default-src': ["'self'"],
        'script-src': ["'self'", "'unsafe-inline'"],  # inline scripts for now
        'style-src': ["'self'", "'unsafe-inline'", 'https://cdn.jsdelivr.net'],
        'img-src': ["'self'", 'data:', 'https:'],
        'font-src': ["'self'", 'https://cdn.jsdelivr.net'],
        'connect-src': ["'self'"],
        'frame-ancestors': ["'none'"],
        'base-uri': ["'self'"],
        'form-action': ["'self'"],
    }
    talisman = Talisman(
        app,
        content_security_policy=csp,
        force_https=False,  # PythonAnywhere handles TLS termination
        strict_transport_security=True,
        strict_transport_security_max_age=31536000,
        strict_transport_security_include_subdomains=True,
        frame_options=None,  # use CSP frame-ancestors only (avoids conflict)
        x_content_type_options='nosniff',
        referrer_policy='strict-origin-when-cross-origin',
        permissions_policy={
            'geolocation': '()',
            'microphone': '()',
            'camera': '()',
        },
    )
else:
    logger.warning("Flask-Talisman not available. Security headers disabled.")

# Rate limiting
if _limiter_available:
    storage_uri = os.getenv('RATE_LIMIT_STORAGE', 'memory://')
    limiter = Limiter(
        key_func=get_remote_address,
        app=app,
        default_limits=["200 per hour", "50 per minute"],
        storage_uri=storage_uri,
        strategy="fixed-window",
    )
else:
    limiter = None
    logger.warning("Flask-Limiter not available. Rate limiting disabled.")

# CORS — explicit origins only
if _cors_available:
    allowed_origins = os.getenv('ALLOWED_ORIGINS', '').split(',') if os.getenv('ALLOWED_ORIGINS') else []
    allowed_origins = [o.strip() for o in allowed_origins if o.strip()]
    if allowed_origins:
        CORS(app, origins=allowed_origins, supports_credentials=False)
    else:
        logger.info("ALLOWED_ORIGINS not set. CORS disabled for API endpoints.")
else:
    logger.warning("Flask-CORS not available. CORS not configured.")

# Initialize Database (shared)
db = Database()

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────
# Singleton aggregator so CACHE_TTL and health tracking actually work
_aggregator_instance: Optional[NewsAggregator] = None

def get_aggregator() -> NewsAggregator:
    """Return shared NewsAggregator (per-process singleton)."""
    global _aggregator_instance
    if _aggregator_instance is None:
        from web_scraper import NewsAggregator
        _aggregator_instance = NewsAggregator()
    return _aggregator_instance

# Stats cache (60s TTL) — avoids 7 COUNT(*) per page load
_stats_cache: dict = {'data': None, 'ts': 0.0}
_STATS_TTL = 60

def _get_gold_stats():
    """Try to serve stats from Gold layer (Parquet via DuckDB) — ponytail: falls back to DB."""
    try:
        from pathlib import Path
        import json as _json
        from datetime import datetime, timezone
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        gold_json = Path(f"data/gold/{day}/daily_stats.json")
        # legacy slash fallback
        if not gold_json.exists():
            alt = Path(f"data/gold/{day.replace('-', '/')}/daily_stats.json")
            if alt.exists():
                gold_json = alt
                day = day.replace("-", "/")
        if gold_json.exists():
            data = _json.loads(gold_json.read_text(encoding="utf-8"))
            # normalize to DB shape for template
            return {
                "total": data.get("total", 0),
                "today": data.get("total", 0),
                "saved": 0,  # gold doesn't track bookmarks
                "read": 0,
                "by_source": data.get("by_source", {}),
                "by_category": data.get("by_category", {}),
                "by_sentiment": {},
            }
        # Try DuckDB on Parquet (if gold was written as parquet)
        try:
            import duckdb
            gold_parquet = Path("data/gold")
            if gold_parquet.exists() and any(gold_parquet.rglob("*.parquet")):
                # query latest gold
                con = duckdb.connect()
                # ponytail: DuckDB reads hive-partitioned parquet directly
                q = con.execute("SELECT source, count(*) as c FROM read_parquet('data/gold/**/*.parquet', hive_partitioning=1) GROUP BY source").fetchall()
                by_source = {r[0]: r[1] for r in q}
                con.close()
                if by_source:
                    total = sum(by_source.values())
                    return {"total": total, "today": total, "saved": 0, "read": 0, "by_source": by_source, "by_category": {}, "by_sentiment": {}}
        except Exception:
            pass
        # Try HF Dataset pull (if HF_DATASET env set)
        hf_dataset = os.getenv("HF_DATASET", "").strip()
        if hf_dataset:
            try:
                from huggingface_hub import hf_hub_download
                # download daily_stats.json from dataset repo
                p = hf_hub_download(repo_id=hf_dataset, filename=f"{day}/daily_stats.json", repo_type="dataset")
                data = _json.loads(Path(p).read_text(encoding="utf-8"))
                return {
                    "total": data.get("total", 0),
                    "today": data.get("total", 0),
                    "saved": 0,
                    "read": 0,
                    "by_source": data.get("by_source", {}),
                    "by_category": data.get("by_category", {}),
                    "by_sentiment": {},
                }
            except Exception:
                pass
    except Exception:
        pass
    return None


def get_cached_stats():
    # Prefer Gold if available (shows lakehouse), else DB
    gold = _get_gold_stats()
    if gold is not None:
        return gold
    now = time.time()
    if _stats_cache['data'] is not None and (now - _stats_cache['ts']) < _STATS_TTL:
        return _stats_cache['data']
    data = db.get_stats()
    _stats_cache['data'] = data
    _stats_cache['ts'] = now
    return data

MAX_SCRAPE_PAGES = 5
MAX_PAGE_NUMBER = 1000
MAX_KEYWORD_LENGTH = 120
MAX_SEARCH_QUERY_LENGTH = 100

ALLOWED_SORT_OPTIONS = {'score', 'comments', 'newest'}
ALLOWED_SOURCE_FILTERS = {'all', 'Hacker News', 'TechCrunch', 'Reddit', 'The Verge', 'Ars Technica', 'GitHub Trending', 'arXiv'}

KEYWORD_REGEX = re.compile(r"^[\w\s\-\.\+#&',:()]*$")


def parse_bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    """Parses and clamps an int value to a safe range."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def sanitize_keyword(keyword: str) -> str:
    """Sanitizes keyword input to avoid malformed queries."""
    cleaned = (keyword or '').strip()
    if not cleaned:
        return ''

    if len(cleaned) > MAX_KEYWORD_LENGTH:
        cleaned = cleaned[:MAX_KEYWORD_LENGTH]

    if not KEYWORD_REGEX.fullmatch(cleaned):
        logger.warning("Rejected keyword with invalid characters")
        return ''

    return cleaned


def sanitize_search_query(query: str) -> str:
    """Sanitizes full-text search query input."""
    cleaned = (query or '').strip()
    if not cleaned:
        return ''

    if len(cleaned) > MAX_SEARCH_QUERY_LENGTH:
        cleaned = cleaned[:MAX_SEARCH_QUERY_LENGTH]

    if any(ord(char) < 32 for char in cleaned):
        logger.warning("Rejected search query with control characters")
        return ''

    return cleaned


def normalize_sort_by(sort_by: str) -> str:
    value = (sort_by or '').strip().lower()
    return value if value in ALLOWED_SORT_OPTIONS else 'score'


def normalize_source_filter(source: str) -> str:
    value = (source or '').strip()
    return value if value in ALLOWED_SOURCE_FILTERS else 'all'


def parse_positive_int(value: Any) -> Optional[int]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def get_json_payload() -> Optional[dict[str, Any]]:
    """Safely parses a JSON body and returns None for malformed payloads."""
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return cast(dict[str, Any], data)
    return None


EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')


def is_valid_email(email: str) -> bool:
    if not email or len(email) > 254:
        return False
    if '\n' in email or '\r' in email:
        return False
    return bool(EMAIL_REGEX.fullmatch(email))


BLOCKED_HOSTS = {'localhost', '127.0.0.1', '0.0.0.0', '169.254.169.254', '::1'}

IPAddress = Union[ipaddress.IPv4Address, ipaddress.IPv6Address]


def _is_disallowed_ip(address: IPAddress) -> bool:
    return (
        address.is_private or
        address.is_loopback or
        address.is_link_local or
        address.is_multicast or
        address.is_reserved or
        address.is_unspecified
    )


def _resolves_to_disallowed_ip(hostname: str) -> bool:
    try:
        records = socket.getaddrinfo(hostname, None)
    except Exception:
        return True

    for record in records:
        ip_value = record[4][0]
        try:
            parsed_ip = ipaddress.ip_address(ip_value)
        except ValueError:
            continue

        if _is_disallowed_ip(parsed_ip):
            return True

    return False


def is_safe_url(url: str) -> bool:
    parsed = urlparse((url or '').strip())
    if parsed.scheme not in ('http', 'https'):
        return False

    if not parsed.netloc or parsed.username or parsed.password:
        return False

    hostname = (parsed.hostname or '').strip().lower().rstrip('.')
    if not hostname:
        return False

    if hostname in BLOCKED_HOSTS or hostname.endswith('.localhost'):
        return False

    try:
        address = ipaddress.ip_address(hostname)
        if _is_disallowed_ip(address):
            return False
    except ValueError:
        if _resolves_to_disallowed_ip(hostname):
            return False

    if parsed.port and parsed.port not in (80, 443):
        return False

    return True


# ──────────────────────────────────────────────
# Auto-Tagging (Keyword-based category classification)
# ──────────────────────────────────────────────

CATEGORY_KEYWORDS = {
    'AI & ML': ['ai', 'artificial intelligence', 'machine learning', 'deep learning', 'gpt',
                'chatgpt', 'llm', 'neural', 'openai', 'gemini', 'claude', 'copilot',
                'transformer', 'diffusion', 'generative'],
    'Security': ['security', 'hack', 'breach', 'vulnerability', 'malware', 'ransomware',
                 'phishing', 'cyber', 'exploit', 'privacy', 'encryption', 'zero-day'],
    'Hardware': ['chip', 'processor', 'gpu', 'cpu', 'nvidia', 'amd', 'intel', 'apple silicon',
                 'semiconductor', 'quantum', 'hardware', 'laptop', 'phone', 'device'],
    'Software': ['software', 'app', 'update', 'release', 'version', 'framework', 'library',
                 'programming', 'developer', 'code', 'open source', 'github', 'linux', 'windows'],
    'Business': ['startup', 'funding', 'acquisition', 'ipo', 'revenue', 'layoff', 'market',
                 'company', 'ceo', 'billion', 'million', 'valuation', 'investor'],
    'Science': ['science', 'research', 'study', 'discovery', 'space', 'nasa', 'climate',
                'physics', 'biology', 'medicine', 'vaccine', 'health'],
    'Gaming': ['game', 'gaming', 'xbox', 'playstation', 'nintendo', 'steam', 'esports',
               'console', 'vr', 'ar', 'metaverse'],
    'Social Media': ['twitter', 'facebook', 'instagram', 'tiktok', 'youtube', 'reddit',
                     'social media', 'meta', 'bluesky', 'mastodon', 'threads'],
}

CATEGORY_FILTER_LOOKUP = {'all': 'all', 'general': 'general'}
for _category in CATEGORY_KEYWORDS:
    CATEGORY_FILTER_LOOKUP[_category.lower()] = _category


def normalize_category_filter(category: str) -> str:
    value = (category or '').strip().lower()
    return CATEGORY_FILTER_LOOKUP.get(value, 'all')


def classify_article(title: str) -> str:
    """Classifies an article into a category based on keyword matching (word-boundary aware)."""
    title_lower = title.lower()
    # Extract words for boundary-aware matching of short terms like 'ai', 'game', 'chip'
    words = set(re.findall(r'[a-z0-9]+', title_lower))
    title_filtered = f' {title_lower} '
    scores = {}
    for category, keywords in CATEGORY_KEYWORDS.items():
        score = 0
        for kw in keywords:
            if ' ' in kw:
                if kw in title_lower:
                    score += 1
            elif len(kw) <= 3:
                if kw in words:
                    score += 1
            else:
                if kw in title_lower:
                    score += 1
        if score > 0:
            scores[category] = score

    if scores:
        return max(scores, key=scores.get)
    return 'General'


def estimate_read_time(title: str, excerpt: str = '') -> int:
    """Estimates read time from excerpt length when available, else title.
    ponytail: simple word-count proxy; upgrade to real content length when full body stored."""
    text = excerpt.strip() if excerpt and excerpt.strip() else title
    word_count = len(text.split())
    # avg 200 wpm, tech article 400-800 words => 2-4 min plus overhead
    if word_count > 80:
        return 7
    elif word_count > 40:
        return 5
    elif word_count > 20:
        return 4
    return 3


# ──────────────────────────────────────────────
# Sentiment Analysis (cached singleton)
# ──────────────────────────────────────────────

_sia = None

def _get_sia():
    global _sia
    if not _vader_available:
        return None
    if _sia is None:
        _ensure_nltk_once()
        try:
            _sia = SentimentIntensityAnalyzer()
        except Exception:
            return None
    return _sia

def analyze_sentiment(title: str) -> dict:
    """Uses VADER to analyze sentiment of a title."""
    sia = _get_sia()
    if sia is None:
        return {'label': 'neutral', 'score': 0.0}

    try:
        scores = sia.polarity_scores(title)
        compound = scores['compound']

        if compound >= 0.05:
            label = 'positive'
        elif compound <= -0.05:
            label = 'negative'
        else:
            label = 'neutral'

        return {'label': label, 'score': compound}
    except Exception:
        return {'label': 'neutral', 'score': 0.0}


# ──────────────────────────────────────────────
# Trending Topics (TF-IDF-like word frequency)
# ──────────────────────────────────────────────

STOP_WORDS: Optional[set] = None

def _get_stop_words() -> set:
    global STOP_WORDS
    if STOP_WORDS is not None:
        return STOP_WORDS
    _ensure_nltk_once()
    try:
        from nltk.corpus import stopwords
        base = set(stopwords.words('english'))
    except LookupError:
        base = set()
    base.update({
        'new', 'says', 'first', 'get', 'one', 'two', 'could', 'would', 'also',
        'may', 'use', 'using', 'make', 'like', 'much', 'now', 'just',
        'want', 'still', 'year', 'years', 'going', 'big', 'best', 'way',
    })
    STOP_WORDS = base
    return STOP_WORDS


def extract_trending_topics(titles: list[str], limit: int = 10) -> list[dict]:
    """Extracts trending topics from article titles using word frequency."""
    # ponytail: single-pass, keep unigrams and bigrams separate so neither starves the other
    stop_words = _get_stop_words()
    uni_counts: Counter = Counter()
    bi_counts: Counter = Counter()

    for title in titles:
        words = re.findall(r'[a-zA-Z]{3,}', title.lower())
        meaningful = [w for w in words if w not in stop_words and len(w) > 2]
        uni_counts.update(meaningful)
        for i in range(len(meaningful) - 1):
            bigram = f"{meaningful[i]} {meaningful[i + 1]}"
            bi_counts[bigram] += 1

    topics = []
    for word, count in uni_counts.most_common(limit):
        if count >= 2:
            topics.append({'topic': word, 'count': count, 'kind': 'word'})
    # Add top bigrams interleaved, still respecting limit
    for phrase, count in bi_counts.most_common(limit):
        if count >= 2 and len(topics) < limit and phrase not in {t['topic'] for t in topics}:
            topics.append({'topic': phrase, 'count': count, 'kind': 'phrase'})
    # Sort by count desc and trim
    topics.sort(key=lambda x: x['count'], reverse=True)
    for t in topics:
        t.pop('kind', None)
    return topics[:limit]


# ──────────────────────────────────────────────
# Background Processing
# ──────────────────────────────────────────────

def process_articles_metadata(batch_size: int = 100):
    """Background job: assigns sentiment, category, and read time to unprocessed articles."""
    total = 0
    while True:
        unprocessed = db.get_unprocessed_articles(limit=batch_size)
        if not unprocessed:
            break
        processed_at = time.time()
        for article in unprocessed:
            title = article.get('title', '')
            excerpt = article.get('excerpt', '')
            sentiment = analyze_sentiment(title)
            category = classify_article(title)
            read_time = estimate_read_time(title, excerpt)

            db.update_article_metadata(
                article_id=article['id'],
                sentiment=sentiment['label'],
                sentiment_score=sentiment['score'],
                category=category,
                read_time=read_time,
                metadata_processed_at=processed_at
            )
        total += len(unprocessed)
        logger.info(f"Processed metadata for {len(unprocessed)} articles ({total} total this run)")
        if len(unprocessed) < batch_size:
            break
    if total:
        logger.info(f"Finished metadata processing: {total} articles")


def background_scrape():
    """Background job: scrapes all sources and saves to DB."""
    logger.info("[Scheduler] Running background scrape...")
    try:
        agg = get_aggregator()
        agg.scrape_all(hn_pages=1, force=True)
        new_articles = agg.get_articles()
        if new_articles:
            try:
                new_articles = _enrich_batch(new_articles, fetch=False)
            except Exception as e:
                logger.warning(f"Enrich failed: {e}")
            db.add_articles(new_articles)
            db.upsert_images(new_articles)
            logger.info(f"[Scheduler] Added {len(new_articles)} articles")
            # Process metadata for new articles
            process_articles_metadata()
            _stats_cache['data'] = None
    except Exception as e:
        logger.error(f"[Scheduler] Scrape failed: {e}")


# ──────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────

@app.route('/download')
def download_csv() -> ResponseReturnValue:
    """Generates and downloads a CSV file of the articles."""
    sort_by = normalize_sort_by(request.args.get('sort', 'score'))
    keyword = sanitize_keyword(request.args.get('keyword', ''))

    articles = db.get_articles(limit=500, keyword=keyword, sort_by=sort_by)

    def generate():
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=[
            'title', 'score', 'link', 'author', 'time', 'comments', 'source', 'category', 'sentiment'
        ], extrasaction='ignore')
        writer.writeheader()
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)

        for article in articles:
            writer.writerow(article)
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)

    return Response(stream_with_context(generate()),
                    mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment;filename=tech_news.csv'})


@app.route('/saved')
def saved_articles():
    """Shows only bookmarked articles."""
    page = parse_bounded_int(request.args.get('page', 1), default=1, minimum=1, maximum=MAX_PAGE_NUMBER)
    sort_by = normalize_sort_by(request.args.get('sort', 'newest'))
    per_page = 30
    offset = (page - 1) * per_page

    articles = db.get_articles(limit=per_page, offset=offset, saved_only=True, sort_by=sort_by)
    total = db.get_total_count(saved_only=True)
    total_pages = max(1, (total + per_page - 1) // per_page)
    stats = get_cached_stats()

    return render_template('index.html',
                           articles=articles,
                           stats=stats,
                           total_count=total,
                           page=page,
                           total_pages=total_pages,
                           showing_saved=True,
                           sort_by=sort_by)


@app.route('/', methods=['GET', 'POST'])
def index():
    """Main dashboard route with scraping, filtering, and pagination."""
    keyword = sanitize_keyword(request.form.get('keyword', request.args.get('keyword', '')))
    pages = parse_bounded_int(
        request.form.get('pages', request.args.get('pages', 1)),
        default=1,
        minimum=1,
        maximum=MAX_SCRAPE_PAGES
    )
    sort_by = normalize_sort_by(request.form.get('sort', request.args.get('sort', 'score')))
    source_filter = normalize_source_filter(request.form.get('source', request.args.get('source', 'all')))
    category_filter = normalize_category_filter(request.args.get('category', 'all'))
    page = parse_bounded_int(request.args.get('page', 1), default=1, minimum=1, maximum=MAX_PAGE_NUMBER)
    per_page = 30
    offset = (page - 1) * per_page

    try:
        if request.method == 'POST':
            force_refresh = request.form.get('refresh', 'false') == 'true'
            should_scrape = force_refresh or (db.get_article_count() == 0)

            if should_scrape:
                logger.info("Scraping fresh data and saving to DB...")
                agg = get_aggregator()
                agg.scrape_all(hn_pages=pages, force=force_refresh)
                new_articles = agg.get_articles()
                try:
                    new_articles = _enrich_batch(new_articles, fetch=False)
                except Exception as e:
                    logger.warning(f"Enrich failed: {e}")
                db.add_articles(new_articles)
                db.upsert_images(new_articles)
                # Process metadata for new articles
                process_articles_metadata()
                _stats_cache['data'] = None
            else:
                logger.info("Querying existing data...")

    except Exception as e:
        logger.error(f"Error during scrape/filter: {e}")

    # Fetch articles with pagination
    articles = db.get_articles(
        limit=per_page, offset=offset,
        source_filter=source_filter, keyword=keyword,
        category=category_filter,
        sort_by=sort_by
    )

    total = db.get_total_count(source_filter=source_filter, keyword=keyword, category=category_filter)
    total_pages = max(1, (total + per_page - 1) // per_page)

    # Get stats
    stats = get_cached_stats()

    # Source health
    health = get_aggregator().get_health()

    return render_template('index.html',
                           articles=articles,
                           stats=stats,
                           total_count=total,
                           page=page,
                           total_pages=total_pages,
                           showing_saved=False,
                           source_health=health,
                           keyword=keyword,
                           sort_by=sort_by,
                           source_filter=source_filter,
                           category_filter=category_filter)


# ──────────────────────────────────────────────
# API Routes
# ──────────────────────────────────────────────

# Rate limit decorator helper
def rate_limit(limit_str: str):
    """Apply rate limit if limiter is available."""
    def decorator(f):
        if limiter:
            return limiter.limit(limit_str)(f)
        return f
    return decorator


@app.route('/bookmark', methods=['POST'])
@rate_limit("30 per minute")
def bookmark() -> ResponseReturnValue:
    """Toggles article bookmark status."""
    data = get_json_payload()
    if data is None:
        return jsonify({'error': 'Invalid JSON payload'}), 400

    article_id = parse_positive_int(data.get('article_id'))
    if article_id is None:
        return jsonify({'error': 'Valid article_id is required'}), 400

    new_status = db.toggle_bookmark(article_id)
    if new_status is None:
        return jsonify({'error': 'Article not found'}), 404
    _stats_cache['data'] = None
    return jsonify({'status': 'saved' if new_status else 'removed'})


@app.route('/toggle_read', methods=['POST'])
@rate_limit("30 per minute")
def toggle_read() -> ResponseReturnValue:
    """Toggles article read status."""
    data = get_json_payload()
    if data is None:
        return jsonify({'error': 'Invalid JSON payload'}), 400

    article_id = parse_positive_int(data.get('article_id'))
    if article_id is None:
        return jsonify({'error': 'Valid article_id is required'}), 400

    new_status = db.toggle_read(article_id)
    if new_status is None:
        return jsonify({'error': 'Article not found'}), 404
    _stats_cache['data'] = None
    return jsonify({'status': 'read' if new_status else 'unread'})


@app.route('/subscribe', methods=['POST'])
@rate_limit("10 per hour")
def subscribe() -> ResponseReturnValue:
    """Handle email subscription."""
    data = get_json_payload()
    if data is None:
        return jsonify({'error': 'Invalid JSON payload'}), 400

    email = data.get('email', '').strip()
    if not email or not is_valid_email(email):
        return jsonify({'error': 'Please enter a valid email address'}), 400

    logger.info(f"New subscriber: {email}")
    return jsonify({'message': 'Subscribed successfully!'})


@app.route('/api/stats')
def api_stats() -> ResponseReturnValue:
    """API endpoint for dashboard statistics."""
    stats = get_cached_stats()
    return jsonify(stats)


@app.route('/api/search')
def api_search() -> ResponseReturnValue:
    """Full-text search endpoint using FTS5."""
    query = sanitize_search_query(request.args.get('q', ''))
    if not query:
        return jsonify({'error': 'Search query required'}), 400

    results = db.search_articles(query, limit=50)
    return jsonify({'results': results, 'count': len(results)})





@app.route('/api/health')
def api_health() -> ResponseReturnValue:
    """Returns scraper health status for all sources."""
    return jsonify({'sources': get_aggregator().get_health()})


@app.route('/api/personalized')
def api_personalized() -> ResponseReturnValue:
    """Returns personalized feed based on user bookmarks."""
    articles = db.get_personalized_feed(limit=30)
    return jsonify({'articles': articles})


@app.route('/api/summarize', methods=['POST'])
@rate_limit("20 per minute")
def summarize() -> ResponseReturnValue:
    """Summarizes a given URL using trafilatura (fast, no ML deps)."""
    data = get_json_payload()
    if data is None:
        return jsonify({'error': 'Invalid JSON payload'}), 400

    url = data.get('url', '').strip()

    if not url:
        return jsonify({'error': 'No URL provided'}), 400

    if len(url) > 2048:
        return jsonify({'error': 'URL is too long'}), 400

    if not is_safe_url(url):
        return jsonify({'error': 'URL not allowed'}), 400

    try:
        import trafilatura
        import requests as _req
        # Fetch via requests so SSRF redirect chain can be validated
        try:
            resp = _req.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'}, allow_redirects=True)
            if resp.status_code != 200:
                return jsonify({'error': 'Failed to fetch URL'}), 500
            # Validate final URL after redirects
            if not is_safe_url(resp.url):
                return jsonify({'error': 'URL not allowed after redirect'}), 400
            downloaded = resp.text
        except Exception:
            # Fallback to trafilatura's fetcher
            downloaded = trafilatura.fetch_url(url, timeout=10)
        if not downloaded:
            return jsonify({'error': 'Failed to fetch URL'}), 500

        # Extract main content — use bare_extraction for metadata
        title = ""
        image = ""
        full_text = ""
        try:
            bare = trafilatura.bare_extraction(downloaded, with_metadata=True, favor_recall=False)
            if bare and getattr(bare, "text", None):
                full_text = bare.text or ""
                title = getattr(bare, "title", "") or ""
                image = getattr(bare, "image", "") or ""
        except Exception:
            pass

        if not full_text:
            # fallback to json extract
            result = trafilatura.extract(
                downloaded,
                include_comments=False,
                include_tables=False,
                include_images=False,
                output_format='json',
                with_metadata=True
            )
            if result:
                import json
                data = json.loads(result)
                title = title or data.get('title', '')
                full_text = data.get('raw_text', '') or data.get('text', '') or data.get('excerpt', '')
                image = image or data.get('image', '')
            else:
                text = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
                full_text = text or ""

        if not full_text:
            return jsonify({'error': 'Could not extract content'}), 500

        # Enrich to dek + bullets (free, offline)
        from pipeline.enrich import _make_dek, _extractive_bullets
        dek = _make_dek(full_text, title)
        bullets = _extractive_bullets(full_text, 3)
        # ensure not empty
        if not bullets:
            # fallback single
            bullets = [full_text[:220].rsplit(" ",1)[0] + "…"] if len(full_text) > 220 else [full_text[:220]]
        # read_time
        words = len(full_text.split())
        read_time = max(1, round(words / 225))
        # legacy summary for compat = dek + bullets joined
        summary = dek + (" " + " ".join(bullets) if bullets else "")

        return jsonify({
            'title': title,
            'dek': dek,
            'bullets': bullets,
            'summary': summary[:800],
            'top_image': image,
            'read_time': read_time,
            'word_count': words,
        })
    except Exception as e:
        logger.warning(f"Failed to summarize {url}: {e}")
        return jsonify({'error': f"Failed to summarize: {str(e)}"}), 500


@app.route('/export/json')
def export_json() -> ResponseReturnValue:
    """Exports bookmarked articles as JSON download."""
    json_data = db.export_bookmarks_json()
    return Response(json_data, mimetype='application/json',
                    headers={'Content-Disposition': 'attachment;filename=bookmarks.json'})


@app.route('/export/markdown')
def export_markdown() -> ResponseReturnValue:
    """Exports bookmarked articles as Markdown download."""
    md_data = db.export_bookmarks_markdown()
    return Response(md_data, mimetype='text/markdown',
                    headers={'Content-Disposition': 'attachment;filename=bookmarks.md'})


@app.route('/api/webhook/test', methods=['POST'])
def test_webhook() -> ResponseReturnValue:
    """Tests a webhook by sending a sample payload.
    Configure WEBHOOK_URL environment variable to use."""
    import requests as req

    webhook_url = os.getenv('WEBHOOK_URL', '').strip()
    if not webhook_url:
        return jsonify({'error': 'No WEBHOOK_URL configured. Set it as an environment variable.'}), 400

    if not is_safe_url(webhook_url):
        return jsonify({'error': 'Configured WEBHOOK_URL is invalid or not allowed.'}), 400

    stats = db.get_stats()
    payload = {
        'text': f"📰 *Tech News Digest*\n"
                f"- Total articles: {stats['total']}\n"
                f"- New today: {stats['today']}\n"
                f"- Saved: {stats['saved']}",
        'username': 'Sniffer'
    }

    try:
        resp = req.post(webhook_url, json=payload, timeout=10)
        if resp.status_code < 300:
            return jsonify({'status': 'Webhook sent successfully'})
        return jsonify({'error': f'Webhook returned {resp.status_code}'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/email/digest', methods=['POST'])
def send_email_digest() -> ResponseReturnValue:
    """Sends an email digest of top articles.
    Configure SMTP_* environment variables to use."""
    smtp_host = os.getenv('SMTP_HOST', '')
    smtp_port = int(os.getenv('SMTP_PORT', '587'))
    smtp_user = os.getenv('SMTP_USER', '')
    smtp_pass = os.getenv('SMTP_PASS', '')

    if not all([smtp_host, smtp_user, smtp_pass]):
        return jsonify({
            'error': 'Email not configured. Set SMTP_HOST, SMTP_USER, SMTP_PASS environment variables.',
            'hint': 'Example: set SMTP_HOST=smtp.gmail.com'
        }), 400

    data = get_json_payload()
    if data is None:
        return jsonify({'error': 'Invalid JSON payload'}), 400

    recipient = data.get('email', '').strip()
    if not recipient or not is_valid_email(recipient):
        return jsonify({'error': 'Valid recipient email required'}), 400

    # Build digest content (escape to prevent HTML injection)
    import html as _html
    articles = db.get_articles(limit=10)
    digest_lines = ["<h2>📰 Your Tech News Digest</h2><ul>"]
    for a in articles:
        link = _html.escape(a.get('link') or '', quote=True)
        title = _html.escape(a.get('title') or '')
        source = _html.escape(a.get('source') or '')
        digest_lines.append(f"<li><a href='{link}'>{title}</a> [{source}]</li>")
    digest_lines.append("</ul>")

    body = '\n'.join(digest_lines)
    msg = MIMEText(body, 'html')
    msg['Subject'] = 'Your Daily Tech News Digest'
    msg['From'] = smtp_user
    msg['To'] = recipient

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        return jsonify({'status': 'Digest sent successfully'})
    except Exception as e:
        logger.error(f"Email send failed: {e}")
        return jsonify({'error': f'Failed to send: {str(e)}'}), 500


# ──────────────────────────────────────────────
# PWA Support
# ──────────────────────────────────────────────

@app.route('/manifest.json')
def manifest():
    return jsonify({
        "name": "Sniffer",
        "short_name": "Sniffer",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#1a1a2e",
        "theme_color": "#6c5ce7",
        "description": "Aggregate tech news from multiple sources",
        "icons": [
            {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png"}
        ]
    })


@app.route('/service-worker.js')
def service_worker():
    return app.send_static_file('service-worker.js')


# ──────────────────────────────────────────────
# Start Background Scheduler
# ──────────────────────────────────────────────

scheduler = None


def stop_scheduler() -> None:
    global scheduler
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Background scheduler stopped")


def start_scheduler() -> None:
    """Starts scheduler once and avoids duplicate startup in debug reloader."""
    global scheduler

    if not _scheduler_available:
        logger.warning("APScheduler not available. Background scraping disabled.")
        return

    debug_mode = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    if debug_mode and os.getenv('WERKZEUG_RUN_MAIN') != 'true':
        return

    if scheduler and scheduler.running:
        return

    scheduler = BackgroundScheduler()
    scheduler.add_job(background_scrape, 'interval', minutes=15, id='scrape_job',
                      replace_existing=True, max_instances=1)
    scheduler.start()
    atexit.register(stop_scheduler)
    logger.info("Background scheduler started (scraping every 15 minutes)")


def _init_background_tasks():
    """Lazy init — call explicitly, not at import."""
    # ponytail: avoid import side-effects, call from create_app or __main__
    is_render = os.getenv('RENDER') is not None
    try:
        process_articles_metadata()
        if not is_render:
            start_scheduler()
        else:
            logger.info("Render detected — background scheduler disabled. Use manual Refresh.")
    except Exception as e:
        logger.error(f"Failed to initialize scheduler or process metadata: {e}")

# Only auto-init when not under test and not imported as library
if os.getenv('SNIFFER_NO_AUTO_INIT') != '1':
    # Defer slightly but still allow gunicorn workers to init without blocking import
    # Use app.before_request would be better; for now init once after first request
    @app.before_request
    def _lazy_init_once():
        # run once
        if not getattr(app, '_sniffer_inited', False):
            app._sniffer_inited = True
            try:
                _init_background_tasks()
            except Exception:
                pass


# ──────────────────────────────────────────────
# Error Handlers (Security)
# ──────────────────────────────────────────────

if _limiter_available:
    from flask_limiter.errors import RateLimitExceeded

    @app.errorhandler(RateLimitExceeded)
    def handle_rate_limit(e):
        return jsonify({
            'error': 'rate_limit_exceeded',
            'message': 'Too many requests. Please slow down.',
            'retry_after': e.retry_after
        }), 429


@app.errorhandler(400)
def handle_bad_request(e):
    return jsonify({'error': 'bad_request', 'message': 'Invalid request'}), 400


@app.errorhandler(404)
def handle_not_found(e):
    return jsonify({'error': 'not_found', 'message': 'Resource not found'}), 404


@app.errorhandler(413)
def handle_payload_too_large(e):
    return jsonify({'error': 'payload_too_large', 'message': 'Request body too large'}), 413


@app.errorhandler(500)
def handle_server_error(e):
    logger.error(f"Internal server error: {e}\n{traceback.format_exc()}")
    return jsonify({'error': 'internal_error', 'message': 'Something went wrong'}), 500


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    port = int(os.environ.get('PORT', 7860))
    debug = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    logger.info(f"Starting local dev server on port {port} (debug={debug})...")
    # ponytail: gunicorn is for production (render.yaml / Dockerfile CMD), not os.system from app
    app.run(host='0.0.0.0', port=port, debug=debug)
