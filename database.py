import sqlite3
import time
from typing import List, Dict, Any, Optional

class Database:
    def __init__(self, db_name: str = "technews.db") -> None:
        self.db_name = db_name
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_name)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        """Initializes the database table if it doesn't exist."""
        conn = self.get_connection()
        cursor = conn.cursor()
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
                created_at REAL
            )
        ''')
        conn.commit()
        conn.close()

    def add_article(self, article: Dict[str, Any]) -> None:
        """Adds a single article to the database. Ignores duplicates based on link."""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT OR IGNORE INTO articles (title, link, score, author, time_posted, comments, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                article.get('title'),
                article.get('link'),
                article.get('score', 0),
                article.get('author', 'Unknown'),
                article.get('time', 'Unknown'),
                article.get('comments', '0'),
                article.get('source', 'Unknown'),
                time.time()
            ))
            # If we want to update existing entries (e.g. score changes), we'd use ON CONFLICT DO UPDATE
            # For now, INSERT OR IGNORE is fine to keep the first discovery.
            conn.commit()
        except Exception as e:
            print(f"Error adding article: {e}")
        finally:
            conn.close()

    def add_articles(self, articles: List[Dict[str, Any]]) -> None:
        """Adds a list of articles."""
        for art in articles:
            self.add_article(art)

    def get_articles(self, limit: int = 100, source_filter: str = 'all', keyword: str = '') -> List[Dict[str, Any]]:
        """Retrieves articles with optional filtering."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        query = "SELECT * FROM articles WHERE 1=1"
        params: List[Any] = []

        if source_filter and source_filter != 'all':
            query += " AND source = ?"
            params.append(source_filter)
        
        if keyword:
            query += " AND title LIKE ?"
            params.append(f"%{keyword}%")

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        # Convert rows to dicts and map 'time_posted' back to 'time' key for frontend compatibility
        results = []
        for row in rows:
            d = dict(row)
            d['time'] = d['time_posted'] # Map back for frontend
            results.append(d)
            
        return results

    def get_article_count(self) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM articles")
        count = cursor.fetchone()[0]
        conn.close()
        return count
