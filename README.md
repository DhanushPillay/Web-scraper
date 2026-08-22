---
title: Sniffer
emoji: 🔍
colorFrom: indigo
colorTo: purple
sdk: docker
sdk_version: "4.1.0"
python_version: "3.12"
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

# Sniffer — Cloud Data Lake for Tech Intelligence

![Python Version](https://img.shields.io/badge/python-3.12-blue)
![Flask Version](https://img.shields.io/badge/flask-3.0%2B-green)
![License](https://img.shields.io/badge/license-MIT-orange)

**Sniffer is a cloud-native data lake pipeline** that ingests 7 heterogeneous sources (RSS / JSON / XML) into a partitioned Parquet lakehouse, processed with PySpark + DuckDB and served as a PWA — **₹0 infra** on Hugging Face Spaces + Neon + GitHub Actions.

> Formerly *Sniffer*. Same polished PWA, now with a *data platform* underneath for Big Data / Cloud interviews.

## Architecture — Lakehouse (₹0, no AWS)

```text
[RSS] HN · TechCrunch · Verge · Ars  +  [JSON] Reddit · GitHub Trending  +  [XML] arXiv
        │  BaseScraper(Retry3) + pagination + watermark.json  (variety: 3 protocols)
        ▼
Bronze  data/bronze/YYYY/MM/DD/<source>.jsonl  (append-only, raw)
        │  validate.py (link NOT NULL, title>10, dedup)
        ▼
Silver  data/silver/  Parquet partitioned by day/source  (pyarrow)
        │  PySpark local[*] repartition(source) → Gold  (or pandas fallback)
        ▼
Gold    data/gold/YYYY/MM/DD/daily_stats.{parquet,json}  (DuckDB/Athena SQL)
        │  GitHub Actions cron → Hugging Face Dataset (private 100GB free)
        ▼
Serving  Flask PWA + Neon Postgres (0.5GB free) + DuckDB reads Gold for /api/stats
```

## What It Does

- **Ingests 7 sources** — Hacker News / TechCrunch / Reddit / The Verge / Ars Technica / **GitHub Trending (JSON API)** / **arXiv (XML Atom)** — concurrent `asyncio.to_thread` + `Semaphore(8)` image enrichment + dedup by `link` + credibility filter.
- **Variety:** RSS + JSON + XML, 3 schemas unified to one Silver schema (proves you handle semi-structured).
- **Incremental:** `watermark.json` + per-day Bronze append (not full reload) — history accumulates to Parquet, not just last 30 rows.
- **Lakehouse:** Bronze JSONL → Silver Parquet partitioned `day/source` → Gold aggregates via PySpark (`local[*]`) or pandas fallback → queried via DuckDB (`read_parquet(..., hive_partitioning=1)`) — same SQL as Athena, no Redshift bill.
- **Quality:** `pipeline/validate.py` (link/title/score checks, duplicate detection) + `data_quality.log`.
- **Storage:** SQLite WAL for OLTP bookmarks + Parquet lake for analytics + Neon 0.5GB free for prod (HF SQLite ephemeral otherwise).
- **Serving:** Same mobile-first PWA, FTS5 search, bookmarks, exports, now with `/api/stats` preferring Gold layer.
- **Orchestration:** GitHub Actions cron `0 2 * * *` (public repo = unlimited minutes) → `pipeline/run.py` → artifact + HF Dataset push (no APScheduler on HF free tier).
- **IaC:** `infrastructure/main.tf` (S3 bucket stub) + `docker-compose.yml` — shows Terraform without provisioning.

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

## Quick Start (Local — still 1 command)

```bash
git clone https://huggingface.co/spaces/your-username/sniffer
cd sniffer
pip install -r requirements.txt
python -c "import nltk; [nltk.download(r, quiet=True) for r in ['punkt','punkt_tab','vader_lexicon','stopwords']]"
# lake: scrape → bronze → silver → gold (no AWS)
python pipeline/run.py          # scrapes 7 sources, writes data/bronze → silver → gold
python app.py                   # http://localhost:7860 (reads Gold if present, else DB)
```

With Docker:
```bash
docker compose up --build        # app on 7860
docker compose run --rm pipeline python pipeline/run.py
```

Lake only (reuse bronze):
```bash
python pipeline/run.py --no-scrape   # reprocess existing Bronze
python -c "from processing.spark_job import run_gold_pandas; run_gold_pandas()"
```

## Configuration (Environment Variables — all optional)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SECRET_KEY` | No | random | Flask secret |
| `DATABASE_URL` | No | SQLite | Neon free Postgres DSN (`postgresql://.../neondb`) |
| `HF_DATASET` | No | — | HF Dataset for Gold push (`username/sniffer-gold`) |
| `HF_TOKEN` | No | — | HF write token (for GH Actions push) |
| `GITHUB_TOKEN` | No | `GITHUB_TOKEN` in Actions | Raises GitHub API 60→5000 req/h |
| `SNIFFER_MINIMAL` | No | `0` | `1` = only 5 core sources (CI without token) |
| `WEBHOOK_URL` / `SMTP_*` | No | — | Optional integrations |
| `ALLOWED_ORIGINS` / `TRUSTED_HOSTS` | No | — | CORS/host allowlist |

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
| POST | `/api/summarize` | Summarize URL `{url}` |
| POST | `/api/webhook/test` | Test webhook (needs `WEBHOOK_URL`) |
| POST | `/api/email/digest` | Send digest (needs SMTP) |

## Free Deployment (₹0, no AWS)

| Layer | Where | Free forever | Limits |
|---|---|---|---|
| App | HF Spaces CPU Basic | YES | 2 vCPU/16GB, 50GB disk, sleeps 48h |
| Lake (Gold) | HF Dataset (private) | YES | 100GB, versioned |
| DB (bookmarks) | Neon | YES | 0.5GB, 100 CU-hours/mo, 100 projects |
| Cron | GitHub Actions (public repo) | YES | unlimited public, 2000 min/mo private |
| Alt DB | Supabase | YES but pauses 7d idle | 500MB — use Neon to avoid |

**Deploy:**
```bash
# 1. HF Space (Docker) — git push, no card
git remote add space https://huggingface.co/spaces/<you>/sniffer
git push space main

# 2. Neon — Settings → Variables → DATABASE_URL
# 3. HF Dataset for Gold — create private dataset, set HF_DATASET + HF_TOKEN in Space + GH Secrets
```

SQLite is ephemeral — Neon's 0.5GB survives rebuilds. Actions cron replaces APScheduler (disabled on HF). Port 7860 required by HF.

## License

MIT