# Tech News Aggregator - Technical Architecture

This document explains the current implementation in the repository and reflects the latest hardening and data-flow changes.

---

## 1. System Overview

The app is a Flask-based news aggregation service composed of three core modules:

- web_scraper.py: source adapters + aggregation orchestration
- database.py: SQLite persistence, FTS5 indexing, and query APIs
- app.py: HTTP routes, validation, background jobs, and integration endpoints

Data flow:

1. Scrapers pull stories from external sources.
2. Aggregator merges story lists and caches them for 5 minutes.
3. Database layer inserts deduplicated records.
4. Metadata enrichment updates sentiment/category/read-time asynchronously.
5. Flask routes serve UI and API responses from persisted data.

---

## 2. Scraping Layer (web_scraper.py)

### 2.1 BaseScraper Contract

All source scrapers inherit from BaseScraper and share:

- requests.Session with retry policy:
  - total retries: 3
  - backoff_factor: 0.5
  - retried statuses: 429, 500, 502, 503
- common User-Agent header
- health state fields:
  - last_status
  - last_scrape_time
  - scrape_duration
  - last_error

### 2.2 Source Adapters

- HackerNewsScraper:
  - primary source: hnrss.org RSS
  - fallback source: news.ycombinator.com HTML parser
- TechCrunchScraper: RSS
- RedditScraper: JSON API (/r/technology/top.json)
- TheVergeScraper: RSS
- ArsTechnicaScraper: RSS

### 2.3 Aggregation and Caching

NewsAggregator manages all scrapers and executes them via ThreadPoolExecutor(max_workers=5).

- CACHE_TTL = 300 seconds
- scrape_all(force=False) returns cached in-memory results when TTL is valid
- scrape_all(force=True) always refreshes source content
- get_health() exposes per-source scrape diagnostics

---

## 3. Persistence and Search Layer (database.py)

### 3.1 SQLite Connection Behavior

Each operation uses a short-lived context-managed connection with:

- sqlite3.Row row factory
- timeout=15 at connect time
- PRAGMA busy_timeout = 5000

This improves behavior under transient lock pressure.

### 3.2 Schema and Migrations

Primary table: articles

- Core identity/content: id, title, link, score, author, time_posted, comments, source
- Runtime state: created_at, is_saved, is_read
- NLP metadata: sentiment, sentiment_score, category, read_time
- Metadata lifecycle: metadata_processed_at

Initialization includes idempotent migration checks for expected columns before ALTER TABLE.

### 3.3 Full-Text Search (FTS5)

- Virtual table: articles_fts(title, author, source)
- Synchronization triggers:
  - articles_ai (insert)
  - articles_ad (delete)
  - articles_au (update)
- search_articles(query, limit) issues MATCH queries
- If FTS errors, database falls back to LIKE-based retrieval

### 3.4 Query Semantics and Sorting

get_articles supports filtering by source, keyword, saved/unread state, and category.

Sort behavior is SQL-driven (not post-pagination in Python):

- newest: created_at DESC
- score: CAST(score AS INTEGER) DESC, created_at DESC
- comments: numeric comments DESC, created_at DESC

This guarantees consistent ordering across paginated pages.

### 3.5 Metadata Processing Idempotency

get_unprocessed_articles now selects rows where metadata_processed_at IS NULL.

During enrichment, update_article_metadata sets metadata_processed_at, so the same rows are not repeatedly reprocessed in subsequent background runs.

---

## 4. Application Layer (app.py)

### 4.1 Input Validation and Normalization

The route layer includes centralized helpers for input safety:

- parse_bounded_int: numeric clamping for pagination/scrape bounds
- parse_positive_int: strict positive id parsing
- sanitize_keyword: regex-filtered keyword with max length
- sanitize_search_query: bounded FTS query sanitization
- normalize_sort_by: restricts sort to score/comments/newest
- normalize_source_filter: source whitelist
- normalize_category_filter: category whitelist based on keyword map
- get_json_payload: safe JSON parsing returning None for malformed bodies

### 4.2 URL and Email Safety

is_safe_url applies outbound URL protections:

- http/https only
- rejects credentialed URLs
- rejects localhost and blocked hostnames
- blocks private/reserved/link-local/loopback/multicast/unspecified IPs
- resolves hostnames and rejects those resolving to disallowed IP ranges
- allows explicit ports only 80 and 443

is_valid_email enforces length and blocks CRLF characters before regex validation.

### 4.3 Dashboard Routes

- GET/POST / : main feed, scraping trigger, filtered retrieval, pagination
- GET /saved : saved-only feed
- GET /download : streamed CSV export

### 4.4 API Routes

- POST /bookmark
- POST /toggle_read
- POST /subscribe
- GET /api/stats
- GET /api/search
- GET /api/health
- GET /api/personalized
- POST /api/summarize
- POST /api/webhook/test
- POST /api/email/digest
- GET /export/json
- GET /export/markdown

Error handling patterns:

- Invalid/missing JSON payloads return 400
- Invalid article ids return 400
- Missing rows in bookmark/read toggles return 404
- summarize and webhook endpoints reject unsafe URLs

---

## 5. NLP and Metadata Enrichment

Metadata is derived from article titles:

- Category classification: keyword scoring over CATEGORY_KEYWORDS
- Sentiment analysis: NLTK VADER compound score thresholds
- Read-time estimate: heuristic based on title length

Background enrichment flow:

1. Fetch unprocessed rows (metadata_processed_at IS NULL)
2. Compute category, sentiment, read-time
3. Persist metadata + metadata_processed_at timestamp

---

## 6. Scheduler Lifecycle

Background scraping uses APScheduler when installed.

- start_scheduler() creates a 15-minute interval job for background_scrape
- In Flask debug mode, startup is guarded with WERKZEUG_RUN_MAIN checks to avoid duplicate scheduler instances
- stop_scheduler() is registered via atexit for graceful shutdown

Startup sequence in __main__:

1. logging setup
2. initial metadata processing pass
3. scheduler startup
4. app.run

---

## 7. Export and Integrations

- CSV export: streamed response with csv.DictWriter + generator
- JSON export: saved/bookmarked articles as JSON
- Markdown export: bookmarks grouped by source
- Webhook test: posts compact digest payload to WEBHOOK_URL
- Email digest: SMTP-based digest of top 10 records

---

## 8. Frontend and PWA

Template: templates/index.html

- Bootstrap-based dashboard
- client-side API calls for bookmark/read/summary/subscribe/personalized features
- service worker registration

PWA support:

- GET /manifest.json route
- static/service-worker.js cache implementation

---

## 9. Current Gaps

- No automated test suite is implemented yet in tests/
- No CI pipeline is configured
- Optional integrations (SMTP/webhook) require environment configuration

---

## 10. Summary

The current system is a practical single-node Flask + SQLite architecture optimized for lightweight deployment. Recent updates improved request validation, outbound URL safety, pagination-sort correctness, scheduler lifecycle behavior, and idempotent metadata processing.
