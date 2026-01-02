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
        """Initializes the database table and ensures schema is up to date."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # 1. Create table if it doesn't exist
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
                is_saved INTEGER DEFAULT 0
            )
        ''')
        
        # 2. Migration: Ensure 'is_saved' column exists (for older DB versions)
        try:
            cursor.execute("SELECT is_saved FROM articles LIMIT 1")
        except sqlite3.OperationalError:
            print("Migrating DB: Adding 'is_saved' column...")
            cursor.execute("ALTER TABLE articles ADD COLUMN is_saved INTEGER DEFAULT 0")
            
        conn.commit()
        conn.close()

    def add_article(self, article: Dict[str, Any]) -> None:
        """Adds a single article to the database. Ignores duplicates based on link."""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT OR IGNORE INTO articles (title, link, score, author, time_posted, comments, source, created_at, is_saved)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
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
            conn.commit()
        except Exception as e:
            print(f"Error adding article: {e}")
        finally:
            conn.close()

    def add_articles(self, articles: List[Dict[str, Any]]) -> None:
        """Adds a list of articles."""
        for art in articles:
            self.add_article(art)

    def get_articles(self, limit: int = 100, source_filter: str = 'all', keyword: str = '', saved_only: bool = False) -> List[Dict[str, Any]]:
        """Retrieves articles with optional filtering."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        query = "SELECT * FROM articles WHERE 1=1"
        params: List[Any] = []

        if saved_only:
             query += " AND is_saved = 1"

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
        
        # Convert rows to dicts and map 'time_posted' back to 'time'
        results = []
        for row in rows:
            d = dict(row)
            d['time'] = d['time_posted'] # Map back for frontend
            results.append(d)
            
        return results

    def toggle_bookmark(self, article_id: int) -> bool:
        """Toggles the bookmark status of an article. Returns new status."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Get current status
        cursor.execute("SELECT is_saved FROM articles WHERE id = ?", (article_id,))
        result = cursor.fetchone()
        
        new_status = False
        if result:
            current_status = result['is_saved']
            new_status = not current_status
            cursor.execute("UPDATE articles SET is_saved = ? WHERE id = ?", (int(new_status), article_id))
            conn.commit()
            
        conn.close()
        return new_status

    def get_article_count(self) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM articles")
        count = cursor.fetchone()[0]
        conn.close()
        return count
