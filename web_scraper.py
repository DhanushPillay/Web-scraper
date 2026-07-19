"""
Web Scraper Module — Sniffer
Uses RSS feeds where available for speed, falls back to HTML scraping.
Includes caching, health tracking, and retry logic.
"""
import re
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
import feedparser
import time
import logging
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import aiohttp
import asyncio

from utils.credibility import is_credible, score_article

logger = logging.getLogger(__name__)

EXCERPT_MAX_LEN = 280


def _extract_feed_image(entry) -> str:
    """Return the best image URL exposed by an RSS or Atom entry."""
    for field in ('media_content', 'media_thumbnail', 'enclosures'):
        for item in getattr(entry, field, []) or []:
            url = item.get('url') or item.get('href')
            if url and str(url).startswith(('https://', 'http://')):
                return str(url)

    for field in ('summary', 'description', 'content'):
        value = getattr(entry, field, '') or ''
        if isinstance(value, list):
            value = ' '.join(str(part.get('value', '')) for part in value)
        match = re.search(r'<img[^>]+src=[\"\']([^\"\']+)', str(value), re.IGNORECASE)
        if match and match.group(1).startswith(('https://', 'http://')):
            return match.group(1)
    return ''

def _clean_excerpt(text: str) -> str:
    """Strip HTML tags, normalize whitespace, truncate to EXCERPT_MAX_LEN."""
    if not text:
        return ""
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Decode common HTML entities
    text = text.replace('&', '&').replace('<', '<').replace('>', '>')
    text = text.replace("&#34;", "&#34;").replace("&#39;", "&#39;").replace("&nbsp;", " ")
    # Strip HN raw URL patterns (Article URL: ..., Comments URL: ..., Points: ..., # Comments: ...)
    text = re.sub(r'Article URL:\s*https?://\S+', '', text)
    text = re.sub(r'Comments URL:\s*https?://\S+', '', text)
    text = re.sub(r'Points:\s*\d+', '', text)
    text = re.sub(r'#\s*Comments:\s*\d+', '', text)
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()
# Truncate at word boundary
    if len(text) > EXCERPT_MAX_LEN:
        text = text[:EXCERPT_MAX_LEN].rsplit(' ', 1)[0] + '…'
    return text


async def _fetch_article_image_async(session: aiohttp.ClientSession, url: str) -> str:
    """Fetch the top image from an article page via meta tags."""
    try:
        async with session.get(url, timeout=5) as response:
            if response.status != 200:
                return ''
            html = await response.text()
            soup = BeautifulSoup(html, 'html.parser')
            meta_og_image = soup.find('meta', property='og:image')
            if meta_og_image and meta_og_image.get('content'):
                return str(meta_og_image['content'])
            return ''
    except Exception:
        return ''


class BaseScraper(ABC):
    """Abstract base class for all news scrapers."""

    def __init__(self) -> None:
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
    def scrape(self, num_pages: int = 1) -> list[dict]:
        pass

    def get_health(self) -> dict:
        return {
            'source': self.__class__.__name__.replace('Scraper', ''),
            'status': self.last_status,
            'last_scrape': self.last_scrape_time,
            'duration': round(self.scrape_duration, 2),
            'last_error': self.last_error
        }


class HackerNewsScraper(BaseScraper):
    """Scraper for Hacker News using RSS feed (hnrss.org) for speed."""

    def __init__(self) -> None:
        super().__init__()
        # hnrss.org provides a fast, reliable RSS feed for HN
        self.feed_url: str = "https://hnrss.org/frontpage?count=30"
        self.fallback_url: str = "https://news.ycombinator.com/news"

    def scrape(self, num_pages: int = 1) -> list[dict]:
        start = time.time()
        articles = []
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

                    # Extract excerpt from RSS description
                    excerpt = ""
                    if hasattr(entry, 'description'):
                        excerpt = _clean_excerpt(entry.description)

                    articles.append({
                        'title': entry.title,
                        'link': entry.link,
                        'score': score,
                        'author': author,
                        'time': time_posted,
                        'comments': str(comments),
                        'source': 'Hacker News',
                        'excerpt': excerpt,
                        'image_url': _extract_feed_image(entry)
                    })
                self.last_status = "ok"
            else:
                # Fallback to HTML scraping if RSS fails
                logger.warning("[HN] RSS empty, falling back to HTML scrape")
                articles = self._scrape_html(num_pages)
        except Exception as e:
            logger.warning(f"[HN] RSS failed ({e}), falling back to HTML")
            articles = self._scrape_html(num_pages)

        self.scrape_duration = time.time() - start
        self.last_scrape_time = time.time()
        logger.info(f"[HN] Done. {len(articles)} articles in {self.scrape_duration:.1f}s")
        return articles

    def _scrape_html(self, num_pages: int) -> list[dict]:
        """Fallback HTML scraper for Hacker News."""
        articles = []
        try:
            for p in range(1, num_pages + 1):
                url = f"{self.fallback_url}?p={p}"
                response = self.session.get(url, timeout=10)
                if response.status_code == 200:
                    articles.extend(self._parse_html(response.text))
                if p < num_pages:
                    time.sleep(1)
            self.last_status = "ok"
        except requests.RequestException as e:
            self.last_status = "error"
            self.last_error = str(e)
            logger.warning(f"[HN] HTML fallback failed: {e}")
        return articles

    def _parse_html(self, html_content: str) -> list[dict]:
        articles = []
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

                # HN HTML doesn't have excerpts, leave empty
                excerpt = ""

                articles.append({
                    'title': title,
                    'link': link,
                    'score': score,
                    'author': author,
                    'time': time_posted,
                    'comments': comments,
                        'source': 'Hacker News',
                        'excerpt': excerpt,
                        'image_url': ''
                })
            except (AttributeError, ValueError):
                continue
        return articles


class TechCrunchScraper(BaseScraper):
    """Scraper for TechCrunch using RSS feed."""

    def __init__(self) -> None:
        super().__init__()
        self.feed_url: str = "https://techcrunch.com/feed/"

    def scrape(self, num_pages: int = 1) -> list[dict]:
        start = time.time()
        articles = []
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

                # Extract excerpt from RSS description/summary
                excerpt = ""
                if hasattr(entry, 'summary'):
                    excerpt = _clean_excerpt(entry.summary)
                elif hasattr(entry, 'description'):
                    excerpt = _clean_excerpt(entry.description)

                articles.append({
                    'title': entry.title,
                    'link': entry.link,
                    'score': 0,
                    'author': author,
                    'time': time_posted,
                    'comments': '0',
                    'source': 'TechCrunch',
                    'excerpt': excerpt,
                    'image_url': _extract_feed_image(entry)
                })
            self.last_status = "ok"
        except Exception as e:
            self.last_status = "error"
            self.last_error = str(e)
            logger.warning(f"[TC] Error: {e}")

        self.scrape_duration = time.time() - start
        self.last_scrape_time = time.time()
        logger.info(f"[TC] Done. {len(articles)} articles in {self.scrape_duration:.1f}s")
        return articles


class RedditScraper(BaseScraper):
    """Scraper for r/technology using JSON API (already fast)."""

    def __init__(self) -> None:
        super().__init__()
        self.base_url: str = "https://www.reddit.com/r/technology/top.json?t=day&limit=25"

    def scrape(self, num_pages: int = 1) -> list[dict]:
        start = time.time()
        articles = []
        logger.info("[Reddit] Starting JSON scrape...")
        try:
            response = self.session.get(self.base_url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                children = data.get('data', {}).get('children', [])

                for post in children:
                    p_data = post.get('data', {})
                    # Extract excerpt from selftext (Reddit post body)
                    excerpt = ""
                    if p_data.get('selftext'):
                        excerpt = _clean_excerpt(p_data['selftext'])

                    articles.append({
                        'title': p_data.get('title'),
                        'link': p_data.get('url'),
                        'score': p_data.get('score', 0),
                        'author': p_data.get('author'),
                        'time': 'Today',
                        'comments': str(p_data.get('num_comments', 0)),
                        'source': 'Reddit',
                        'excerpt': excerpt,
                        'image_url': (
                            p_data.get('thumbnail')
                            if str(p_data.get('thumbnail', '')).startswith(('https://', 'http://'))
                            else p_data.get('preview', {}).get('images', [{}])[0].get('source', {}).get('url', '')
                        )
                    })
            self.last_status = "ok"
        except requests.RequestException as e:
            self.last_status = "error"
            self.last_error = str(e)
            logger.warning(f"[Reddit] Error: {e}")

        self.scrape_duration = time.time() - start
        self.last_scrape_time = time.time()
        logger.info(f"[Reddit] Done. {len(articles)} articles in {self.scrape_duration:.1f}s")
        return articles


class TheVergeScraper(BaseScraper):
    """Scraper for The Verge using RSS feed."""

    def __init__(self) -> None:
        super().__init__()
        self.feed_url: str = "https://www.theverge.com/rss/index.xml"

    def scrape(self, num_pages: int = 1) -> list[dict]:
        start = time.time()
        articles = []
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

                # Extract excerpt from RSS summary/description
                excerpt = ""
                if hasattr(entry, 'summary'):
                    excerpt = _clean_excerpt(entry.summary)
                elif hasattr(entry, 'description'):
                    excerpt = _clean_excerpt(entry.description)

                articles.append({
                    'title': entry.title,
                    'link': entry.link,
                    'score': 0,
                    'author': author,
                    'time': time_posted,
                    'comments': '0',
                    'source': 'The Verge',
                    'excerpt': excerpt,
                    'image_url': _extract_feed_image(entry)
                })
            self.last_status = "ok"
        except Exception as e:
            self.last_status = "error"
            self.last_error = str(e)
            logger.warning(f"[Verge] Error: {e}")

        self.scrape_duration = time.time() - start
        self.last_scrape_time = time.time()
        logger.info(f"[Verge] Done. {len(articles)} articles in {self.scrape_duration:.1f}s")
        return articles


class ArsTechnicaScraper(BaseScraper):
    """Scraper for Ars Technica using RSS feed."""

    def __init__(self) -> None:
        super().__init__()
        self.feed_url: str = "https://feeds.arstechnica.com/arstechnica/index"

    def scrape(self, num_pages: int = 1) -> list[dict]:
        start = time.time()
        articles = []
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

                # Extract excerpt from RSS summary/description
                excerpt = ""
                if hasattr(entry, 'summary'):
                    excerpt = _clean_excerpt(entry.summary)
                elif hasattr(entry, 'description'):
                    excerpt = _clean_excerpt(entry.description)

                articles.append({
                    'title': entry.title,
                    'link': entry.link,
                    'score': 0,
                    'author': author,
                    'time': time_posted,
                    'comments': '0',
                    'source': 'Ars Technica',
                    'excerpt': excerpt,
                    'image_url': _extract_feed_image(entry)
                })
            self.last_status = "ok"
        except Exception as e:
            self.last_status = "error"
            self.last_error = str(e)
            logger.warning(f"[Ars] Error: {e}")

        self.scrape_duration = time.time() - start
        self.last_scrape_time = time.time()
        logger.info(f"[Ars] Done. {len(articles)} articles in {self.scrape_duration:.1f}s")
        return articles


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

    async def scrape_all_async(self, hn_pages: int = 1, force: bool = False) -> None:
        """Runs all scrapers in parallel (async). Skips if cache is still valid."""
        # Cache check — avoid re-scraping if data is fresh
        if not force and self.articles and (time.time() - self._last_scrape_time) < self.CACHE_TTL:
            logger.info(f"Cache still valid ({int(self.CACHE_TTL - (time.time() - self._last_scrape_time))}s remaining). Skipping scrape.")
            return

        self.articles = []

        # Run all scrapers concurrently using asyncio.gather
        scrape_tasks = []
        for scraper in self.scrapers:
            pages = hn_pages if isinstance(scraper, HackerNewsScraper) else 1
            scrape_tasks.append(asyncio.to_thread(scraper.scrape, pages))

        results = await asyncio.gather(*scrape_tasks, return_exceptions=True)

        for scraper, result in zip(self.scrapers, results):
            if isinstance(result, Exception):
                logger.error(f"Scraper {scraper.__class__.__name__} failed: {result}")
                continue
            if result:
                # Apply credibility filter before adding
                valid_articles = []
                for a in result:
                    if is_credible(a.get('title', ''), a.get('link', '')):
                        # Add credibility details to article
                        _, cred = score_article(a.get('title', ''), a.get('link', ''))
                        a['credibility'] = cred
                        valid_articles.append(a)
                self.articles.extend(valid_articles)

        # Async image enrichment (single event loop)
        await self._enrich_images_async()
            
        self._last_scrape_time = time.time()
        logger.info(f"Total articles scraped: {len(self.articles)}")

    def scrape_all(self, hn_pages: int = 1, force: bool = False) -> None:
        """Synchronous wrapper for backward compatibility."""
        asyncio.run(self.scrape_all_async(hn_pages, force))

    async def _enrich_images_async(self) -> None:
        """Fetch real images for articles missing image_url concurrently."""
        missing = [a for a in self.articles if not a.get('image_url')]
        if not missing:
            return
        logger.info(f"Enriching images for {len(missing)} articles...")
        
        async with aiohttp.ClientSession(headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0'}) as session:
            tasks = []
            for article in missing:
                tasks.append(_fetch_article_image_async(session, article['link']))
                
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for article, img in zip(missing, results):
                if isinstance(img, str) and img:
                    article['image_url'] = img

    def get_articles(self) -> list[dict]:
        return self.articles

    def get_health(self) -> list[dict]:
        """Returns health status of all scrapers."""
        return [s.get_health() for s in self.scrapers]
