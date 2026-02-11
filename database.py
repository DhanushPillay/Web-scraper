"""
Database Module — Tech News Aggregator
SQLite with FTS5 full-text search, sentiment/category columns,
pagination, reading list, and export features.
"""
import sqlite3
import time
import json
import logging
from contextlib import contextmanager
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_name: str = "technews.db") -> None:
        self.db_name = db_name
        self.init_db()

    @contextmanager
    def get_connection(self):
        """Context manager that auto-closes the DB connection."""
        conn = sqlite3.connect(self.db_name)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def init_db(self) -> None:
        """Initializes the database table and ensures schema is up to date."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # 1. Create main articles table
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
                    read_time INTEGER DEFAULT 0
                )
            ''')

            # 2. Migrations: add columns if they don't exist (idempotent)
            migrations = [
                ("is_saved", "INTEGER DEFAULT 0"),
                ("is_read", "INTEGER DEFAULT 0"),
                ("sentiment", "TEXT DEFAULT 'neutral'"),
                ("sentiment_score", "REAL DEFAULT 0.0"),
                ("category", "TEXT DEFAULT 'general'"),
                ("read_time", "INTEGER DEFAULT 0"),
            ]
            for col_name, col_type in migrations:
                try:
                    cursor.execute(f"SELECT {col_name} FROM articles LIMIT 1")
                except sqlite3.OperationalError:
                    logger.info(f"Migrating DB: Adding '{col_name}' column...")
                    cursor.execute(f"ALTER TABLE articles ADD COLUMN {col_name} {col_type}")

            # 3. Create FTS5 virtual table for full-text search
            cursor.execute('''
                CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
                    title, author, source,
                    content='articles',
                    content_rowid='id'
                )
            ''')

            # 4. Create triggers to keep FTS in sync
            cursor.execute('''
                CREATE TRIGGER IF NOT EXISTS articles_ai AFTER INSERT ON articles BEGIN
                    INSERT INTO articles_fts(rowid, title, author, source)
                    VALUES (new.id, new.title, new.author, new.source);
                END
            ''')
            cursor.execute('''
                CREATE TRIGGER IF NOT EXISTS articles_ad AFTER DELETE ON articles BEGIN
                    INSERT INTO articles_fts(articles_fts, rowid, title, author, source)
                    VALUES ('delete', old.id, old.title, old.author, old.source);
                END
            ''')
            cursor.execute('''
                CREATE TRIGGER IF NOT EXISTS articles_au AFTER UPDATE ON articles BEGIN
                    INSERT INTO articles_fts(articles_fts, rowid, title, author, source)
                    VALUES ('delete', old.id, old.title, old.author, old.source);
                    INSERT INTO articles_fts(rowid, title, author, source)
                    VALUES (new.id, new.title, new.author, new.source);
                END
            ''')

            conn.commit()

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
                cursor.executemany('''
                    INSERT OR IGNORE INTO articles
                    (title, link, score, author, time_posted, comments, source, created_at,
                     is_saved, is_read, sentiment, sentiment_score, category, read_time)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 'neutral', 0.0, 'general', 0)
                ''', [
                    (
                        a.get('title'), a.get('link'), a.get('score', 0),
                        a.get('author', 'Unknown'), a.get('time', 'Unknown'),
                        a.get('comments', '0'), a.get('source', 'Unknown'),
                        time.time()
                    )
                    for a in articles
                ])
                conn.commit()
                logger.info(f"Batch inserted {len(articles)} articles (duplicates ignored).")
            except sqlite3.IntegrityError as e:
                logger.warning(f"Integrity error during batch insert: {e}")
            except sqlite3.OperationalError as e:
                logger.error(f"DB operational error during batch insert: {e}")

    # ──────────────────────────────────────────────
    # Query Operations (with pagination)
    # ──────────────────────────────────────────────

    def get_articles(self, limit: int = 30, offset: int = 0, source_filter: str = 'all',
                     keyword: str = '', saved_only: bool = False,
                     unread_only: bool = False, category: str = '') -> List[Dict[str, Any]]:
        """Retrieves articles with optional filtering and pagination."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            query = "SELECT * FROM articles WHERE 1=1"
            params: List[Any] = []

            if saved_only:
                query += " AND is_saved = 1"

            if unread_only:
                query += " AND is_read = 0"

            if source_filter and source_filter != 'all':
                query += " AND source = ?"
                params.append(source_filter)

            if keyword:
                query += " AND title LIKE ?"
                params.append(f"%{keyword}%")

            if category and category != 'all':
                query += " AND category = ?"
                params.append(category)

            query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cursor.execute(query, params)
            rows = cursor.fetchall()

            results = []
            for row in rows:
                d = dict(row)
                d['time'] = d['time_posted']
                results.append(d)

            return results

    def get_total_count(self, source_filter: str = 'all', keyword: str = '',
                        saved_only: bool = False, category: str = '') -> int:
        """Returns total article count for pagination calculation."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT COUNT(*) FROM articles WHERE 1=1"
            params: List[Any] = []

            if saved_only:
                query += " AND is_saved = 1"
            if source_filter and source_filter != 'all':
                query += " AND source = ?"
                params.append(source_filter)
            if keyword:
                query += " AND title LIKE ?"
                params.append(f"%{keyword}%")
            if category and category != 'all':
                query += " AND category = ?"
                params.append(category)

            cursor.execute(query, params)
            return cursor.fetchone()[0]

    # ──────────────────────────────────────────────
    # Full-Text Search
    # ──────────────────────────────────────────────

    def search_articles(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Full-text search using FTS5."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute('''
                    SELECT a.* FROM articles a
                    JOIN articles_fts fts ON a.id = fts.rowid
                    WHERE articles_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                ''', (query, limit))
                rows = cursor.fetchall()
                results = []
                for row in rows:
                    d = dict(row)
                    d['time'] = d['time_posted']
                    results.append(d)
                return results
            except sqlite3.OperationalError as e:
                logger.warning(f"FTS search error: {e}")
                # Fallback to LIKE search
                return self.get_articles(limit=limit, keyword=query)

    # ──────────────────────────────────────────────
    # Bookmarks & Reading List
    # ──────────────────────────────────────────────

    def toggle_bookmark(self, article_id: int) -> bool:
        """Toggles the bookmark status of an article."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT is_saved FROM articles WHERE id = ?", (article_id,))
            result = cursor.fetchone()

            new_status = False
            if result:
                current_status = result['is_saved']
                new_status = not current_status
                cursor.execute("UPDATE articles SET is_saved = ? WHERE id = ?", (int(new_status), article_id))
                conn.commit()

            return new_status

    def toggle_read(self, article_id: int) -> bool:
        """Toggles the read status of an article."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT is_read FROM articles WHERE id = ?", (article_id,))
            result = cursor.fetchone()

            new_status = False
            if result:
                current_status = result['is_read']
                new_status = not current_status
                cursor.execute("UPDATE articles SET is_read = ? WHERE id = ?", (int(new_status), article_id))
                conn.commit()

            return new_status

    # ──────────────────────────────────────────────
    # Sentiment & Category Updates
    # ──────────────────────────────────────────────

    def update_article_metadata(self, article_id: int, sentiment: str = None,
                                 sentiment_score: float = None, category: str = None,
                                 read_time: int = None) -> None:
        """Updates article metadata (sentiment, category, read_time)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            updates = []
            params = []

            if sentiment is not None:
                updates.append("sentiment = ?")
                params.append(sentiment)
            if sentiment_score is not None:
                updates.append("sentiment_score = ?")
                params.append(sentiment_score)
            if category is not None:
                updates.append("category = ?")
                params.append(category)
            if read_time is not None:
                updates.append("read_time = ?")
                params.append(read_time)

            if updates:
                params.append(article_id)
                cursor.execute(f"UPDATE articles SET {', '.join(updates)} WHERE id = ?", params)
                conn.commit()

    def get_unprocessed_articles(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Gets articles that haven't been processed for sentiment/category yet."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM articles
                WHERE sentiment = 'neutral' AND category = 'general'
                ORDER BY created_at DESC LIMIT ?
            ''', (limit,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    # ──────────────────────────────────────────────
    # Statistics & Analytics
    # ──────────────────────────────────────────────

    def get_article_count(self) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM articles")
            return cursor.fetchone()[0]

    def get_stats(self) -> Dict[str, Any]:
        """Returns statistics about articles in the database."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM articles")
            total = cursor.fetchone()[0]

            twenty_four_hours_ago = time.time() - (24 * 60 * 60)
            cursor.execute("SELECT COUNT(*) FROM articles WHERE created_at >= ?", (twenty_four_hours_ago,))
            today = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM articles WHERE is_saved = 1")
            saved = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM articles WHERE is_read = 1")
            read_count = cursor.fetchone()[0]

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
            cursor.execute(
                "SELECT title FROM articles WHERE created_at >= ?",
                (twenty_four_hours_ago,)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_articles_per_day(self, days: int = 7) -> List[Dict[str, Any]]:
        """Returns article counts grouped by day for the chart."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cutoff = time.time() - (days * 24 * 60 * 60)
            cursor.execute('''
                SELECT date(created_at, 'unixepoch') as day, COUNT(*) as count
                FROM articles
                WHERE created_at >= ?
                GROUP BY day
                ORDER BY day ASC
            ''', (cutoff,))
            rows = cursor.fetchall()
            return [{'day': row['day'], 'count': row['count']} for row in rows]

    def get_personalized_feed(self, limit: int = 30) -> List[Dict[str, Any]]:
        """Returns articles boosted by user preferences (based on bookmarked sources/categories)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Find user's preferred sources and categories from bookmarks
            cursor.execute('''
                SELECT source, COUNT(*) as cnt FROM articles
                WHERE is_saved = 1 GROUP BY source ORDER BY cnt DESC LIMIT 3
            ''')
            preferred_sources = [row['source'] for row in cursor.fetchall()]

            cursor.execute('''
                SELECT category, COUNT(*) as cnt FROM articles
                WHERE is_saved = 1 GROUP BY category ORDER BY cnt DESC LIMIT 3
            ''')
            preferred_categories = [row['category'] for row in cursor.fetchall()]

            if not preferred_sources and not preferred_categories:
                # No preferences yet, return recent articles
                return self.get_articles(limit=limit)

            # Build a scoring query that boosts preferred content
            # Articles from preferred sources/categories are scored higher
            placeholders_src = ','.join(['?' for _ in preferred_sources])
            placeholders_cat = ','.join(['?' for _ in preferred_categories])

            query = f'''
                SELECT *,
                    (CASE WHEN source IN ({placeholders_src}) THEN 2 ELSE 0 END +
                     CASE WHEN category IN ({placeholders_cat}) THEN 1 ELSE 0 END) as relevance_score
                FROM articles
                ORDER BY relevance_score DESC, created_at DESC
                LIMIT ?
            '''
            params = preferred_sources + preferred_categories + [limit]
            cursor.execute(query, params)
            rows = cursor.fetchall()

            results = []
            for row in rows:
                d = dict(row)
                d['time'] = d['time_posted']
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
