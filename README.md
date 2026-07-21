---
title: Sniffer
emoji: 🔍
colorFrom: indigo
colorTo: purple
sdk: docker
sdk_version: "4.1.0"
python_version: "3.10"
app_port: 7860
tags:
  - flask
  - news
  - scraper
  - pwa
  - tech-news
  - rss
  - sentiment-analysis
---

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

## Quick Start (Local)

```bash
git clone https://huggingface.co/spaces/your-username/sniffer
cd sniffer
docker build -t sniffer .
docker run -p 7860:7860 sniffer
# Open http://localhost:7860
```

Or without Docker:
```bash
pip install -r requirements.txt
python -c "import nltk; [nltk.download(r, quiet=True) for r in ['punkt','punkt_tab','vader_lexicon','stopwords']]"
python app.py
```

## Configuration (Environment Variables)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SECRET_KEY` | No | random | Flask secret |
| `WEBHOOK_URL` | No | — | Slack/Discord webhook for `/api/webhook/test` |
| `SMTP_HOST` `SMTP_PORT` `SMTP_USER` `SMTP_PASS` | No | — | Email digest via `/api/email/digest` |
| `DATABASE_URL` | No | SQLite | Postgres DSN (Render, etc.) |
| `ALLOWED_ORIGINS` | No | — | CORS origins for API |
| `TRUSTED_HOSTS` | No | localhost | Host header allowlist |

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Dashboard (scrape + filter) |
| GET | `/saved` | Bookmarked articles |
| GET | `/download` | CSV export |
| GET | `/export/json` | JSON export (bookmarks) |
| GET | `/export/markdown` | Markdown export (bookmarks) |
| POST | `/bookmark` | Toggle bookmark `{article_id}` |
| POST | `/toggle_read` | Toggle read status `{article_id}` |
| POST | `/subscribe` | Email subscribe `{email}` |
| GET | `/api/stats` | Aggregate stats |
| GET | `/api/search?q=` | FTS5 search |
| GET | `/api/health` | Scraper health |
| GET | `/api/personalized` | Personalized feed |
| GET | `/api/articles/load-more` | Paginated articles |
| POST | `/api/summarize` | Summarize URL `{url}` |
| POST | `/api/webhook/test` | Test webhook (needs `WEBHOOK_URL`) |
| POST | `/api/email/digest` | Send digest (needs SMTP) |

## HF Spaces Notes

- **SQLite is ephemeral** — data resets on rebuild. For persistence, set `DATABASE_URL` to a managed Postgres (e.g., Neon, Supabase).
- **APScheduler disabled** on HF free tier (no background workers). Use "Refresh" button to scrape manually.
- **Port 7860** is required by HF Spaces (configured in Dockerfile).
- **First load** may take 15–30s while scrapers fetch and enrich articles.

## License

MIT