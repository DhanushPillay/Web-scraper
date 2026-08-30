"""
Database Module — Sniffer
SQLite with FTS5 full-text search, sentiment/category columns,
pagination, reading list, and export features.
Supports both SQLite (local) and PostgreSQL (production).
"""
import os
import re
import sqlite3
import time
import json
import logging
from contextlib import contextmanager
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_name: str = "sniffer.db") -> None:
        # PostgreSQL is configured through DATABASE_URL.  A few callers used to
        # pass that URL as ``db_name``; keep the SQLite fallback a real local
        # filename instead of trying to open a URL as a filesystem path.
        self.db_name = (
            "sniffer.db"
            if str(db_name).startswith(("postgres://", "postgresql://"))
            else db_name
        )
        self._use_postgres = bool(os.getenv("DATABASE_URL"))
        self._pg_pool = None

        if self._use_postgres:
            for attempt in range(1, 4):
                try:
                    self._init_pg_pool()
                    # Test connection upfront
                    conn = self._pg_pool.getconn()
                    self._pg_pool.putconn(conn)
                    break
                except Exception as e:
                    if attempt < 3:
                        logger.warning(f"PostgreSQL connection failed (attempt {attempt}): {e}. Retrying in {2 ** attempt}s...")
                        time.sleep(2 ** attempt)
                        # Reset pool for next attempt
                        if self._pg_pool:
                            try:
                                self._pg_pool.closeall()
                            except Exception:
                                pass
                        self._pg_pool = None
                    else:
                        logger.error(f"PostgreSQL connection failed after 3 attempts: {e}. Falling back to SQLite WAL mode.")
                        self._use_postgres = False
                        if self._pg_pool:
                            try:
                                self._pg_pool.closeall()
                            except Exception:
                                pass
                        self._pg_pool = None

        self.init_db()

    def _init_pg_pool(self) -> None:
        """Initializes the PostgreSQL connection pool."""
        if self._pg_pool is None:
            import psycopg2
            from psycopg2.extras import RealDictCursor
            from psycopg2.pool import ThreadedConnectionPool
            dsn = os.getenv("DATABASE_URL", "").strip()
            # Render provides postgres://... but psycopg2 requires postgresql://
            if dsn.startswith("postgres://"):
                dsn = dsn.replace("postgres://", "postgresql://", 1)
            # All query methods use mapping-style row access (row['title']) or
            # convert rows with dict(row).  PostgreSQL cursors return tuples by
            # default, unlike SQLite's Row objects, so use dictionary cursors
            # consistently for both backends.
            self._pg_pool = ThreadedConnectionPool(
                1, 10, dsn, cursor_factory=RealDictCursor
            )

    @contextmanager
    def get_connection(self):
        """Context manager that auto-closes the DB connection with automatic fallback."""
        if self._use_postgres:
            try:
                if self._pg_pool is None:
                    self._init_pg_pool()
                conn = self._pg_pool.getconn()
            except Exception as e:
                logger.error(f"PostgreSQL connection error: {e}. Falling back to SQLite.")
                self._use_postgres = False
                self._pg_pool = None
            else:
                # Only connection-acquisition failures should fall back to
                # SQLite.  SQL errors need to surface to the caller; treating
                # them as connection failures masks the real problem.
                conn.autocommit = False
                try:
                    yield conn
                    conn.commit()
                except Exception:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    raise
                finally:
                    if self._pg_pool:
                        self._pg_pool.putconn(conn)
                return

        # SQLite fallback
        conn = sqlite3.connect(self.db_name, timeout=15)
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _row_to_dict(self, cursor, row) -> Dict[str, Any]:
        """Safely converts a database row to a dictionary."""
        if hasattr(row, 'keys') and callable(getattr(row, 'keys')):
            try:
                return dict(row)
            except (TypeError, ValueError):
                pass
        cols = [col[0] for col in cursor.description]
        return dict(zip(cols, row))

    def _fetch_scalar(self, cursor) -> Any:
        """Safely fetches a single scalar value from the first column of the next row."""
        row = cursor.fetchone()
        if row is None:
            return None
        return list(self._row_to_dict(cursor, row).values())[0]

    def init_db(self) -> None:
        """Initializes the database table and ensures schema is up to date."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            if self._use_postgres:
                # ``CREATE TABLE IF NOT EXISTS`` is not safe when multiple
                # web/worker processes initialize a brand-new PostgreSQL
                # schema concurrently.  The transaction-scoped advisory lock
                # serializes the DDL across GitHub Actions and web instances.
                cursor.execute("SELECT pg_advisory_xact_lock(%s)", (734010592,))

                # PostgreSQL schema
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS articles (
                        id SERIAL PRIMARY KEY,
                        title TEXT NOT NULL,
                        link TEXT UNIQUE NOT NULL,
                        score INTEGER DEFAULT 0,
                        author TEXT,
                        time_posted TEXT,
                        comments TEXT,
                        source TEXT,
                        created_at REAL,
                        is_saved INTEGER DEFAULT 0,
                        is_read INTEGER DEFAULT 0,
                        sentiment TEXT DEFAULT 'neutral',
                        sentiment_score REAL DEFAULT 0.0,
                        category TEXT DEFAULT 'general',
                        read_time INTEGER DEFAULT 0,
                        metadata_processed_at REAL,
                        excerpt TEXT DEFAULT '',
                        image_url TEXT DEFAULT '',
                        dek TEXT DEFAULT '',
                        bullets TEXT DEFAULT '[]'
                    )
                ''')
                # Create indexes for PostgreSQL (keep composites, drop redundant single-col where composite covers)
                indexes = [
                    "CREATE INDEX IF NOT EXISTS idx_articles_sentiment ON articles(sentiment)",
                    "CREATE INDEX IF NOT EXISTS idx_articles_created_at ON articles(created_at DESC)",
                    "CREATE INDEX IF NOT EXISTS idx_articles_source_created ON articles(source, created_at DESC)",
                    "CREATE INDEX IF NOT EXISTS idx_articles_category_created ON articles(category, created_at DESC)",
                    "CREATE INDEX IF NOT EXISTS idx_articles_saved_created ON articles(is_saved, created_at DESC)",
                    "CREATE INDEX IF NOT EXISTS idx_articles_read_created ON articles(is_read, created_at DESC)",
                ]
                for idx in indexes:
                    cursor.execute(idx)

                # FTS not directly supported in PG same way, use tsvector/tsquery or pg_trgm
                # For now, we'll rely on ILIKE with indexes
            else:
                # SQLite schema
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS articles (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL,
                        link TEXT UNIQUE NOT NULL,
                        score INTEGER DEFAULT 0,
                        author TEXT,
                        time_posted TEXT,
                        comments TEXT,
                        source TEXT,
                        created_at REAL,
                        is_saved INTEGER DEFAULT 0,
                        is_read INTEGER DEFAULT 0,
                        sentiment TEXT DEFAULT 'neutral',
                        sentiment_score REAL DEFAULT 0.0,
                        category TEXT DEFAULT 'general',
                        read_time INTEGER DEFAULT 0,
                        metadata_processed_at REAL,
                        excerpt TEXT DEFAULT '',
                        image_url TEXT DEFAULT '',
                        dek TEXT DEFAULT '',
                        bullets TEXT DEFAULT '[]'
                    )
                ''')

                # Migrations for existing SQLite databases (single PRAGMA, not 9 SELECTs)
                cursor.execute("PRAGMA table_info(articles)")
                existing_cols = {row[1] for row in cursor.fetchall()}
                migrations = [
                    ("is_saved", "INTEGER DEFAULT 0"),
                    ("is_read", "INTEGER DEFAULT 0"),
                    ("sentiment", "TEXT DEFAULT 'neutral'"),
                    ("sentiment_score", "REAL DEFAULT 0.0"),
                    ("category", "TEXT DEFAULT 'general'"),
                    ("read_time", "INTEGER DEFAULT 0"),
                    ("metadata_processed_at", "REAL"),
                    ("excerpt", "TEXT DEFAULT ''"),
                    ("image_url", "TEXT DEFAULT ''"),
                    ("dek", "TEXT DEFAULT ''"),
                    ("bullets", "TEXT DEFAULT '[]'"),
                ]
                for col_name, col_type in migrations:
                    if col_name not in existing_cols:
                        logger.info(f"Migrating DB: Adding '{col_name}' column...")
                        cursor.execute(f"ALTER TABLE articles ADD COLUMN {col_name} {col_type}")

                # FTS5 virtual table for full-text search
                cursor.execute('''
                    CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
                        title, author, source, excerpt,
                        content='articles',
                        content_rowid='id'
                    )
                ''')

                # Triggers to keep FTS in sync
                cursor.execute('''
                    CREATE TRIGGER IF NOT EXISTS articles_ai AFTER INSERT ON articles BEGIN
                        INSERT INTO articles_fts(rowid, title, author, source, excerpt)
                        VALUES (new.id, new.title, new.author, new.source, new.excerpt);
                    END
                ''')
                cursor.execute('''
                    CREATE TRIGGER IF NOT EXISTS articles_ad AFTER DELETE ON articles BEGIN
                        INSERT INTO articles_fts(articles_fts, rowid, title, author, source, excerpt)
                        VALUES ('delete', old.id, old.title, old.author, old.source, old.excerpt);
                    END
                ''')
                cursor.execute('''
                    CREATE TRIGGER IF NOT EXISTS articles_au AFTER UPDATE ON articles BEGIN
                        INSERT INTO articles_fts(articles_fts, rowid, title, author, source, excerpt)
                        VALUES ('delete', old.id, old.title, old.author, old.source, old.excerpt);
                        INSERT INTO articles_fts(rowid, title, author, source, excerpt)
                        VALUES (new.id, new.title, new.author, new.source, new.excerpt);
                    END
                ''')

                # SQLite indexes (composite covers single-col lookups)
                indexes = [
                    "CREATE INDEX IF NOT EXISTS idx_articles_sentiment ON articles(sentiment)",
                    "CREATE INDEX IF NOT EXISTS idx_articles_created_at ON articles(created_at DESC)",
                    "CREATE INDEX IF NOT EXISTS idx_articles_source_created ON articles(source, created_at DESC)",
                    "CREATE INDEX IF NOT EXISTS idx_articles_category_created ON articles(category, created_at DESC)",
                    "CREATE INDEX IF NOT EXISTS idx_articles_saved_created ON articles(is_saved, created_at DESC)",
                    "CREATE INDEX IF NOT EXISTS idx_articles_read_created ON articles(is_read, created_at DESC)",
                ]
                for idx in indexes:
                    cursor.execute(idx)

            conn.commit()

    # ──────────────────────────────────────────────
    # Helpers for cross-DB compatibility
    # ──────────────────────────────────────────────

    def _ph(self, n: int) -> str:
        """Return n parameter placeholders for current DB."""
        return ','.join(['%s'] * n) if self._use_postgres else ','.join(['?'] * n)

    def _ph_one(self) -> str:
        """Return single parameter placeholder for current DB."""
        return '%s' if self._use_postgres else '?'

    def _cast_int(self, col: str) -> str:
        return f"CAST({col} AS INTEGER)" if self._use_postgres else f"CAST({col} AS INTEGER)"

    def _date_trunc_day(self, col: str) -> str:
        if self._use_postgres:
            return f"DATE(to_timestamp({col}))"
        return f"date({col}, 'unixepoch')"

    def _glob(self, col: str, pattern: str) -> str:
        if self._use_postgres:
            return f"{col} ~ '{pattern}'"
        return f"{col} GLOB '{pattern}'"

    # ──────────────────────────────────────────────
    # CRUD Operations
    # ──────────────────────────────────────────────

    def add_article(self, article: Dict[str, Any]) -> None:
        """Adds a single article to the database."""
        self.add_articles([article])

    def add_articles(self, articles: List[Dict[str, Any]]) -> None:
        """Batch insert articles in a single transaction for performance."""
        if not articles:
            return
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                ph = self._ph_one()
                cursor.executemany(f'''
                    INSERT INTO articles
                    (title, link, score, author, time_posted, comments, source, created_at,
                     is_saved, is_read, sentiment, sentiment_score, category, read_time,
                     metadata_processed_at, excerpt, image_url, dek, bullets)
                    VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph},
                            0, 0, 'neutral', 0.0, 'general', 0, NULL, {ph}, {ph}, {ph}, {ph})
                    ON CONFLICT (link) DO NOTHING
                ''', [
                    (
                        a.get('title'), a.get('link'), a.get('score', 0),
                        a.get('author', 'Unknown'), a.get('time', 'Unknown'),
                        a.get('comments', '0'), a.get('source', 'Unknown'),
                        time.time(),
                        a.get('excerpt', ''),
                        a.get('image_url', ''),
                        a.get('dek', ''),
                        json.dumps(a.get('bullets', []) or [], ensure_ascii=False),
                    )
                    for a in articles
                ])
                conn.commit()
                logger.info(f"Batch inserted {len(articles)} articles (duplicates ignored).")
            except Exception as e:
                logger.error(f"DB error during batch insert: {e}")

    def upsert_images(self, articles: List[Dict[str, Any]]) -> None:
        """Update image_url for articles that have it but the DB row doesn't."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            ph = self._ph_one()
            updates = [(a['image_url'], a['link']) for a in articles if a.get('image_url')]
            if updates:
                cursor.executemany(
                    f"UPDATE articles SET image_url = {ph} WHERE link = {ph} AND image_url = ''",
                    updates
                )
                conn.commit()
                logger.info(f"Enriched {cursor.rowcount} article images in DB.")

    # ──────────────────────────────────────────────
    # Query Operations (with pagination)
    # ──────────────────────────────────────────────

    def get_articles(self, limit: int = 30, offset: int = 0, source_filter: str = 'all',
                     keyword: str = '', saved_only: bool = False,
                     unread_only: bool = False, category: str = '',
                     sort_by: str = 'newest') -> List[Dict[str, Any]]:
        """Retrieves articles with optional filtering and pagination."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            ph = self._ph_one()

            query = "SELECT * FROM articles WHERE 1=1"
            params: List[Any] = []

            if saved_only:
                query += " AND is_saved = 1"

            if unread_only:
                query += " AND is_read = 0"

            if source_filter and source_filter != 'all':
                query += f" AND source = {ph}"
                params.append(source_filter)

            if keyword:
                query += f" AND title ILIKE {ph}" if self._use_postgres else f" AND title LIKE {ph}"
                params.append(f"%{keyword}%")

            if category and category != 'all':
                query += f" AND category = {ph}"
                params.append(category)

            order_by = "created_at DESC"
            sort_key = (sort_by or 'newest').lower()
            if sort_key == 'score':
                order_by = f"{self._cast_int('score')} DESC, created_at DESC"
            elif sort_key == 'comments':
                if self._use_postgres:
                    order_by = f"CASE WHEN {self._glob('comments', r'^\d+$')} THEN {self._cast_int('comments')} ELSE 0 END DESC, created_at DESC"
                else:
                    order_by = (
                        f"CASE WHEN {self._glob('comments', '[0-9]*')} THEN {self._cast_int('comments')} "
                        f"ELSE 0 END DESC, created_at DESC"
                    )

            query += f" ORDER BY {order_by} LIMIT {ph} OFFSET {ph}"
            params.extend([limit, offset])

            cursor.execute(query, params)
            rows = cursor.fetchall()

            results = []
            for row in rows:
                d = self._row_to_dict(cursor, row)
                d['time'] = d['time_posted']
                # parse bullets JSON
                try:
                    b = d.get('bullets')
                    if isinstance(b, str):
                        d['bullets'] = json.loads(b) if b else []
                    elif b is None:
                        d['bullets'] = []
                except Exception:
                    d['bullets'] = []
                results.append(d)

            return results

    def get_total_count(self, source_filter: str = 'all', keyword: str = '',
                        saved_only: bool = False, category: str = '') -> int:
        """Returns total article count for pagination calculation."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            ph = self._ph_one()
            query = "SELECT COUNT(*) FROM articles WHERE 1=1"
            params: List[Any] = []

            if saved_only:
                query += " AND is_saved = 1"
            if source_filter and source_filter != 'all':
                query += f" AND source = {ph}"
                params.append(source_filter)
            if keyword:
                query += f" AND title ILIKE {ph}" if self._use_postgres else f" AND title LIKE {ph}"
                params.append(f"%{keyword}%")
            if category and category != 'all':
                query += f" AND category = {ph}"
                params.append(category)

            cursor.execute(query, params)
            return self._fetch_scalar(cursor)

    # ──────────────────────────────────────────────
    # Full-Text Search
    # ──────────────────────────────────────────────

    def _sanitize_fts_query(self, query: str) -> str:
        """Escape FTS5 special syntax to prevent injection/errors."""
        # Remove FTS5 operators and quote the query as phrase tokens
        # ponytail: naive quoting is safer than full FTS parser; upgrade to fts5 tokeniser if needed
        cleaned = re.sub(r'[\"\*\(\)\:\^\-]', ' ', query)
        cleaned = re.sub(r'\b(AND|OR|NOT|NEAR)\b', ' ', cleaned, flags=re.IGNORECASE)
        tokens = [t for t in re.findall(r'[a-zA-Z0-9]+', cleaned) if len(t) >= 2]
        if not tokens:
            return ''
        # Join as OR phrase for broader recall
        return ' OR '.join(f'"{t}"' for t in tokens[:10])

    def search_articles(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Full-text search using FTS5 (SQLite) or ILIKE (PostgreSQL)."""
        if not query or not query.strip():
            return []
        # ILIKE requires escaping % and _ wildcards
        query_escaped = query.replace('%', r'\%').replace('_', r'\_')
        with self.get_connection() as conn:
            cursor = conn.cursor()
            ph = self._ph_one()
            if self._use_postgres:
                # PostgreSQL: use ILIKE across multiple columns
                cursor.execute(f'''
                    SELECT * FROM articles
                    WHERE title ILIKE {ph} ESCAPE '\\' OR excerpt ILIKE {ph} ESCAPE '\\' OR author ILIKE {ph} ESCAPE '\\' OR source ILIKE {ph} ESCAPE '\\'
                    ORDER BY created_at DESC
                    LIMIT {ph}
                ''', (f"%{query_escaped}%", f"%{query_escaped}%", f"%{query_escaped}%", f"%{query_escaped}%", limit))
            else:
                fts_query = self._sanitize_fts_query(query)
                if not fts_query:
                    return self.get_articles(limit=limit, keyword=query, sort_by='newest')
                try:
                    cursor.execute('''
                        SELECT a.* FROM articles a
                        JOIN articles_fts fts ON a.id = fts.rowid
                        WHERE articles_fts MATCH ?
                        ORDER BY rank
                        LIMIT ?
                    ''', (fts_query, limit))
                except sqlite3.OperationalError as e:
                    logger.warning(f"FTS search error: {e}")
                    return self.get_articles(limit=limit, keyword=query_escaped, sort_by='newest')

            rows = cursor.fetchall()
            results = []
            for row in rows:
                d = self._row_to_dict(cursor, row)
                d['time'] = d['time_posted']
                try:
                    b = d.get('bullets')
                    d['bullets'] = json.loads(b) if isinstance(b, str) and b else (b or [])
                except Exception:
                    d['bullets'] = []
                results.append(d)
            return results

    # ──────────────────────────────────────────────
    # Bookmarks & Reading List
    # ──────────────────────────────────────────────

    def toggle_bookmark(self, article_id: int) -> Optional[bool]:
        """Toggles the bookmark status of an article."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            ph = self._ph_one()
            cursor.execute(f"SELECT is_saved FROM articles WHERE id = {ph}", (article_id,))
            result = cursor.fetchone()

            if not result:
                return None

            current_status = result['is_saved']
            new_status = not current_status
            cursor.execute(f"UPDATE articles SET is_saved = {ph} WHERE id = {ph}", (int(new_status), article_id))
            conn.commit()

            return bool(new_status)

    def toggle_read(self, article_id: int) -> Optional[bool]:
        """Toggles the read status of an article."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            ph = self._ph_one()
            cursor.execute(f"SELECT is_read FROM articles WHERE id = {ph}", (article_id,))
            result = cursor.fetchone()

            if not result:
                return None

            current_status = result['is_read']
            new_status = not current_status
            cursor.execute(f"UPDATE articles SET is_read = {ph} WHERE id = {ph}", (int(new_status), article_id))
            conn.commit()

            return bool(new_status)

    # ──────────────────────────────────────────────
    # Sentiment & Category Updates
    # ──────────────────────────────────────────────

    def update_article_metadata(self, article_id: int, sentiment: str = None,
                                 sentiment_score: float = None, category: str = None,
                                 read_time: int = None,
                                 metadata_processed_at: float = None) -> None:
        """Updates article metadata (sentiment, category, read_time)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            ph = self._ph_one()
            updates = []
            params = []

            if sentiment is not None:
                updates.append(f"sentiment = {ph}")
                params.append(sentiment)
            if sentiment_score is not None:
                updates.append(f"sentiment_score = {ph}")
                params.append(sentiment_score)
            if category is not None:
                updates.append(f"category = {ph}")
                params.append(category)
            if read_time is not None:
                updates.append(f"read_time = {ph}")
                params.append(read_time)
            if metadata_processed_at is not None:
                updates.append(f"metadata_processed_at = {ph}")
                params.append(metadata_processed_at)

            if updates:
                params.append(article_id)
                cursor.execute(f"UPDATE articles SET {', '.join(updates)} WHERE id = {ph}", params)
                conn.commit()

    def get_unprocessed_articles(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Gets articles that haven't been processed for sentiment/category yet."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            ph = self._ph_one()
            cursor.execute(f'''
                SELECT * FROM articles
                WHERE metadata_processed_at IS NULL
                ORDER BY created_at DESC LIMIT {ph}
            ''', (limit,))
            rows = cursor.fetchall()
            return [self._row_to_dict(cursor, row) for row in rows]

    # ──────────────────────────────────────────────
    # Statistics & Analytics
    # ──────────────────────────────────────────────

    def get_article_count(self) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM articles")
            return self._fetch_scalar(cursor)

    def get_stats(self) -> Dict[str, Any]:
        """Returns statistics about articles in the database."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM articles")
            total = self._fetch_scalar(cursor)

            twenty_four_hours_ago = time.time() - (24 * 60 * 60)
            ph = self._ph_one()
            cursor.execute(f"SELECT COUNT(*) FROM articles WHERE created_at >= {ph}", (twenty_four_hours_ago,))
            today = self._fetch_scalar(cursor)

            cursor.execute("SELECT COUNT(*) FROM articles WHERE is_saved = 1")
            saved = self._fetch_scalar(cursor)

            cursor.execute("SELECT COUNT(*) FROM articles WHERE is_read = 1")
            read_count = self._fetch_scalar(cursor)

            cursor.execute("SELECT source, COUNT(*) as count FROM articles GROUP BY source")
            by_source_rows = cursor.fetchall()
            by_source = {row['source']: row['count'] for row in by_source_rows}

            cursor.execute("SELECT category, COUNT(*) as count FROM articles GROUP BY category ORDER BY count DESC")
            by_category_rows = cursor.fetchall()
            by_category = {row['category']: row['count'] for row in by_category_rows}

            # Sentiment breakdown
            cursor.execute("SELECT sentiment, COUNT(*) as count FROM articles GROUP BY sentiment")
            by_sentiment_rows = cursor.fetchall()
            by_sentiment = {row['sentiment']: row['count'] for row in by_sentiment_rows}

            return {
                'total': total,
                'today': today,
                'saved': saved,
                'read': read_count,
                'by_source': by_source,
                'by_category': by_category,
                'by_sentiment': by_sentiment
            }

    def get_trending_words(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Returns most frequent meaningful words from recent article titles."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            twenty_four_hours_ago = time.time() - (24 * 60 * 60)
            ph = self._ph_one()
            cursor.execute(
                f"SELECT title FROM articles WHERE created_at >= {ph}",
                (twenty_four_hours_ago,)
            )
            rows = cursor.fetchall()
            return [self._row_to_dict(cursor, row) for row in rows]

    def get_articles_per_day(self, days: int = 7) -> List[Dict[str, Any]]:
        """Returns article counts grouped by day for the chart."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cutoff = time.time() - (days * 24 * 60 * 60)
            ph = self._ph_one()
            date_fn = self._date_trunc_day('created_at')
            cursor.execute(f'''
                SELECT {date_fn} as day, COUNT(*) as count
                FROM articles
                WHERE created_at >= {ph}
                GROUP BY day
                ORDER BY day ASC
            ''', (cutoff,))
            rows = cursor.fetchall()
            return [{'day': row['day'], 'count': row['count']} for row in rows]

    def get_personalized_feed(self, limit: int = 30) -> List[Dict[str, Any]]:
        """Returns articles boosted by user preferences (based on bookmarked sources/categories)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            ph = self._ph_one()

            # Find user's preferred sources and categories from bookmarks
            cursor.execute(f'''
                SELECT source, COUNT(*) as cnt FROM articles
                WHERE is_saved = 1 GROUP BY source ORDER BY cnt DESC LIMIT 3
            ''')
            preferred_sources = [row['source'] for row in cursor.fetchall()]

            cursor.execute(f'''
                SELECT category, COUNT(*) as cnt FROM articles
                WHERE is_saved = 1 GROUP BY category ORDER BY cnt DESC LIMIT 3
            ''')
            preferred_categories = [row['category'] for row in cursor.fetchall()]

            if not preferred_sources and not preferred_categories:
                # No preferences yet, return recent articles
                return self.get_articles(limit=limit)

            # Build a scoring query that boosts preferred content (avoid IN () when list empty)
            if preferred_sources and preferred_categories:
                placeholders_src = self._ph(len(preferred_sources))
                placeholders_cat = self._ph(len(preferred_categories))
                query = f'''
                    SELECT *,
                        (CASE WHEN source IN ({placeholders_src}) THEN 2 ELSE 0 END +
                          CASE WHEN category IN ({placeholders_cat}) THEN 1 ELSE 0 END) as relevance_score
                    FROM articles
                    ORDER BY relevance_score DESC, created_at DESC
                    LIMIT {ph}
                '''
                params = preferred_sources + preferred_categories + [limit]
            elif preferred_sources:
                placeholders_src = self._ph(len(preferred_sources))
                query = f'''
                    SELECT *,
                        (CASE WHEN source IN ({placeholders_src}) THEN 2 ELSE 0 END) as relevance_score
                    FROM articles
                    ORDER BY relevance_score DESC, created_at DESC
                    LIMIT {ph}
                '''
                params = preferred_sources + [limit]
            else:
                placeholders_cat = self._ph(len(preferred_categories))
                query = f'''
                    SELECT *,
                        (CASE WHEN category IN ({placeholders_cat}) THEN 1 ELSE 0 END) as relevance_score
                    FROM articles
                    ORDER BY relevance_score DESC, created_at DESC
                    LIMIT {ph}
                '''
                params = preferred_categories + [limit]
            cursor.execute(query, params)
            rows = cursor.fetchall()

            results = []
            for row in rows:
                d = self._row_to_dict(cursor, row)
                d['time'] = d['time_posted']
                try:
                    b = d.get('bullets')
                    d['bullets'] = json.loads(b) if isinstance(b, str) and b else (b or [])
                except Exception:
                    d['bullets'] = []
                results.append(d)
            return results

    # ──────────────────────────────────────────────
    # Export
    # ──────────────────────────────────────────────

    def export_bookmarks_json(self) -> str:
        """Exports bookmarked articles as JSON string."""
        articles = self.get_articles(limit=1000, saved_only=True)
        export_data = []
        for a in articles:
            export_data.append({
                'title': a.get('title'),
                'link': a.get('link'),
                'source': a.get('source'),
                'author': a.get('author'),
                'score': a.get('score'),
                'category': a.get('category'),
                'sentiment': a.get('sentiment'),
                'saved_at': a.get('created_at')
            })
        return json.dumps(export_data, indent=2)

    def export_bookmarks_markdown(self) -> str:
        """Exports bookmarked articles as Markdown string."""
        articles = self.get_articles(limit=1000, saved_only=True)
        lines = ["# Saved Articles\n"]
        # Group by source
        by_source: Dict[str, list] = {}
        for a in articles:
            src = a.get('source', 'Other')
            by_source.setdefault(src, []).append(a)

        for source, arts in by_source.items():
            lines.append(f"\n## {source}\n")
            for a in arts:
                lines.append(f"- [{a.get('title')}]({a.get('link')})")

        return '\n'.join(lines)
