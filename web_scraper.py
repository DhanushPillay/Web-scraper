"""
Web Scraper Module — Tech News Aggregator
Uses RSS feeds where available for speed, falls back to HTML scraping.
Includes caching, health tracking, and retry logic.
"""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
import feedparser
import csv
import time
import logging
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """Abstract base class for all news scrapers."""

    def __init__(self) -> None:
        self.articles: list[dict] = []
        self.headers: dict[str, str] = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        # Requests session with automatic retries on transient failures
        self.session = requests.Session()
        retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503])
        self.session.mount('https://', HTTPAdapter(max_retries=retries))
        self.session.mount('http://', HTTPAdapter(max_retries=retries))
        self.session.headers.update(self.headers)

        # Health tracking
        self.last_scrape_time: float = 0
        self.last_status: str = "idle"  # idle, ok, error
        self.last_error: str = ""
        self.scrape_duration: float = 0

    @abstractmethod
    def scrape(self, num_pages: int = 1) -> None:
        pass

    def get_articles(self) -> list[dict]:
        return self.articles

    def get_health(self) -> dict:
        return {
            'source': self.__class__.__name__.replace('Scraper', ''),
            'status': self.last_status,
            'last_scrape': self.last_scrape_time,
            'duration': round(self.scrape_duration, 2),
            'article_count': len(self.articles),
            'last_error': self.last_error
        }


class HackerNewsScraper(BaseScraper):
    """Scraper for Hacker News using RSS feed (hnrss.org) for speed."""

    def __init__(self) -> None:
        super().__init__()
        # hnrss.org provides a fast, reliable RSS feed for HN
        self.feed_url: str = "https://hnrss.org/frontpage?count=30"
        self.fallback_url: str = "https://news.ycombinator.com/news"

    def scrape(self, num_pages: int = 1) -> None:
        start = time.time()
        self.articles = []
        logger.info("[HN] Starting RSS scrape...")
        try:
            # Try RSS first (much faster)
            feed = feedparser.parse(self.feed_url)
            if feed.entries:
                for entry in feed.entries:
                    # Extract comments count from the description if available
                    comments = "0"
                    if hasattr(entry, 'comments') and entry.comments:
                        # comments URL contains item ID
                        pass

                    score = 0
                    # hnrss includes score in description
                    if hasattr(entry, 'description'):
                        desc = entry.description or ""
                        if 'Points:' in desc:
                            try:
                                score = int(desc.split('Points:')[1].split('<')[0].strip())
                            except (ValueError, IndexError):
                                pass
                        if 'Comments:' in desc:
                            try:
                                comments = desc.split('Comments:')[1].split('<')[0].strip()
                            except (ValueError, IndexError):
                                comments = "0"

                    time_posted = "Recent"
                    if hasattr(entry, 'published'):
                        time_posted = entry.published

                    author = "Unknown"
                    if hasattr(entry, 'author'):
                        author = entry.author

                    self.articles.append({
                        'title': entry.title,
                        'link': entry.link,
                        'score': score,
                        'author': author,
                        'time': time_posted,
                        'comments': str(comments),
                        'source': 'Hacker News'
                    })
                self.last_status = "ok"
            else:
                # Fallback to HTML scraping if RSS fails
                logger.warning("[HN] RSS empty, falling back to HTML scrape")
                self._scrape_html(num_pages)
        except Exception as e:
            logger.warning(f"[HN] RSS failed ({e}), falling back to HTML")
            self._scrape_html(num_pages)

        self.scrape_duration = time.time() - start
        self.last_scrape_time = time.time()
        logger.info(f"[HN] Done. {len(self.articles)} articles in {self.scrape_duration:.1f}s")

    def _scrape_html(self, num_pages: int) -> None:
        """Fallback HTML scraper for Hacker News."""
        try:
            for p in range(1, num_pages + 1):
                url = f"{self.fallback_url}?p={p}"
                response = self.session.get(url, timeout=10)
                if response.status_code == 200:
                    self._parse_html(response.text)
                if p < num_pages:
                    time.sleep(1)
            self.last_status = "ok"
        except requests.RequestException as e:
            self.last_status = "error"
            self.last_error = str(e)
            logger.warning(f"[HN] HTML fallback failed: {e}")

    def _parse_html(self, html_content: str) -> None:
        soup = BeautifulSoup(html_content, 'html.parser')
        story_rows = soup.find_all('tr', class_='athing')

        for row in story_rows:
            try:
                title_element = row.find('span', class_='titleline').find('a')
                title = title_element.text
                link = title_element['href']
                if not link.startswith('http'):
                    link = f"https://news.ycombinator.com/{link}"

                metadata_row = row.find_next_sibling('tr')
                subtext = metadata_row.find('td', class_='subtext')

                score = 0
                author = "Unknown"
                time_posted = "Unknown"
                comments = "0"

                if subtext:
                    score_elem = subtext.find('span', class_='score')
                    if score_elem:
                        score = int(score_elem.text.split()[0])

                    author_elem = subtext.find('a', class_='hnuser')
                    if author_elem:
                        author = author_elem.text

                    age_elem = subtext.find('span', class_='age')
                    if age_elem:
                        time_posted = age_elem.text

                    links = subtext.find_all('a')
                    for l in links:
                        if 'comment' in l.text:
                            comments = l.text.split()[0]
                            if comments == 'discuss':
                                comments = "0"
                            break

                self.articles.append({
                    'title': title,
                    'link': link,
                    'score': score,
                    'author': author,
                    'time': time_posted,
                    'comments': comments,
                    'source': 'Hacker News'
                })
            except (AttributeError, ValueError):
                continue


class TechCrunchScraper(BaseScraper):
    """Scraper for TechCrunch using RSS feed."""

    def __init__(self) -> None:
        super().__init__()
        self.feed_url: str = "https://techcrunch.com/feed/"

    def scrape(self, num_pages: int = 1) -> None:
        start = time.time()
        self.articles = []
        logger.info("[TC] Starting RSS scrape...")
        try:
            feed = feedparser.parse(self.feed_url)
            for entry in feed.entries[:25]:
                author = "TechCrunch"
                if hasattr(entry, 'author'):
                    author = entry.author

                time_posted = "Recent"
                if hasattr(entry, 'published'):
                    time_posted = entry.published

                self.articles.append({
                    'title': entry.title,
                    'link': entry.link,
                    'score': 0,
                    'author': author,
                    'time': time_posted,
                    'comments': '0',
                    'source': 'TechCrunch'
                })
            self.last_status = "ok"
        except Exception as e:
            self.last_status = "error"
            self.last_error = str(e)
            logger.warning(f"[TC] Error: {e}")

        self.scrape_duration = time.time() - start
        self.last_scrape_time = time.time()
        logger.info(f"[TC] Done. {len(self.articles)} articles in {self.scrape_duration:.1f}s")


class RedditScraper(BaseScraper):
    """Scraper for r/technology using JSON API (already fast)."""

    def __init__(self) -> None:
        super().__init__()
        self.base_url: str = "https://www.reddit.com/r/technology/top.json?t=day&limit=25"

    def scrape(self, num_pages: int = 1) -> None:
        start = time.time()
        self.articles = []
        logger.info("[Reddit] Starting JSON scrape...")
        try:
            response = self.session.get(self.base_url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                children = data.get('data', {}).get('children', [])

                for post in children:
                    p_data = post.get('data', {})
                    self.articles.append({
                        'title': p_data.get('title'),
                        'link': p_data.get('url'),
                        'score': p_data.get('score', 0),
                        'author': p_data.get('author'),
                        'time': 'Today',
                        'comments': str(p_data.get('num_comments', 0)),
                        'source': 'Reddit'
                    })
            self.last_status = "ok"
        except requests.RequestException as e:
            self.last_status = "error"
            self.last_error = str(e)
            logger.warning(f"[Reddit] Error: {e}")

        self.scrape_duration = time.time() - start
        self.last_scrape_time = time.time()
        logger.info(f"[Reddit] Done. {len(self.articles)} articles in {self.scrape_duration:.1f}s")


class TheVergeScraper(BaseScraper):
    """Scraper for The Verge using RSS feed."""

    def __init__(self) -> None:
        super().__init__()
        self.feed_url: str = "https://www.theverge.com/rss/index.xml"

    def scrape(self, num_pages: int = 1) -> None:
        start = time.time()
        self.articles = []
        logger.info("[Verge] Starting RSS scrape...")
        try:
            feed = feedparser.parse(self.feed_url)
            for entry in feed.entries[:15]:
                author = "The Verge Staff"
                if hasattr(entry, 'author'):
                    author = entry.author

                time_posted = "Recent"
                if hasattr(entry, 'published'):
                    time_posted = entry.published

                self.articles.append({
                    'title': entry.title,
                    'link': entry.link,
                    'score': 0,
                    'author': author,
                    'time': time_posted,
                    'comments': '0',
                    'source': 'The Verge'
                })
            self.last_status = "ok"
        except Exception as e:
            self.last_status = "error"
            self.last_error = str(e)
            logger.warning(f"[Verge] Error: {e}")

        self.scrape_duration = time.time() - start
        self.last_scrape_time = time.time()
        logger.info(f"[Verge] Done. {len(self.articles)} articles in {self.scrape_duration:.1f}s")


class ArsTechnicaScraper(BaseScraper):
    """Scraper for Ars Technica using RSS feed."""

    def __init__(self) -> None:
        super().__init__()
        self.feed_url: str = "https://feeds.arstechnica.com/arstechnica/index"

    def scrape(self, num_pages: int = 1) -> None:
        start = time.time()
        self.articles = []
        logger.info("[Ars] Starting RSS scrape...")
        try:
            feed = feedparser.parse(self.feed_url)
            for entry in feed.entries[:15]:
                author = "Ars Staff"
                if hasattr(entry, 'author'):
                    author = entry.author

                time_posted = "Recent"
                if hasattr(entry, 'published'):
                    time_posted = entry.published

                self.articles.append({
                    'title': entry.title,
                    'link': entry.link,
                    'score': 0,
                    'author': author,
                    'time': time_posted,
                    'comments': '0',
                    'source': 'Ars Technica'
                })
            self.last_status = "ok"
        except Exception as e:
            self.last_status = "error"
            self.last_error = str(e)
            logger.warning(f"[Ars] Error: {e}")

        self.scrape_duration = time.time() - start
        self.last_scrape_time = time.time()
        logger.info(f"[Ars] Done. {len(self.articles)} articles in {self.scrape_duration:.1f}s")


class NewsAggregator:
    """Aggregates articles from all scrapers with caching and health tracking."""

    CACHE_TTL = 300  # 5 minutes

    def __init__(self) -> None:
        self.scrapers: list[BaseScraper] = [
            HackerNewsScraper(),
            TechCrunchScraper(),
            RedditScraper(),
            TheVergeScraper(),
            ArsTechnicaScraper()
        ]
        self.articles: list[dict] = []
        self._last_scrape_time: float = 0

    def scrape_all(self, hn_pages: int = 1, force: bool = False) -> None:
        """Runs all scrapers in parallel. Skips if cache is still valid."""
        # Cache check — avoid re-scraping if data is fresh
        if not force and self.articles and (time.time() - self._last_scrape_time) < self.CACHE_TTL:
            logger.info(f"Cache still valid ({int(self.CACHE_TTL - (time.time() - self._last_scrape_time))}s remaining). Skipping scrape.")
            return

        self.articles = []

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = []
            for scraper in self.scrapers:
                pages = hn_pages if isinstance(scraper, HackerNewsScraper) else 1
                futures.append(executor.submit(scraper.scrape, pages))

            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"Scraper thread failed: {e}")

        # Collect results from all scrapers
        for scraper in self.scrapers:
            self.articles.extend(scraper.get_articles())

        self._last_scrape_time = time.time()
        logger.info(f"Total articles scraped: {len(self.articles)}")

    def get_articles(self) -> list[dict]:
        return self.articles

    def get_health(self) -> list[dict]:
        """Returns health status of all scrapers."""
        return [s.get_health() for s in self.scrapers]

    def filter_by_keyword(self, articles: list[dict], keyword: str) -> list[dict]:
        if not keyword:
            return articles
        return [art for art in articles if keyword.lower() in art['title'].lower()]

    def save_to_csv(self, filename: str = "tech_news.csv") -> None:
        if not self.articles:
            logger.info("No data to save.")
            return
        try:
            with open(filename, mode='w', newline='', encoding='utf-8') as file:
                writer = csv.DictWriter(file, fieldnames=["title", "score", "link", "author", "time", "comments", "source"])
                writer.writeheader()
                writer.writerows(self.articles)
            logger.info(f"Data successfully saved to {filename}")
        except (IOError, OSError) as e:
            logger.error(f"Error saving file: {e}")


# Legacy support for main execution
def main() -> None:
    logging.basicConfig(level=logging.INFO)
    agg = NewsAggregator()
    print("Scraping all sources...")
    agg.scrape_all(hn_pages=2)

    sorted_arts = sorted(agg.articles, key=lambda x: x['score'] if isinstance(x['score'], int) else 0, reverse=True)

    print(f"\nTotal articles: {len(sorted_arts)}")
    print("-" * 80)
    print(f"{'SOURCE':<12} | {'SCORE':<5} | {'TITLE'}")
    print("-" * 80)

    for art in sorted_arts[:20]:
        print(f"{art['source'][:12]:<12} | {str(art['score']):<5} | {art['title'][:60]}")


if __name__ == "__main__":
    main()