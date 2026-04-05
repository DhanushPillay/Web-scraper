# Tech News Aggregator - Deep Technical Architecture

This document provides a highly detailed, component-level technical explanation of the Tech News Aggregator. It covers the internal mechanisms, concurrency models, data pipelines, NLP applications, and design patterns used across the stack.

---

## 1. The Scraping Engine (`web_scraper.py`)

The scraping engine is responsible for efficiently aggregating data from 5 disparate sources. It is designed around resilience, speed, and concurrency.

### 1.1 Base Abstraction (`BaseScraper`)
All scrapers inherit from `BaseScraper(ABC)`.
- **Session Management**: Uses `requests.Session()` to pool connections.
- **Resiliency**: Implements `urllib3.util.retry.Retry` with a backoff factor of `0.5` and 3 total retries for specific HTTP statuses (`429, 500, 502, 503`). This ensures transient network failures don't break the scraping pipeline.
- **Health Tracking**: Tracks `last_status`, `scrape_duration`, and `last_error` per source to power the dashboard's health API.

### 1.2 Data Ingestion Strategies
The engine prioritizes speed by preferring structured data formats over raw HTML parsing:
- **RSS Feeds (`feedparser`)**: TechCrunch, The Verge, Ars Technica, and Hacker News (via `hnrss.org`) use RSS. `feedparser` parses these feeds instantly without the overhead of DOM traversal.
- **JSON APIs**: Reddit (`r/technology/top.json`) is queried directly via its native API.
- **HTML Fallback (`BeautifulSoup`)**: If the Hacker News RSS feed fails or is empty, the `HackerNewsScraper` falls back to the `_scrape_html` method. It iterates over `num_pages`, introducing a 1-second `time.sleep()` to prevent rate limiting, and parses the DOM using `BeautifulSoup` (`'html.parser'`), targeting `tr.athing` and `tr > td.subtext` to extract scores, authors, and comments.

### 1.3 Concurrency & Caching (`NewsAggregator`)
- **Multithreading**: The `scrape_all` method executes all 5 scrapers simultaneously using `concurrent.futures.ThreadPoolExecutor(max_workers=5)`. This reduces the total scrape time from the sum of all response times to roughly the time of the slowest source.
- **Caching Mechanism**: Implements a Time-To-Live (TTL) cache (`CACHE_TTL = 300` seconds). If a user requests a scrape within 5 minutes of the last one, it skips network requests entirely unless forced (`force=True`).

---

## 2. Data Persistence & Indexing (`database.py`)

The application uses SQLite3, highly optimized for read-heavy operations, with native full-text search capabilities.

### 2.1 Database Initialization & Schema Migrations
- Uses `sqlite3.Row` for dict-like row access.
- **Idempotent Migrations**: The `init_db` method safely checks if specific columns (e.g., `sentiment`, `category`) exist using `SELECT ... LIMIT 1`. If an `OperationalError` happens, it issues an `ALTER TABLE` to append the column. This natively supports schema evolution without external libraries like Alembic.

### 2.2 FTS5 Full-Text Search Implementation
Standard `LIKE` queries are O(N) and slow down as the database grows. This app implements O(1) text search using SQLite's `FTS5` extension.
- **Virtual Table**: `CREATE VIRTUAL TABLE articles_fts USING fts5(title, author, source, content='articles', content_rowid='id')`.
- **Trigger-Based Synchronization**: To keep the `articles_fts` index completely synchronized with the `articles` table without writing dual-insert logic in Python, three SQLite triggers handle it natively:
  1. `articles_ai` (After Insert): Pushes new row into FTS.
  2. `articles_ad` (After Delete): Removes deleted row from FTS.
  3. `articles_au` (After Update): Updates FTS row.
- **Query Execution**: `search_articles` executes a `MATCH` query against the `articles_fts` table, ordering by SQLite's internal `rank` function (BM25 algorithm) for relevance.

### 2.3 Personalized Feed Algorithm
The `/api/personalized` endpoint surfaces content tailored to user behavior.
1. It queries the 3 most frequent `source` and `category` values among articles where `is_saved = 1`.
2. It constructs a dynamic SQL query to calculate a `relevance_score` using `CASE WHEN ... THEN`. Matches on favored sources grant +2 points; favored categories grant +1 point.
3. The results are ordered by `relevance_score DESC, created_at DESC`.

---

## 3. NLP & Data Enrichment (`app.py`)

The application performs background natural language processing on article titles to extract semantic meaning.

### 3.1 Rule-Based Categorization
- `classify_article(title)` uses a dictionary mapping of themes (`CATEGORY_KEYWORDS`) to lists of keywords (e.g., 'Business', 'AI & ML', 'Hardware').
- It generates a score for each category by counting exact substring matches in the normalized string. The highest score wins.

### 3.2 Sentiment Analysis (NLTK VADER)
- Uses `nltk.sentiment.vader.SentimentIntensityAnalyzer`.
- Calculates the `compound` polarity score (from -1 to +1).
- Triggers custom labels: `>= 0.05` is Positive, `<= -0.05` is Negative, else Neutral.

### 3.3 Trending Topics / TF-IDF Alternative
- `extract_trending_topics` calculates frequency distributions (`collections.Counter`) of words and bigrams across recent titles.
- It filters out non-alpha characters via regex `[a-zA-Z]{3,}` and strips English filler words using `nltk.corpus.stopwords` combined with domain-specific stop words (e.g., 'new', 'says', 'use').
- Generates 2-word phrases (bigrams) to extract context like "artificial intelligence" instead of just "artificial".

### 3.4 AI Summarization Component
- Handled dynamically on the `/api/summarize` endpoint.
- Instantiates an `Article` object from the `newspaper3k` library.
- Calls `download()`, `parse()`, and `nlp()` to fetch the HTML, extract the primary text (stripping ads and menus), and run extractive summarization to return a concise paragraph along with the `top_image`.

---

## 4. Web Application Architecture (Flask)

### 4.1 Route Controllers & Endpoints
- **Pagination**: The `index` route uses structural offsets (`(page - 1) * per_page`) inside the database queries.
- **REST APIs**: Bookmarking and read statuses are handled via JSON POST requests. Returning success `{'status': 'saved'}` toggles UI states via standard vanilla JavaScript handlers.

### 4.2 Streaming Large Exports
- The `/download` endpoint generates a CSV file of the articles.
- Instead of keeping a potentially massive string in memory, it leverages Flask's `stream_with_context` alongside a generator function and `io.StringIO()`.
- It writes row-by-row, yielding the buffer output and immediately truncating `output.truncate(0)`. This handles high-volume dataset exports with minimal RAM overhead.

### 4.3 Background Schedulers
- Imports `apscheduler.schedulers.background.BackgroundScheduler`.
- Exposes two core background tasks:
  1. `background_scrape()`: Forces a cache bypass and retrieves new articles.
  2. `process_articles_metadata()`: Finds records with generic metadata (`sentiment = 'neutral'`, `category = 'general'`) and processes them in batches of 100, offloading NLTK processing from request-response cycles to ensure fast page loads for end-users.
