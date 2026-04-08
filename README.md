# Tech News Aggregator

![Python Version](https://img.shields.io/badge/python-3.8%2B-blue)
![Flask Version](https://img.shields.io/badge/flask-3.0%2B-green)
![License](https://img.shields.io/badge/license-MIT-orange)

Tech News Aggregator is a Flask application that collects technology stories from five major sources, enriches the data with NLP metadata, and serves a searchable dashboard with bookmarks, exports, and integration endpoints.

## What It Does

- Aggregates stories from Hacker News, TechCrunch, Reddit (r/technology), The Verge, and Ars Technica.
- Scrapes sources concurrently with retries and source health tracking.
- Caches scraper results (5 minute TTL) to reduce unnecessary network requests.
- Persists data in SQLite with deduplication by URL.
- Supports full-text search via SQLite FTS5 with fallback behavior.
- Adds metadata in the background: category, sentiment, read time.
- Supports bookmarks, read/unread status, and personalized feed ranking.
- Exports data as CSV, JSON, and Markdown.
- Offers optional webhook test and SMTP digest endpoints.

## Recent Hardening Updates

- Added bounded input parsing for page, scrape pages, and query values.
- Added keyword/query sanitization and source/sort/category normalization.
- Added safer JSON payload handling across API routes.
- Added stricter email validation for subscription and digest endpoints.
- Added outbound URL validation for summarize and webhook endpoints:
  - Blocks localhost and private/reserved IP targets.
  - Rejects credentialed URLs.
  - Restricts explicit ports to 80 and 443.
- Added scheduler startup guard to avoid duplicate jobs in debug reload mode.
- Added idempotent metadata processing marker with metadata_processed_at.

## Prerequisites

- Python 3.8+
- Internet access

## Installation

1. Clone repository.

```bash
git clone https://github.com/DhanushPillay/Web-scraper.git
cd Web-scraper
```

2. Install dependencies.

```bash
pip install -r requirements.txt
```

3. Run the app.

```bash
python app.py
```

Open http://127.0.0.1:5000/.

## Configuration

Optional environment variables:

- FLASK_DEBUG: true or false
- WEBHOOK_URL: URL used by POST /api/webhook/test
- SMTP_HOST: SMTP server host
- SMTP_PORT: SMTP server port (default 587)
- SMTP_USER: SMTP username/email
- SMTP_PASS: SMTP password/app password

## Project Structure

```text
Web-scraper/
|- app.py
|- web_scraper.py
|- database.py
|- templates/
|  \- index.html
|- static/
|  \- service-worker.js
|- doc/
|  \- project_explanation.md
|- tests/
|- requirements.txt
\- technews.db (runtime generated)
```

## Database Model

Main table: articles

- id INTEGER PRIMARY KEY AUTOINCREMENT
- title TEXT NOT NULL
- link TEXT UNIQUE NOT NULL
- score INTEGER DEFAULT 0
- author TEXT
- time_posted TEXT
- comments TEXT
- source TEXT
- created_at REAL
- is_saved INTEGER DEFAULT 0
- is_read INTEGER DEFAULT 0
- sentiment TEXT DEFAULT 'neutral'
- sentiment_score REAL DEFAULT 0.0
- category TEXT DEFAULT 'general'
- read_time INTEGER DEFAULT 0
- metadata_processed_at REAL

FTS table: articles_fts (title, author, source) with triggers for insert/update/delete sync.

## API and Routes

UI routes:

- GET / : dashboard
- POST / : scrape + filter form submit
- GET /saved : bookmarked list
- GET /download : CSV export
- GET /export/json : bookmarked JSON export
- GET /export/markdown : bookmarked Markdown export
- GET /manifest.json : PWA manifest
- GET /service-worker.js : service worker

JSON API routes:

- POST /bookmark : toggle bookmark, body { article_id }
- POST /toggle_read : toggle read status, body { article_id }
- POST /subscribe : subscribe email, body { email }
- GET /api/stats : aggregate stats
- GET /api/search?q=... : full-text search
- GET /api/health : scraper health snapshot
- GET /api/personalized : personalized feed
- POST /api/summarize : summarize URL, body { url }
- POST /api/webhook/test : send sample digest to WEBHOOK_URL
- POST /api/email/digest : send digest via SMTP to body { email }

## Notes on Runtime Behavior

- Scheduler runs every 15 minutes when APScheduler is installed.
- In debug mode, scheduler startup is guarded to avoid duplicate runs.
- Metadata enrichment processes only rows where metadata_processed_at IS NULL.
- Sort order for paginated queries is handled in SQL for consistency.

## Troubleshooting

- Missing NLTK resources: start app once and let auto-download complete.
- Empty source results: source may be temporarily unavailable or rate-limited.
- SMTP errors: verify SMTP_* variables and app-password requirements.
- Webhook test blocked: ensure WEBHOOK_URL passes safe URL checks.

## Development Status

- Tests directory exists but currently has no test files.
- CI workflow is not configured yet.

## License

MIT
