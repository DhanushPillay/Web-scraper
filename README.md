# Sniffer

![Python Version](https://img.shields.io/badge/python-3.8%2B-blue)
![Flask Version](https://img.shields.io/badge/flask-3.0%2B-green)
![License](https://img.shields.io/badge/license-MIT-orange)

Sniffer is a Flask application that collects technology stories from five major sources, enriches the data with NLP metadata, and serves a searchable, mobile-first PWA dashboard with bookmarks, exports, and integration endpoints.

## What It Does

- Aggregates stories from Hacker News, TechCrunch, Reddit (r/technology), The Verge, and Ars Technica.
- Scrapes sources concurrently with retries, RSS-first strategy, and source health tracking.
- Caches scraper results (5 minute TTL) to reduce unnecessary network requests.
- Persists data in SQLite with deduplication by URL and ~280-char article excerpts for preview.
- Supports full-text search via SQLite FTS5 (title, author, source, excerpt) with LIKE fallback.
- Adds metadata in the background: category, sentiment, read time.
- Supports bookmarks, read/unread status, and personalized feed ranking.
- Exports data as CSV, JSON, and Markdown.
- Offers optional webhook test and SMTP digest endpoints.
- **Mobile-first, accessible PWA** with offline support, install prompt, and keyboard shortcuts.

## Recent Major Updates

### UI/UX Overhaul (v2.0)
- **Mobile-first responsive design** — works on phones, tablets, laptops, desktops.
- **New design system** — CSS custom properties, optical spacing, system font stack (no framework).
- **Article cards with excerpts** — title → excerpt → meta → actions (layer-cake scanning pattern).
- **Source color indicator** — subtle 4px left border per source, not loud badges.
- **Skeleton loaders** — perceived performance, no layout shift.
- **Load more pagination** — replaces numbered pagination, better for mobile data usage.
- **Light/dark mode toggle** — persists in localStorage, respects `prefers-color-scheme`.
- **Keyboard shortcuts** — J/K navigate, O open, B bookmark, R read, / search, ? help.
- **Full accessibility** — focus-visible styles, ARIA labels, reduced-motion support, screen-reader friendly.

### Security Hardening
- Flask-Talisman with CSP, HSTS, X-Frame-Options, Referrer-Policy, Permissions-Policy.
- CSRF protection on all state-changing forms.
- Rate limiting on API endpoints (Flask-Limiter).
- SSRF protection: outbound URL validation blocks localhost, private IPs, non-80/443 ports.
- SQL injection safety: parameterized queries; allowlist validation for sort/source/category.
- Strict email validation with length and CRLF checks.

### Data Layer
- **`excerpt` column** — ~280-char preview from RSS description/summary, word-boundary truncated.
- **FTS5 includes excerpt** — full-text search now covers article previews.
- **Database indexes** — `created_at`, `source`, `is_saved`, `is_read`, `category`, `score`.
- **WAL mode** — better concurrent read performance.

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
|-- app.py
|-- web_scraper.py
|-- database.py
|-- templates/
|   `-- index.html
|-- static/
|   |-- css/
|   |   `-- app.css
|   |-- js/
|   |   `-- app.js
|   |-- service-worker.js
|   `-- icons/         # PWA icons
|-- doc/
|   `-- project_explanation.md
|-- tests/
|-- requirements.txt
`-- sniffer.db        # runtime generated
```

## Database Model

Main table: `articles`

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK AUTOINCREMENT | |
| title | TEXT NOT NULL | |
| link | TEXT UNIQUE NOT NULL | dedup key |
| score | INTEGER DEFAULT 0 | |
| author | TEXT | |
| time_posted | TEXT | |
| comments | TEXT | |
| source | TEXT | |
| created_at | REAL | |
| is_saved | INTEGER DEFAULT 0 | |
| is_read | INTEGER DEFAULT 0 | |
| sentiment | TEXT DEFAULT 'neutral' | |
| sentiment_score | REAL DEFAULT 0.0 | |
| category | TEXT DEFAULT 'general' | |
| read_time | INTEGER DEFAULT 0 | |
| metadata_processed_at | REAL | idempotency marker |
| **excerpt** | TEXT DEFAULT '' | ~280 char RSS preview |

FTS table: `articles_fts(title, author, source, excerpt)` with triggers for insert/update/delete sync.

## API and Routes

UI routes:

- GET `/` — dashboard
- POST `/` — scrape + filter form submit
- GET `/saved` — bookmarked list
- GET `/download` — CSV export (streamed)
- GET `/export/json` — bookmarked JSON export
- GET `/export/markdown` — bookmarked Markdown export
- GET `/manifest.json` — PWA manifest
- GET `/service-worker.js` — service worker

JSON API routes:

- POST `/bookmark` — toggle bookmark, body `{ article_id }`
- POST `/toggle_read` — toggle read status, body `{ article_id }`
- POST `/subscribe` — subscribe email, body `{ email }`
- GET `/api/stats` — aggregate stats
- GET `/api/search?q=...` — full-text search
- GET `/api/health` — scraper health snapshot
- GET `/api/personalized` — personalized feed
- GET `/api/articles/load-more` — paginated article fetch (page, sort, source, keyword, category)
- POST `/api/summarize` — summarize URL, body `{ url }`
- POST `/api/webhook/test` — send sample digest to WEBHOOK_URL
- POST `/api/email/digest` — send digest via SMTP to body `{ email }`

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| J / ↓ | Next article |
| K / ↑ | Previous article |
| O / Enter | Open article |
| B | Toggle bookmark |
| R | Toggle read |
| / | Focus search |
| ? | Show help |
| Esc | Close modal / help |

## Notes on Runtime Behavior

- Scheduler runs every 15 minutes when APScheduler is installed.
- In debug mode, scheduler startup is guarded to avoid duplicate runs.
- Metadata enrichment processes only rows where `metadata_processed_at IS NULL`.
- Sort order for paginated queries is handled in SQL for consistency.
- Service worker caches static assets and API responses for offline reading.
- Excerpt extraction strips HTML, normalizes whitespace, and truncates at word boundary.

## Troubleshooting

- Missing NLTK resources: start app once and let auto-download complete.
- Empty source results: source may be temporarily unavailable or rate-limited.
- SMTP errors: verify SMTP_* variables and app-password requirements.
- Webhook test blocked: ensure WEBHOOK_URL passes safe URL checks.
- Database locked: enable WAL mode (`PRAGMA journal_mode=WAL`).

## Development Status

- Tests directory exists but currently has no test files.
- CI workflow is not configured yet.

## License

MIT