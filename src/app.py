"""
Flask Application — Sniffer
Routes, background scheduler, sentiment analysis, trending topics,
auto-tagging, charts, export, personalized feed, and webhook/email stubs.
"""
import csv
import io
import ipaddress
import json
import logging
import os
import re
import smtplib
import socket
import time
import traceback
from email.mime.text import MIMEText
from typing import Any, cast
from urllib.parse import urlparse

from flask import (
    Flask,
    Response,
    jsonify,
    render_template,
    request,
    stream_with_context,
)
from flask.typing import ResponseReturnValue

from categories import classify_article, normalize_category_filter
from database import Database
from pipeline.enrich import enrich_batch as _enrich_batch
from web_scraper import NewsAggregator

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

logger = logging.getLogger(__name__)

app = Flask(__name__)


def _humanize_time(value: str) -> str:
    """Humanize ISO/RFC time for display (no raw ISO in UI)."""
    if not value:
        return "Today"
    v = value.strip()
    if v.lower() in ("recent", "recently", "today", "unknown"):
        return v
    try:
        from datetime import datetime, timezone
        from email.utils import parsedate_to_datetime
        s = v[:-1] + "+00:00" if v.endswith("Z") else v
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            dt = parsedate_to_datetime(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        secs = int((datetime.now(timezone.utc) - dt).total_seconds())
        if secs < 0:
            return "Today"
        if secs < 60:
            return "now"
        if secs < 3600:
            return f"{secs // 60}m ago"
        if secs < 86400:
            return f"{secs // 3600}h ago"
        if secs < 604800:
            return f"{secs // 86400}d ago"
        return dt.strftime("%b %d")
    except Exception:
        m = re.search(r"(\d+)\s*hour", v, re.IGNORECASE)
        if "hour" in v.lower():
            return f"{m.group(1) if m else 1}h ago"
        return value[:16]


@app.template_filter("humanize_time")
def humanize_time_filter(value):
    return _humanize_time(str(value) if value is not None else "")


@app.context_processor
def inject_humanize_time():
    return {'humanize_time': _humanize_time}


# Security Hardening
# Trusted hosts (Flask 3.1+) — prevent Host header attacks
trusted_hosts_env = os.getenv('TRUSTED_HOSTS', '')
if trusted_hosts_env:
    app.config['TRUSTED_HOSTS'] = [
        h.strip() for h in trusted_hosts_env.split(',') if h.strip()
    ]
elif os.getenv('RENDER'):
    # Behind a proxy the original Host is the public hostname, which the
    # platform does not tell us. An empty list would allow ANY host, so leave
    # the key unset and let the deploy set TRUSTED_HOSTS (render.yaml does).
    logger.warning(
        "TRUSTED_HOSTS not set on Render — host header validation is disabled. "
        "Set the TRUSTED_HOSTS env var to your public hostname.")
else:
    app.config['TRUSTED_HOSTS'] = ['localhost', '127.0.0.1']

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
        'script-src': ["'self'"],
        # index.html has no inline <script>; every handler lives in app.js.
        'script-src-attr': ["'none'"],
        # style-src still needs unsafe-inline for the style="" the template sets
        # and the jsdelivr stylesheet.
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

# Helpers
# Singleton aggregator so CACHE_TTL and health tracking actually work
_aggregator_instance: NewsAggregator | None = None

def get_aggregator() -> NewsAggregator:
    """Return shared NewsAggregator (per-process singleton)."""
    global _aggregator_instance
    if _aggregator_instance is None:
        _aggregator_instance = NewsAggregator()
    return _aggregator_instance

# Stats cache (60s TTL) — avoids 7 COUNT(*) per page load
_stats_cache: dict = {'data': None, 'ts': 0.0}
_STATS_TTL = 60

# Summary cache (1h TTL) — avoids refetch + re-extract on repeat Quick reads
_summary_cache: dict = {}
_SUMMARY_TTL = 3600

def _gold_shape(data: dict) -> dict:
    """Normalize Gold daily_stats.json (writes total_articles) to DB stats shape."""
    total = data.get("total_articles", data.get("total", 0))
    return {"total": total, "today": total, "saved": 0, "read": 0,
            "by_source": data.get("by_source", {}), "by_category": data.get("by_category", {}),
            "by_sentiment": {}}


def _get_gold_stats():
    """Serve stats from Gold layer (Parquet via DuckDB) — falls back to DB."""
    try:
        from datetime import datetime, timezone
        from pathlib import Path
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for d in (day, day.replace("-", "/")):
            p = Path(f"data/gold/{d}/daily_stats.json")
            if p.exists():
                return _gold_shape(json.loads(p.read_text(encoding="utf-8")))
        hf_dataset = os.getenv("HF_DATASET", "").strip()
        if hf_dataset:
            try:
                from huggingface_hub import hf_hub_download
                p = hf_hub_download(repo_id=hf_dataset, filename=f"{day}/daily_stats.json", repo_type="dataset")
                return _gold_shape(json.loads(Path(p).read_text(encoding="utf-8")))
            except Exception as e:
                logger.debug("HF_DATASET lookup failed for %s: %s", day, e)
        try:
            import duckdb
            marts = sorted(Path("data/gold").glob("*/source_metrics.parquet"))
            if marts:
                # Read ONE mart. Globbing data/gold/** spans by_category,
                # source_metrics and top_ranked_articles, whose schemas are
                # mutually incompatible, so DuckDB bound to the
                # alphabetically-first file and raised BinderException —
                # swallowed below, leaving Gold stats permanently unreachable.
                q = duckdb.query(
                    "SELECT source, sum(total_articles) c "
                    f"FROM read_parquet({[str(m) for m in marts]!r}, union_by_name=true) "
                    "GROUP BY source ORDER BY c DESC"
                ).fetchall()
                by_source = {r[0]: int(r[1]) for r in q if r[0]}
                if by_source:
                    total = sum(by_source.values())
                    return {"total": total, "today": total, "saved": 0, "read": 0,
                            "by_source": by_source, "by_category": {}, "by_sentiment": {}}
        except Exception as e:
            logger.debug(f"Gold parquet stats unavailable: {e}")
    except Exception as e:
        logger.debug(f"Gold stats unavailable: {e}")
    return None


def get_cached_stats():
    # The TTL must wrap the Gold lookup too. It used to run above this check,
    # so every page load did a network-bound hf_hub_download, a full rglob and
    # a parquet scan with no caching and no negative caching for a 404.
    now = time.time()
    if _stats_cache['data'] is not None and (now - _stats_cache['ts']) < _STATS_TTL:
        return _stats_cache['data']
    data = _get_gold_stats()
    if data is None:
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


def sanitize_keyword(keyword: str) -> str | None:
    """Sanitizes keyword input. Returns None when the input is rejected.

    The distinction matters: returning '' on rejection made the caller's
    `if keyword:` false, which dropped the WHERE clause and served the whole
    unfiltered feed as "search results" for any query containing a character
    outside the allowlist (%, ", emoji, CJK comma, ...).
    """
    cleaned = (keyword or '').strip()
    if not cleaned:
        return ''

    if len(cleaned) > MAX_KEYWORD_LENGTH:
        # Re-strip: truncating at N can leave a trailing space, which makes
        # `LIKE '%...a %'` unmatchable.
        cleaned = cleaned[:MAX_KEYWORD_LENGTH].strip()

    if not KEYWORD_REGEX.fullmatch(cleaned):
        logger.warning("Rejected keyword with invalid characters")
        return None

    return cleaned


def sanitize_search_query(query: str) -> str:
    """Sanitizes full-text search query input."""
    cleaned = (query or '').strip()
    if not cleaned:
        return ''

    if len(cleaned) > MAX_SEARCH_QUERY_LENGTH:
        cleaned = cleaned[:MAX_SEARCH_QUERY_LENGTH].strip()

    # isprintable() also excludes DEL and the C1 range, not just < 0x20;
    # U+0085 is whitespace to the FTS5 tokenizer.
    if not all(char.isprintable() or char.isspace() for char in cleaned):
        logger.warning("Rejected search query with control characters")
        return ''

    return cleaned


def normalize_sort_by(sort_by: str) -> str:
    value = (sort_by or '').strip().lower()
    return value if value in ALLOWED_SORT_OPTIONS else 'score'


def normalize_source_filter(source: str) -> str:
    value = (source or '').strip()
    return value if value in ALLOWED_SOURCE_FILTERS else 'all'


def parse_positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        # int(True) == 1, so {"article_id": true} toggled article 1.
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def payload_str(data: dict[str, Any], key: str) -> str:
    """Reads a string field, tolerating null/non-string JSON values.

    `data.get(key, '').strip()` raised AttributeError on {"url": 123} or
    {"url": null}, turning a client mistake into a 500.
    """
    value = data.get(key)
    return value.strip() if isinstance(value, str) else ''


def get_json_payload() -> dict[str, Any] | None:
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

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


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

    # urlparse().port is a property that RAISES on an out-of-range or
    # non-numeric port. That ValueError escaped to a 500 from /api/summarize,
    # and it was then swallowed by the caller's `except Exception`, which
    # re-fetched the URL through trafilatura with no SSRF check at all.
    # Port 0 is also falsy, so the old `if parsed.port` skipped the check.
    try:
        port = parsed.port
    except ValueError:
        return False
    if port is not None and port not in (80, 443):
        return False

    return True


# Auto-Tagging (single classifier lives in categories.py)


def _ensure_categories(articles: list[dict]) -> list[dict]:
    """Fills missing category via classify_article so topic filters match."""
    for a in articles:
        try:
            if not (a.get('category') or '').strip() or (a.get('category') or '').strip().lower() == 'general':
                a['category'] = classify_article(a.get('title', '') or '')
        except Exception:
            a.setdefault('category', 'General')
    return articles


# Routes

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
    if keyword is None:
        return jsonify({'error': 'invalid_keyword',
                        'message': 'Search contains unsupported characters.'}), 400
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
                    new_articles = _ensure_categories(new_articles)
                except Exception as e:
                    logger.warning(f"Enrich failed: {e}", exc_info=True)
                inserted, _skipped = db.add_articles(new_articles)
                db.upsert_images(new_articles)
                logger.info(f"Refresh saved {inserted} new articles.")
                try:
                    db.prune_old_articles(max_age_days=int(os.getenv('RETENTION_DAYS', '2')))
                except Exception as e:
                    logger.warning(f"Prune failed: {e}")
                _stats_cache['data'] = None
            else:
                logger.info("Querying existing data...")

    except Exception:
        logger.exception("Error during scrape/filter")

    # Inside the same try: a DB blip here used to escape as raw JSON instead
    # of the dashboard.
    try:
        articles = db.get_articles(
            limit=per_page, offset=offset,
            source_filter=source_filter, keyword=keyword,
            category=category_filter,
            sort_by=sort_by
        )
        total = db.get_total_count(source_filter=source_filter, keyword=keyword, category=category_filter)
        stats = get_cached_stats()
    except Exception:
        logger.exception("Failed to load dashboard")
        articles, total, stats = [], 0, None

    total_pages = max(1, (total + per_page - 1) // per_page)

    return render_template('index.html',
                           articles=articles,
                           stats=stats,
                           total_count=total,
                           page=page,
                           total_pages=total_pages,
                           showing_saved=False,
                           keyword=keyword,
                           sort_by=sort_by,
                           source_filter=source_filter,
                           category_filter=category_filter)


# SSE Scrape Progress Endpoint

@app.route('/api/scrape', methods=['POST'])
def api_scrape():
    """Streams real-time scrape progress via Server-Sent Events (SSE).
    Each source is scraped individually, and its completion is reported
    as a progress event so the frontend can update a real progress bar.
    """
    def generate():
        import json as _json
        try:
            agg = get_aggregator()
            scrapers = list(agg.scrapers)
        except Exception as e:
            logger.exception("Scrape init failed")
            yield f"data: {_json.dumps({'stage': f'Error: {e}', 'progress': 100, 'error': True})}\n\n"
            return
        total_steps = len(scrapers) + 3
        completed = 0

        # Accumulate locally. Assigning to the process-wide singleton meant two
        # concurrent POSTs interleaved into one list, and a disconnect left
        # agg.articles holding a half-finished scrape that index() then wrote
        # to the DB.
        collected = []
        for scraper in scrapers:
            name = getattr(scraper, 'name', scraper.__class__.__name__)
            yield f"data: {_json.dumps({'stage': f'Scanning {name}...', 'progress': int(completed / total_steps * 100)})}\n\n"
            try:
                result = scraper.scrape(1)
                if result:
                    from utils.credibility import is_credible, score_article
                    for a in result:
                        if is_credible(a.get('title', ''), a.get('link', '')):
                            _, cred = score_article(a.get('title', ''), a.get('link', ''))
                            a['credibility'] = cred
                            collected.append(a)
                elif getattr(scraper, 'last_status', '') == 'error':
                    detail = getattr(scraper, 'last_error', '') or 'no reason given'
                    yield f"data: {_json.dumps({'stage': f'{name}: no articles ({detail})'})}\n\n"
            except Exception as e:
                logger.error(f"Scraper {name} failed: {e}")
            completed += 1

        seen = set()
        deduped = []
        for a in collected:
            link = a.get('link')
            if link and link not in seen:
                seen.add(link)
                deduped.append(a)

        yield f"data: {_json.dumps({'stage': 'Fetching thumbnails...', 'progress': int(completed / total_steps * 100)})}\n\n"
        if os.getenv('RENDER'):
            logger.info("Skipping image enrichment on Render free tier.")
        else:
            try:
                import asyncio
                agg.articles = deduped
                asyncio.run(agg._enrich_images_async())
                deduped = agg.get_articles()
            except Exception as e:
                logger.warning(f"Image enrichment failed: {e}", exc_info=True)
        completed += 1

        yield f"data: {_json.dumps({'stage': 'Enriching & saving...', 'progress': int(completed / total_steps * 100)})}\n\n"
        new_articles = deduped
        try:
            new_articles = _enrich_batch(new_articles, fetch=False)
            new_articles = _ensure_categories(new_articles)
        except Exception as e:
            logger.warning(f"Enrich failed: {e}", exc_info=True)
        try:
            inserted, skipped = db.add_articles(new_articles)
            db.upsert_images(new_articles)
        except Exception as e:
            logger.exception("Scrape DB save failed")
            yield f"data: {_json.dumps({'stage': f'Error saving: {e}', 'progress': 100, 'error': True})}\n\n"
            return
        # A batch of articles with zero inserts means the write failed, not
        # that every one of them was already in the table.
        if new_articles and not inserted:
            logger.error(f"Scrape found {len(new_articles)} articles but inserted 0")
            yield f"data: {_json.dumps({'stage': 'Error saving: 0 rows inserted', 'progress': 100, 'error': True})}\n\n"
            return
        try:
            retention = int(os.getenv('RETENTION_DAYS', '2'))
        except ValueError:
            retention = 2
        try:
            db.prune_old_articles(max_age_days=retention)
        except Exception as e:
            logger.warning(f"Prune failed: {e}")
        completed += 1

        yield f"data: {_json.dumps({'stage': 'Finishing...', 'progress': int(completed / total_steps * 100)})}\n\n"
        _stats_cache['data'] = None
        # Publish only after the data is safely in the DB, so a concurrent
        # index() can never persist a partial list.
        agg.articles = new_articles
        agg._last_scrape_time = time.time()
        completed += 1

        try:
            total_count = db.get_total_count()
        except Exception as e:
            logger.exception("Scrape total-count failed")
            yield f"data: {_json.dumps({'stage': f'Error finishing: {e}', 'progress': 100, 'error': True})}\n\n"
            return
        yield f"data: {_json.dumps({'stage': 'Done', 'progress': 100, 'total': total_count, 'inserted': inserted, 'skipped': skipped})}\n\n"

    return Response(stream_with_context(generate()),
                    mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


# API Routes

# Rate limit decorator helper
def rate_limit(limit_str: str):
    """Apply a per-route rate limit that ADDS to the global defaults.

    flask-limiter's LimitDecorator defaults to override_defaults=True, which
    REPLACES the 200/hour global rather than adding to it. That silently left
    /bookmark and /toggle_read at 30/min with no hourly ceiling (1800/hour) and
    /api/summarize at 1200 outbound fetches per hour.
    """
    def decorator(f):
        if limiter:
            return limiter.limit(limit_str, override_defaults=False)(f)
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

    email = payload_str(data, 'email')
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

    url = payload_str(data, 'url')

    if not url:
        return jsonify({'error': 'No URL provided'}), 400

    if len(url) > 2048:
        return jsonify({'error': 'URL is too long'}), 400

    if not is_safe_url(url):
        return jsonify({'error': 'URL not allowed'}), 400

    now = time.time()
    cached = _summary_cache.get(url)
    if cached and (now - cached['ts']) < _SUMMARY_TTL:
        out = dict(cached['data'])
        out['cached'] = True
        return jsonify(out)

    try:
        import requests as _req
        import trafilatura
        # Fetch via requests so the SSRF redirect chain can be validated. The
        # fallback must be reachable ONLY from a transport failure: a bare
        # `except Exception` also caught the is_safe_url ValueError and the
        # 400 return path, re-fetching the same URL through trafilatura with
        # no validation at all.
        try:
            resp = _req.get(url, timeout=(4, 6), headers={'User-Agent': 'Mozilla/5.0'},
                            allow_redirects=True, stream=True)
        except _req.RequestException as e:
            logger.warning(f"Summarize fetch failed, trying trafilatura: {e}")
            downloaded = trafilatura.fetch_url(url, timeout=6) or ''
        else:
            with resp:
                if resp.status_code != 200:
                    return jsonify({'error': 'Failed to fetch URL'}), 500
                # Validate the FINAL url after redirects, before reading a byte.
                if not is_safe_url(resp.url):
                    return jsonify({'error': 'URL not allowed after redirect'}), 400
                ctype = resp.headers.get('content-type', '')
                if ctype and 'html' not in ctype.lower() and 'text' not in ctype.lower():
                    return jsonify({'error': 'URL did not return a text page'}), 415
                # Stream: resp.text decodes the whole body before slicing, so a
                # multi-GB response OOMed the worker. MAX_CONTENT_LENGTH only
                # bounds inbound requests.
                buf = bytearray()
                for chunk in resp.iter_content(65536):
                    buf.extend(chunk)
                    if len(buf) >= 500000:
                        break
                resp.close()
                downloaded = buf[:500000].decode(resp.encoding or 'utf-8', 'replace')
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
        except Exception as e:
            logger.debug(f"bare_extraction failed: {e}", exc_info=True)

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

        from pipeline.enrich import _extractive_bullets, _make_dek
        short_text = full_text[:20000]
        dek = _make_dek(short_text, title)
        bullets = _extractive_bullets(short_text, 3, exclude=dek)
        if not bullets:
            snippet = short_text[:220]
            bullets = [snippet.rsplit(" ", 1)[0] + "…" if len(snippet) > 220 else snippet]
        words = len(full_text.split())
        read_time = max(1, round(words / 225))
        summary = dek + (" " + " ".join(bullets) if bullets else "")

        payload = {
            'title': title,
            'dek': dek,
            'bullets': bullets,
            'summary': summary[:800],
            'top_image': image,
            'read_time': read_time,
            'word_count': words,
            'cached': False,
        }
        # clear() discards all 500 entries at once, so cycling 501 URLs wipes
        # the cache every pass while still costing 500 live fetches.
        if len(_summary_cache) > 500:
            _summary_cache.pop(next(iter(_summary_cache)))
        _summary_cache[url] = {'ts': time.time(), 'data': payload}
        return jsonify(payload)
    except Exception:
        # Do not return str(e): it carries DSNs, hostnames and ports from
        # requests/psycopg2/trafilatura to an unauthenticated caller.
        logger.exception(f"Failed to summarize {url}")
        return jsonify({'error': 'Failed to summarize the URL.'}), 500


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
    except Exception:
        logger.exception("Webhook test failed")
        return jsonify({'error': 'Webhook request failed.'}), 500


@app.route('/api/email/digest', methods=['POST'])
@rate_limit("5 per hour")
def send_email_digest() -> ResponseReturnValue:
    """Sends an email digest of top articles.
    Configure SMTP_* environment variables to use."""
    smtp_host = os.getenv('SMTP_HOST', '')
    smtp_port = int(os.getenv('SMTP_PORT', '587'))
    smtp_user = os.getenv('SMTP_USER', '')
    smtp_pass = os.getenv('SMTP_PASS', '')

    # Unauthenticated, this endpoint is an open relay: 50 real HTML emails per
    # minute to any internet address, from the app's own domain. Opt in.
    # Checked before the SMTP config so the gate is the first thing a caller
    # hits and a 403 is not a hint about the server's environment.
    if os.getenv('ALLOW_EMAIL_DIGEST') != '1':
        return jsonify({'error': 'Email digest is disabled. Set ALLOW_EMAIL_DIGEST=1 to enable.'}), 403

    if not all([smtp_host, smtp_user, smtp_pass]):
        return jsonify({
            'error': 'Email not configured. Set SMTP_HOST, SMTP_USER, SMTP_PASS environment variables.',
            'hint': 'Example: set SMTP_HOST=smtp.gmail.com'
        }), 400

    data = get_json_payload()
    if data is None:
        return jsonify({'error': 'Invalid JSON payload'}), 400

    recipient = payload_str(data, 'email')
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
        return jsonify({'error': 'Failed to send the digest.'}), 500


# PWA Support

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


# Error Handlers (Security)

if _limiter_available:
    from flask_limiter.errors import RateLimitExceeded

    @app.errorhandler(RateLimitExceeded)
    def handle_rate_limit(e):
        # flask-limiter 3.8 never populates e.retry_after (limits 5.6 exposes no
        # reset_at either), so every 429 shipped {"retry_after": null} with no
        # Retry-After header. get_expiry() is the window length, which for a
        # fixed window is a correct upper bound on when the client may retry.
        try:
            retry_after = max(1, int(e.limit.limit.get_expiry()))
        except (AttributeError, TypeError, ValueError):
            retry_after = None
        response = jsonify({
            'error': 'rate_limit_exceeded',
            'message': 'Too many requests. Please slow down.',
            'retry_after': retry_after,
        })
        if retry_after is not None:
            response.headers['Retry-After'] = str(retry_after)
        return response, 429


@app.errorhandler(400)
def handle_bad_request(e):
    if request.accept_mimetypes.accept_html and not request.is_json:
        return e
    return jsonify({'error': 'bad_request', 'message': 'Invalid request'}), 400


@app.errorhandler(404)
def handle_not_found(e):
    if request.accept_mimetypes.accept_html and not request.is_json:
        return e
    return jsonify({'error': 'not_found', 'message': 'Resource not found'}), 404


@app.errorhandler(413)
def handle_payload_too_large(e):
    if request.accept_mimetypes.accept_html and not request.is_json:
        return e
    return jsonify({'error': 'payload_too_large', 'message': 'Request body too large'}), 413


@app.errorhandler(500)
def handle_server_error(e):
    logger.error(f"Internal server error: {e}\n{traceback.format_exc()}")
    return jsonify({'error': 'internal_error', 'message': 'Something went wrong'}), 500


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    port = int(os.environ.get('PORT', 7860))
    debug = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    # The Werkzeug debugger is an interactive Python shell. Binding it to
    # 0.0.0.0 turns any leaked FLASK_DEBUG into unauthenticated RCE.
    host = '127.0.0.1' if debug else '0.0.0.0'
    logger.info(f"Starting dev server on {host}:{port} (debug={debug})...")
    app.run(host=host, port=port, debug=debug)
