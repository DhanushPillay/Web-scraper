"""
Database Module — Sniffer
SQLite with FTS5 full-text search, sentiment/category columns,
pagination, reading list, and export features.
Supports both SQLite (local) and PostgreSQL (production).
"""
import json
import logging
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)


class Database:
    # Must be >= the per-worker gunicorn thread count (render.yaml: --threads 4).
    PG_POOL_MIN = int(os.getenv("SNIFFER_PG_POOL_MIN", "4"))
    PG_POOL_MAX = int(os.getenv("SNIFFER_PG_POOL_MAX", "10"))

    def __init__(self, db_name: str = "sniffer.db") -> None:
        self.db_name = db_name
        self._use_postgres = bool(os.getenv("DATABASE_URL"))
        self._pg_pool = None
        self._pool_pid = None

        if self._use_postgres:
            for attempt in range(1, 4):
                try:
                    self._init_pg_pool()
                    # Test-only connection: close immediately so no live
                    # socket survives a gunicorn fork into workers (shared
                    # sockets surface as `SSL: decryption failed` errors).
                    conn = self._pg_pool.getconn()
                    conn.close()
                    self._reset_pg_pool()
                    break
                except Exception as e:
                    if attempt < 3:
                        logger.warning(f"PostgreSQL connection failed (attempt {attempt}): {e}. Retrying in {2 ** attempt}s...")
                        time.sleep(2 ** attempt)
                        # Reset pool for next attempt
                        if self._pg_pool:
                            try:
                                self._pg_pool.closeall()
                            except Exception as close_err:
                                # Already tearing down a dead pool; nothing left to salvage
                                logger.debug(f"closeall() during retry failed: {close_err}")
                        self._pg_pool = None
                    else:
                        if self._pg_pool:
                            try:
                                self._pg_pool.closeall()
                            except Exception as close_err:
                                logger.debug(f"closeall() on failed pool failed: {close_err}")
                        self._pg_pool = None
                        if os.getenv("SNIFFER_REQUIRE_POSTGRES") == "1":
                            raise RuntimeError(
                                f"SNIFFER_REQUIRE_POSTGRES=1 but PostgreSQL unreachable: {e}") from e
                        logger.error(f"PostgreSQL connection failed after 3 attempts: {e}. Falling back to SQLite WAL mode.")
                        self._use_postgres = False

        self.init_db()

    @staticmethod
    def _normalize_dsn(dsn: str) -> str:
        """Normalizes DATABASE_URL for psycopg2 on Neon."""
        if dsn.startswith("postgres://"):
            dsn = dsn.replace("postgres://", "postgresql://", 1)
        # Neon PgBouncer (-pooler) + psycopg2 + channel_binding=require is
        # flaky through transaction pooling; `prefer` keeps TLS
        # (sslmode=require untouched) without hard-failing the handshake.
        if "-pooler" in dsn and "channel_binding=require" in dsn:
            dsn = dsn.replace("channel_binding=require", "channel_binding=prefer")
        if "connect_timeout" not in dsn:
            dsn += ("&" if "?" in dsn else "?") + "connect_timeout=10"
        return dsn

    def _init_pg_pool(self) -> None:
        """Initializes the PostgreSQL connection pool."""
        if self._pg_pool is None:
            from psycopg2.extras import RealDictCursor
            from psycopg2.pool import ThreadedConnectionPool
            dsn = self._normalize_dsn(os.getenv("DATABASE_URL", "").strip())
            # All query methods use mapping-style row access (row['title']) or
            # convert rows with dict(row).  PostgreSQL cursors return tuples by
            # default, unlike SQLite's Row objects, so use dictionary cursors
            # consistently for both backends.
            # minconn must cover this worker's thread count.  psycopg2's
            # _putconn only recycles a connection back into the pool while
            # len(pool) < minconn, so minconn=1 made ~90% of returns at
            # --threads 4 close instead — a fresh TCP+TLS handshake to Neon on
            # nearly every request, defeating the keepalives below.
            self._pg_pool = ThreadedConnectionPool(
                self.PG_POOL_MIN, self.PG_POOL_MAX, dsn, cursor_factory=RealDictCursor,
                keepalives=1, keepalives_idle=30,
                keepalives_interval=10, keepalives_count=5,
            )
            self._pool_pid = os.getpid()

    def _reset_pg_pool(self) -> None:
        """Drops all pooled connections so the next request reconnects fresh."""
        if self._pg_pool is not None:
            try:
                self._pg_pool.closeall()
            except Exception as close_err:
                # The pool is already being discarded; a failure here changes nothing
                logger.debug(f"closeall() in _reset_pg_pool failed: {close_err}")
        self._pg_pool = None
        self._pool_pid = None

    def _is_pg_conn_error(self, e: Exception) -> bool:
        """True for stale/broken connection errors (safe to discard the pool).

        Keyed on the exception class, not substrings: a QueryCanceled carrying
        the word "timeout" is a statement-level error, and discarding the pool
        for it drops warm connections for every in-flight thread, while
        InterfaceError ("cursor already closed") matches no substring and
        returns a dead connection to the pool.
        """
        try:
            import psycopg2
        except ImportError:
            return False
        return isinstance(e, (psycopg2.OperationalError, psycopg2.InterfaceError))

    @contextmanager
    def get_connection(self):
        """Context manager that auto-closes the DB connection with automatic fallback."""
        was_postgres = self._use_postgres
        if self._use_postgres:
            # Gunicorn forks workers after import: a pool inherited across
            # processes shares sockets and breaks SSL. Reset on PID change.
            if self._pg_pool is not None and self._pool_pid != os.getpid():
                self._reset_pg_pool()
            try:
                if self._pg_pool is None:
                    self._init_pg_pool()
                conn = self._pg_pool.getconn()
            except Exception as e:
                if os.getenv("SNIFFER_REQUIRE_POSTGRES") == "1":
                    raise RuntimeError(
                        f"SNIFFER_REQUIRE_POSTGRES=1 but PostgreSQL unreachable: {e}") from e
                # Per-request fallback only.  Persisting _use_postgres = False
                # pinned this worker to a local SQLite file for the life of the
                # process after a single transient failure, while its sibling
                # gunicorn worker kept using Postgres.  The downgrade is local
                # so placeholder generation still matches the connection the
                # caller actually receives.
                logger.error(
                    f"PostgreSQL connection error: {e}. Using SQLite for this request.")
                self._reset_pg_pool()
                self._use_postgres = False
                try:
                    with self._sqlite_connection() as sqlite_conn:
                        yield sqlite_conn
                finally:
                    self._use_postgres = was_postgres
                return
            else:
                # Only connection-acquisition failures should fall back to
                # SQLite.  SQL errors need to surface to the caller; treating
                # them as connection failures masks the real problem.
                conn.autocommit = False
                try:
                    yield conn
                    conn.commit()
                except Exception as e:
                    try:
                        conn.rollback()
                    except Exception as rollback_err:
                        # A failed rollback means the connection is already dead
                        logger.debug(f"rollback() on failed connection raised: {rollback_err}")
                    # Stale/killed connections (e.g. gunicorn SIGKILL + Neon
                    # pooler) must not go back into the pool — discard the
                    # whole pool so the next request reconnects fresh.
                    if self._is_pg_conn_error(e):
                        logger.error(f"PostgreSQL connection lost mid-query: {e}. Resetting pool.")
                        try:
                            conn.close()
                        except Exception as close_err:
                            logger.debug(f"close() on dead connection raised: {close_err}")
                        self._reset_pg_pool()
                    raise
                finally:
                    if self._pg_pool is not None:
                        try:
                            self._pg_pool.putconn(conn)
                        except Exception:
                            self._reset_pg_pool()
                return

        with self._sqlite_connection() as conn:
            yield conn

    @contextmanager
    def _sqlite_connection(self):
        """SQLite connection with the pragmas the read/write paths assume."""
        conn = sqlite3.connect(self.db_name, timeout=15)
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _row_to_dict(self, cursor, row) -> dict[str, Any]:
        """Safely converts a database row to a dictionary."""
        if hasattr(row, 'keys'):
            try:
                return dict(row)
            except (TypeError, ValueError):
                # RealDictRow refused: fall through to the positional path below
                pass
        cols = [col[0] for col in cursor.description]
        return dict(zip(cols, row))

    def _fetch_scalar(self, cursor) -> Any:
        """First column of next row (None if empty). Works for Row tuples and RealDict rows."""
        row = cursor.fetchone()
        if row is None:
            return None
        try:
            return row[0]
        except (TypeError, IndexError, KeyError):
            values = list(self._row_to_dict(cursor, row).values())
            return values[0] if values else None

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
                        -- DOUBLE PRECISION, not REAL: PG's REAL is float4, whose
                        -- 24-bit mantissa quantises epoch ~1.79e9 to 128s steps.
                        created_at DOUBLE PRECISION,
                        is_saved INTEGER DEFAULT 0,
                        is_read INTEGER DEFAULT 0,
                        sentiment TEXT DEFAULT 'neutral',
                        sentiment_score REAL DEFAULT 0.0,
                        category TEXT DEFAULT 'general',
                        read_time INTEGER DEFAULT 0,
                        metadata_processed_at DOUBLE PRECISION,
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

                # PG has no FTS5. search_articles falls back to ILIKE, but a
                # leading-wildcard LIKE cannot use a btree index and the
                # four-column OR chain is a guaranteed sequential scan. The
                # real fix is pg_trgm GIN indexes:
                #   CREATE EXTENSION pg_trgm;
                #   CREATE INDEX ... ON articles USING gin (title gin_trgm_ops);
                # Not applied automatically: CREATE EXTENSION needs superuser.
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

                # CREATE ... IF NOT EXISTS never rescans existing rows, so an
                # install that predates the triggers (or any row written while a
                # trigger was missing) sits in `articles` but is invisible to
                # search_articles forever. Rebuild when the index is short.
                cursor.execute("SELECT COUNT(*) FROM articles")
                article_count = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(*) FROM articles_fts")
                fts_count = cursor.fetchone()[0]
                if article_count and fts_count < article_count:
                    logger.info(
                        f"FTS index behind ({fts_count}/{article_count}); rebuilding.")
                    cursor.execute(
                        "INSERT INTO articles_fts(articles_fts) SELECT 'rebuild'")

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

    def _ph(self, n: int) -> str:
        """Return n parameter placeholders for current DB."""
        return ','.join(['%s'] * n) if self._use_postgres else ','.join(['?'] * n)

    def _cast_int(self, col: str) -> str:
        return f"CAST({col} AS INTEGER)"

    @staticmethod
    def _escape_like(value: str) -> str:
        """Escape LIKE/ILIKE metacharacters so a user query is a literal.

        Without this, a search for `_` matches every row (and get_total_count
        agrees, so the pager also reports the wrong page count).
        """
        return value.replace('\\', '\\\\').replace('%', r'\%').replace('_', r'\_')

    def _like_clause(self, col: str, ph: str) -> str:
        op = 'ILIKE' if self._use_postgres else 'LIKE'
        return f" AND {col} {op} {ph} ESCAPE '\\'"

    def _comments_is_numeric(self) -> str:
        """Full-string numeric match for `comments`, identical on both backends."""
        if self._use_postgres:
            return "comments ~ '^[0-9]{1,18}$'"
        return "comments NOT GLOB '*[^0-9]*' AND comments GLOB '[0-9]*'"

    def add_articles(self, articles: list[dict[str, Any]]) -> tuple[int, int]:
        """Batch insert articles in a single transaction for performance.

        Returns (inserted, skipped): rows actually new vs. duplicate links.
        """
        if not articles:
            return (0, 0)
        # A row without a link can never satisfy `link TEXT UNIQUE NOT NULL`, and
        # its presence aborts the entire executemany. A row without a title only
        # passes NOT NULL as an empty string, which renders as a blank card.
        # Drop both explicitly and account for them as skipped, not inserted.
        unusable = [a for a in articles if not a.get('link') or not str(a.get('title') or '').strip()]
        if unusable:
            logger.warning(
                f"Skipping {len(unusable)} article(s) with no link or title: "
                f"{[(a.get('title'), a.get('link')) for a in unusable][:5]}"
            )
        articles = [a for a in articles if a.get('link') and str(a.get('title') or '').strip()]
        if not articles:
            return (0, 0)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                ph = self._ph(1)
                links = [a.get('link') for a in articles]
                existing = set()
                for i in range(0, len(links), 500):
                    chunk = links[i:i + 500]
                    cursor.execute(
                        f"SELECT link FROM articles WHERE link IN ({self._ph(len(chunk))})",
                        chunk,
                    )
                    for r in cursor.fetchall():
                        existing.add(r['link'] if isinstance(r, dict) else r[0])
                fresh = [a for a in articles if a['link'] not in existing]
                if fresh:
                    cursor.executemany(f'''
                        INSERT INTO articles
                        (title, link, score, author, time_posted, comments, source, created_at,
                         is_saved, is_read, sentiment, sentiment_score, category, read_time,
                         metadata_processed_at, excerpt, image_url, dek, bullets)
                        VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph},
                                0, 0, 'neutral', 0.0, {ph}, 0, NULL, {ph}, {ph}, {ph}, {ph})
                        ON CONFLICT (link) DO NOTHING
                    ''', [
                        (
                            (a.get('title') or 'Untitled'), a['link'], a.get('score', 0),
                            a.get('author', 'Unknown'), a.get('time', 'Unknown'),
                            a.get('comments', '0'), a.get('source', 'Unknown'),
                            time.time(),
                            (a.get('category') or 'General'),
                            (a.get('excerpt') or ''),
                            (a.get('image_url') or ''),
                            (a.get('dek') or ''),
                            json.dumps(a.get('bullets') or [], ensure_ascii=False),
                        )
                        for a in fresh
                    ])
                # rowcount is the only honest count: the pre-check SELECT above
                # cannot see another session's uncommitted rows, so under READ
                # COMMITTED a concurrent insert makes ON CONFLICT skip a row the
                # pre-check still counted as fresh.  psycopg2 and py3.12 sqlite3
                # both sum rowcount correctly across executemany.
                inserted = max(cursor.rowcount, 0)
                conn.commit()
                skipped = len(articles) - inserted + len(unusable)
                logger.info(f"Batch insert: {inserted} new, {skipped} skipped.")
                return (inserted, skipped)
            except Exception:
                # A failed insert must never masquerade as "all duplicates".
                logger.exception("DB error during batch insert")
                raise

    def upsert_images(self, articles: list[dict[str, Any]]) -> None:
        """Update image_url for articles that have it but the DB row doesn't."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            ph = self._ph(1)
            updates = [(a['image_url'], a['link']) for a in articles if a.get('image_url')]
            if updates:
                cursor.executemany(
                    f"UPDATE articles SET image_url = {ph} "
                    f"WHERE link = {ph} AND COALESCE(image_url, '') = ''",
                    updates
                )
                conn.commit()
                logger.info(f"Enriched {cursor.rowcount} article images in DB.")

    def prune_old_articles(self, max_age_days: int = 2) -> int:
        """Deletes non-saved articles older than max_age_days. Returns rows removed."""
        cutoff = time.time() - (max_age_days * 24 * 60 * 60)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            ph = self._ph(1)
            cursor.execute(
                f"DELETE FROM articles WHERE created_at < {ph} AND is_saved = 0",
                (cutoff,),
            )
            removed = max(cursor.rowcount or 0, 0)
            conn.commit()
            if removed:
                logger.info(f"Pruned {removed} articles older than {max_age_days}d.")
            return removed

    def _normalize_rows(self, cursor, rows) -> list[dict[str, Any]]:
        """Unifies backend row shapes into the dict shape templates expect."""
        results = []
        for row in rows:
            d = self._row_to_dict(cursor, row)
            d['time'] = d['time_posted']
            try:
                b = d.get('bullets')
                if isinstance(b, str):
                    d['bullets'] = json.loads(b) if b else []
                elif b is None:
                    d['bullets'] = []
            except (TypeError, ValueError):
                d['bullets'] = []
            results.append(d)
        return results

    def get_articles(self, limit: int = 30, offset: int = 0, source_filter: str = 'all',
                     keyword: str = '', saved_only: bool = False,
                     category: str = '',
                     sort_by: str = 'newest') -> list[dict[str, Any]]:
        """Retrieves articles with optional filtering and pagination."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            ph = self._ph(1)

            query = "SELECT * FROM articles WHERE 1=1"
            params: list[Any] = []

            if saved_only:
                query += " AND is_saved = 1"

            if source_filter and source_filter != 'all':
                query += f" AND source = {ph}"
                params.append(source_filter)

            if keyword:
                query += self._like_clause('title', ph)
                params.append(f"%{self._escape_like(keyword)}%")

            if category and category != 'all':
                query += f" AND category = {ph}"
                params.append(category)

            order_by = "created_at DESC"
            sort_key = (sort_by or 'newest').lower()
            if sort_key == 'score':
                order_by = f"{self._cast_int('score')} DESC, created_at DESC"
            elif sort_key == 'comments':
                # Both backends must agree: PG '^\d+$' is a full match, while
                # SQLite GLOB '[0-9]*' only means "digit then anything", so
                # '1,234' used to cast to 1 on SQLite and 0 on PG.
                order_by = (
                    f"CASE WHEN {self._comments_is_numeric()} "
                    f"THEN {self._cast_int('comments')} ELSE 0 END DESC, created_at DESC"
                )

            query += f" ORDER BY {order_by} LIMIT {ph} OFFSET {ph}"
            params.extend([limit, max(0, offset)])

            cursor.execute(query, params)
            return self._normalize_rows(cursor, cursor.fetchall())

    def get_total_count(self, source_filter: str = 'all', keyword: str = '',
                        saved_only: bool = False, category: str = '') -> int:
        """Returns total article count for pagination calculation."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            ph = self._ph(1)
            query = "SELECT COUNT(*) FROM articles WHERE 1=1"
            params: list[Any] = []

            if saved_only:
                query += " AND is_saved = 1"
            if source_filter and source_filter != 'all':
                query += f" AND source = {ph}"
                params.append(source_filter)
            if keyword:
                query += self._like_clause('title', ph)
                params.append(f"%{self._escape_like(keyword)}%")
            if category and category != 'all':
                query += f" AND category = {ph}"
                params.append(category)

            cursor.execute(query, params)
            return self._fetch_scalar(cursor)

    def _sanitize_fts_query(self, query: str) -> str:
        """Escape FTS5 special syntax to prevent injection/errors."""
        # Remove FTS5 operators and quote the query as phrase tokens.
        # Naive stripping is deliberate: it cannot emit malformed FTS5 syntax.
        cleaned = re.sub(r'[\"\*\(\)\:\^\-]', ' ', query)
        cleaned = re.sub(r'\b(AND|OR|NOT|NEAR)\b', ' ', cleaned, flags=re.IGNORECASE)
        tokens = [t for t in re.findall(r'[a-zA-Z0-9]+', cleaned) if len(t) >= 2]
        if not tokens:
            return ''
        # Join as OR phrase for broader recall
        return ' OR '.join(f'"{t}"' for t in tokens[:10])

    def search_articles(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        """Full-text search using FTS5 (SQLite) or ILIKE (PostgreSQL)."""
        if not query or not query.strip():
            return []
        # Resolve the fallback query BEFORE taking a connection: re-entering
        # get_connection() while one is checked out makes psycopg2 hand out a
        # second connection and then close+discard the outer one.
        fts_query = self._sanitize_fts_query(query) if not self._use_postgres else ''
        if not self._use_postgres and not fts_query:
            return self.get_articles(limit=limit, keyword=query, sort_by='newest')
        pattern = f"%{self._escape_like(query)}%"
        with self.get_connection() as conn:
            cursor = conn.cursor()
            ph = self._ph(1)
            if self._use_postgres:
                # `%foo%` with a leading wildcard cannot use a btree index, and
                # the OR chain across four columns forces a sequential scan.
                # pg_trgm GIN indexes are the fix; until then this is expected.
                cursor.execute(f'''
                    SELECT * FROM articles
                    WHERE title ILIKE {ph} ESCAPE '\\' OR excerpt ILIKE {ph} ESCAPE '\\' OR author ILIKE {ph} ESCAPE '\\' OR source ILIKE {ph} ESCAPE '\\'
                    ORDER BY created_at DESC
                    LIMIT {ph}
                ''', (pattern, pattern, pattern, pattern, limit))
            else:
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
                    return self.get_articles(limit=limit, keyword=query, sort_by='newest')

            return self._normalize_rows(cursor, cursor.fetchall())

    def _toggle_flag(self, article_id: int, column: str) -> bool | None:
        """Flips a boolean-ish column atomically and returns the new state.

        A SELECT-then-UPDATE let two concurrent callers both read 0 and both
        write 1, and `not None` treated a NULL column as "set".  A single
        UPDATE...RETURNING fixes both (RETURNING needs PG, or SQLite >= 3.35).
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            ph = self._ph(1)
            sql = (
                f"UPDATE articles SET {column} = CASE WHEN {column} = 1 THEN 0 ELSE 1 END "
                f"WHERE id = {ph} RETURNING {column}"
            )
            try:
                cursor.execute(sql, (article_id,))
                row = cursor.fetchone()
            except Exception as e:
                if 'RETURNING' not in str(e).upper():
                    raise
                # Backend without RETURNING: accept the (rare) lost-update race
                # rather than failing the request outright.
                logger.warning(f"RETURNING unsupported, using non-atomic toggle: {e}")
                cursor.execute(
                    f"UPDATE articles SET {column} = CASE WHEN {column} = 1 THEN 0 ELSE 1 END "
                    f"WHERE id = {ph}", (article_id,))
                cursor.execute(f"SELECT {column} FROM articles WHERE id = {ph}", (article_id,))
                row = cursor.fetchone()
            conn.commit()
            if not row:
                return None
            value = row[column] if isinstance(row, dict) else row[0]
            return bool(value)

    def toggle_bookmark(self, article_id: int) -> bool | None:
        """Toggles the bookmark status of an article."""
        return self._toggle_flag(article_id, 'is_saved')

    def toggle_read(self, article_id: int) -> bool | None:
        """Toggles the read status of an article."""
        return self._toggle_flag(article_id, 'is_read')

    def update_article_metadata(self, article_id: int, sentiment: str | None = None,
                                 sentiment_score: float | None = None,
                                 category: str | None = None,
                                 read_time: int | None = None,
                                 metadata_processed_at: float | None = None) -> None:
        """Updates article metadata (sentiment, category, read_time)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            ph = self._ph(1)
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

    def get_unprocessed_articles(self, limit: int = 50) -> list[dict[str, Any]]:
        """Gets articles that haven't been processed for sentiment/category yet."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            ph = self._ph(1)
            cursor.execute(f'''
                SELECT * FROM articles
                WHERE metadata_processed_at IS NULL
                ORDER BY created_at DESC LIMIT {ph}
            ''', (limit,))
            rows = cursor.fetchall()
            return [self._row_to_dict(cursor, row) for row in rows]

    def get_article_count(self) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM articles")
            return self._fetch_scalar(cursor)

    def get_stats(self) -> dict[str, Any]:
        """Returns statistics about articles in the database."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM articles")
            total = self._fetch_scalar(cursor)

            twenty_four_hours_ago = time.time() - (24 * 60 * 60)
            ph = self._ph(1)
            cursor.execute(f"SELECT COUNT(*) FROM articles WHERE created_at >= {ph}", (twenty_four_hours_ago,))
            today = self._fetch_scalar(cursor)

            cursor.execute("SELECT COUNT(*) FROM articles WHERE is_saved = 1")
            saved = self._fetch_scalar(cursor)

            cursor.execute("SELECT COUNT(*) FROM articles WHERE is_read = 1")
            read_count = self._fetch_scalar(cursor)

            cursor.execute("SELECT source, COUNT(*) as count FROM articles GROUP BY source")
            by_source_rows = cursor.fetchall()
            # A None key makes Flask's sort_keys=True raise TypeError, turning
            # a single NULL source into a 500 on every page render.
            by_source = {(row['source'] or 'Unknown'): row['count'] for row in by_source_rows}

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

    def get_personalized_feed(self, limit: int = 30) -> list[dict[str, Any]]:
        """Returns articles boosted by user preferences (based on bookmarked sources/categories)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            ph = self._ph(1)

            # Find user's preferred sources and categories from bookmarks
            cursor.execute('''
                SELECT source, COUNT(*) as cnt FROM articles
                WHERE is_saved = 1 GROUP BY source ORDER BY cnt DESC LIMIT 3
            ''')
            # A NULL source can never satisfy `source IN (...)`, so it would
            # silently consume one of the three preference slots.
            preferred_sources = [r['source'] for r in cursor.fetchall() if r['source']]

            cursor.execute('''
                SELECT category, COUNT(*) as cnt FROM articles
                WHERE is_saved = 1 GROUP BY category ORDER BY cnt DESC LIMIT 3
            ''')
            preferred_categories = [row['category'] for row in cursor.fetchall()]

            if not preferred_sources and not preferred_categories:
                # Run the query on this connection rather than re-entering
                # get_connection(), which would consume a second pool slot and
                # get the outer connection closed underneath us.
                cursor.execute(f"SELECT * FROM articles ORDER BY created_at DESC LIMIT {ph}", (limit,))
                results = self._normalize_rows(cursor, cursor.fetchall())
                for d in results:
                    d['relevance_score'] = 0
                return results

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
            return self._normalize_rows(cursor, cursor.fetchall())

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
        by_source: dict[str, list] = {}
        for a in articles:
            src = a.get('source', 'Other')
            by_source.setdefault(src, []).append(a)

        for source, arts in by_source.items():
            lines.append(f"\n## {source}\n")
            for a in arts:
                lines.append(f"- [{a.get('title')}]({a.get('link')})")

        return '\n'.join(lines)
