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
import aiohttp
import asyncio

from utils.credibility import is_credible, score_article

logger = logging.getLogger(__name__)

EXCERPT_MAX_LEN = 280


def _parse_feed(url: str):
    """Wrapper around feedparser.parse with bozo logging."""
    feed = feedparser.parse(url)
    if getattr(feed, 'bozo', False):
        logger.warning(f"Feed {url} bozo: {getattr(feed, 'bozo_exception', '')}")
    return feed


def _is_valid_image_url(url: str) -> bool:
    """Filter out placeholders, 1x1, reddit defaults."""
    if not url or not str(url).startswith(("https://", "http://")):
        return False
    u = str(url).lower()
    # reddit placeholders
    if any(x in u for x in ["redditstatic", "self", "default", "placeholder", "1x1", "blank.gif"]):
        return False
    # must look like image
    if not re.search(r"\.(jpg|jpeg|png|webp|avif)(\?|$)", u) and "preview.redd.it" not in u and "i.redd.it" not in u:
        # allow og images without extension if from known hosts
        if not any(h in u for h in ["i.redd.it", "preview.redd.it", "cdn", "images", "media"]):
            # still allow if not obviously not image
            pass
    return True


def _extract_feed_image(entry) -> str:
    """Return the best image URL exposed by an RSS or Atom entry."""
    for field in ('media_content', 'media_thumbnail', 'enclosures'):
        for item in getattr(entry, field, []) or []:
            url = item.get('url') or item.get('href')
            if _is_valid_image_url(str(url)):
                return str(url).strip()

    for field in ('summary', 'description', 'content'):
        value = getattr(entry, field, '') or ''
        if isinstance(value, list):
            value = ' '.join(str(part.get('value', '')) for part in value)
        # collect all imgs, prefer largest (by url length heuristic)
        matches = re.findall(r'<img[^>]+src=[\"\']([^\"\']+)', str(value), re.IGNORECASE)
        for m in matches:
            import html as _html
            m = _html.unescape(m).strip()
            if _is_valid_image_url(m):
                return m
    return ''

def _clean_excerpt(text: str) -> str:
    """Strip HTML tags, normalize whitespace, truncate to EXCERPT_MAX_LEN."""
    if not text:
        return ""
    import html as _html
    # Remove HTML tags then decode entities properly
    text = re.sub(r'<[^>]+>', '', text)
    text = _html.unescape(text)
    # Strip HN raw URL patterns (Article URL: ..., Comments URL: ..., Points: ..., # Comments: ...)
    text = re.sub(r'Article URL:\s*https?://\S+', '', text)
    text = re.sub(r'Comments URL:\s*https?://\S+', '', text)
    text = re.sub(r'Points:\s*\d+', '', text)
    text = re.sub(r'#\s*Comments:\s*\d+', '', text)
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    # Truncate at word boundary (handle long token edge)
    if len(text) > EXCERPT_MAX_LEN:
        cut = text[:EXCERPT_MAX_LEN].rsplit(' ', 1)[0]
        text = (cut if cut else text[:EXCERPT_MAX_LEN]) + '…'
    return text


async def _fetch_article_image_async(session: aiohttp.ClientSession, url: str, sem: asyncio.Semaphore) -> str:
    """Fetch the top image from an article page via meta tags (bounded concurrency)."""
    async with sem:
        try:
            async with session.get(url, timeout=5) as response:
                if response.status != 200:
                    return ''
                # only parse html
                ct = response.headers.get("content-type", "")
                if "text/html" not in ct and "application/xhtml" not in ct:
                    return ''
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                # priority: og:image -> twitter:image -> og:image:secure_url
                for prop in ["og:image", "og:image:secure_url"]:
                    tag = soup.find('meta', property=prop)
                    if tag and tag.get('content') and _is_valid_image_url(tag['content']):
                        return str(tag['content']).strip()
                for name in ["twitter:image", "twitter:image:src"]:
                    tag = soup.find('meta', attrs={"name": name})
                    if tag and tag.get('content') and _is_valid_image_url(tag['content']):
                        return str(tag['content']).strip()
                # fallback: largest meaningful <img> (skip icons)
                best = ""
                best_len = 0
                for img in soup.find_all('img'):
                    src = (img.get('src') or img.get('data-src') or "").strip()
                    if not _is_valid_image_url(src):
                        continue
                    # skip tiny/icons by dimensions if present
                    try:
                        w = int(img.get('width') or 0)
                        h = int(img.get('height') or 0)
                        if w and w < 120:
                            continue
                        if h and h < 80:
                            continue
                    except:
                        pass
                    if len(src) > best_len:
                        best, best_len = src, len(src)
                return best
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
            feed = _parse_feed(self.feed_url)
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
            feed = _parse_feed(self.feed_url)
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
        # Reddit blocks generic UAs; use dedicated header
        self.session.headers.update({'User-Agent': 'SnifferBot/1.0 (tech news aggregator)'})

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
                    # Robust image: preview first (real post image), then thumbnail, then url if image
                    import html as _html
                    preview_url = ""
                    try:
                        preview_url = p_data.get('preview', {}).get('images', [{}])[0].get('source', {}).get('url', '')
                        if preview_url:
                            preview_url = _html.unescape(preview_url)
                    except Exception:
                        preview_url = ""
                    thumb = str(p_data.get('thumbnail', '') or "").strip()
                    link_url = str(p_data.get('url', '') or "").strip()
                    img = ""
                    if _is_valid_image_url(preview_url):
                        img = preview_url
                    elif _is_valid_image_url(thumb) and thumb not in ("self", "default", "nsfw", "spoiler", "image") and not thumb.endswith(".svg"):
                        # only keep thumb if it's http and not placeholder
                        if _is_valid_image_url(thumb):
                            img = thumb
                    elif _is_valid_image_url(link_url) and re.search(r"\.(jpg|jpeg|png|webp)(\?|$)", link_url, re.I):
                        img = link_url

                    articles.append({
                        'title': p_data.get('title'),
                        'link': p_data.get('url'),
                        'score': p_data.get('score', 0),
                        'author': p_data.get('author'),
                        'time': 'Today',
                        'comments': str(p_data.get('num_comments', 0)),
                        'source': 'Reddit',
                        'excerpt': excerpt,
                        'image_url': img if _is_valid_image_url(img) else "",
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
            feed = _parse_feed(self.feed_url)
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
            feed = _parse_feed(self.feed_url)
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


class GithubTrendingScraper(BaseScraper):
    """Scraper for GitHub Trending via Search API (JSON, paginated, rate-limited)."""

    def __init__(self) -> None:
        super().__init__()
        self.base_url = "https://api.github.com/search/repositories"
        # Use token if available to avoid 60 req/h limit
        import os
        token = os.getenv("GITHUB_TOKEN", "").strip()
        if token:
            self.session.headers.update({"Authorization": f"Bearer {token}"})
        self.session.headers.update({"Accept": "application/vnd.github.v3+json"})

    def scrape(self, num_pages: int = 1) -> list[dict]:
        start = time.time()
        articles = []
        logger.info("[GitHub] Starting API scrape...")
        try:
            # ponytail: 1 page = 20 repos, paginate via ?page= if needed
            for page in range(1, num_pages + 1):
                params = {
                    "q": "stars:>5000",
                    "sort": "stars",
                    "order": "desc",
                    "per_page": 20,
                    "page": page,
                }
                resp = self.session.get(self.base_url, params=params, timeout=10)
                # handle rate limit
                if resp.status_code == 403 and "rate limit" in resp.text.lower():
                    logger.warning(f"[GitHub] rate limited, remaining {resp.headers.get('X-RateLimit-Remaining')}")
                    break
                if resp.status_code != 200:
                    logger.warning(f"[GitHub] HTTP {resp.status_code}: {resp.text[:200]}")
                    break
                data = resp.json()
                for repo in data.get("items", [])[:20]:
                    excerpt = _clean_excerpt(repo.get("description") or "")
                    articles.append({
                        "title": f"{repo.get('full_name')}: {repo.get('description') or ''}".strip()[:200],
                        "link": repo.get("html_url"),
                        "score": repo.get("stargazers_count", 0),
                        "author": (repo.get("owner") or {}).get("login", "GitHub"),
                        "time": repo.get("updated_at", "Recent"),
                        "comments": str(repo.get("forks_count", 0)),
                        "source": "GitHub Trending",
                        "excerpt": excerpt,
                        "image_url": (repo.get("owner") or {}).get("avatar_url", ""),
                    })
                if len(data.get("items", [])) < 20:
                    break
                if page < num_pages:
                    time.sleep(1)
            self.last_status = "ok"
        except Exception as e:
            self.last_status = "error"
            self.last_error = str(e)
            logger.warning(f"[GitHub] Error: {e}")

        self.scrape_duration = time.time() - start
        self.last_scrape_time = time.time()
        logger.info(f"[GitHub] Done. {len(articles)} articles in {self.scrape_duration:.1f}s")
        return articles


class ArxivScraper(BaseScraper):
    """Scraper for arXiv CS papers via Atom API (XML, paginated)."""

    def __init__(self) -> None:
        super().__init__()
        self.base_url = "http://export.arxiv.org/api/query"

    def scrape(self, num_pages: int = 1) -> list[dict]:
        start = time.time()
        articles = []
        logger.info("[arXiv] Starting Atom scrape...")
        try:
            # ponytail: 1 page = 20 papers, paginate via start
            for page in range(num_pages):
                params = {
                    "search_query": "cat:cs.AI OR cat:cs.LG OR cat:cs.DC",
                    "sortBy": "submittedDate",
                    "sortOrder": "descending",
                    "start": page * 20,
                    "max_results": 20,
                }
                # feedparser handles Atom XML — encode properly
                import urllib.parse
                query = urllib.parse.urlencode(params, safe=":")
                url = f"{self.base_url}?{query}"
                feed = _parse_feed(url)
                if not feed.entries:
                    break
                for entry in feed.entries:
                    # arXiv authors are in entry.authors
                    author = "arXiv"
                    try:
                        if hasattr(entry, "authors") and entry.authors:
                            author = ", ".join(a.get("name", "") for a in entry.authors[:2])
                    except Exception:
                        pass
                    excerpt = _clean_excerpt(getattr(entry, "summary", "") or "")
                    link = getattr(entry, "link", "") or getattr(entry, "id", "")
                    # prefer arxiv abs link
                    if hasattr(entry, "id"):
                        link = entry.id
                    articles.append({
                        "title": getattr(entry, "title", "").replace("\n", " ").strip(),
                        "link": link,
                        "score": 0,
                        "author": author,
                        "time": getattr(entry, "published", "Recent"),
                        "comments": "0",
                        "source": "arXiv",
                        "excerpt": excerpt,
                        "image_url": "",  # arXiv has no images; will be enriched or fallback
                    })
                if len(feed.entries) < 20:
                    break
                if page < num_pages - 1:
                    time.sleep(1)
            self.last_status = "ok"
        except Exception as e:
            self.last_status = "error"
            self.last_error = str(e)
            logger.warning(f"[arXiv] Error: {e}")

        self.scrape_duration = time.time() - start
        self.last_scrape_time = time.time()
        logger.info(f"[arXiv] Done. {len(articles)} articles in {self.scrape_duration:.1f}s")
        return articles


class NewsAggregator:
    """Aggregates articles from all scrapers with caching and health tracking."""

    CACHE_TTL = 300  # 5 minutes

    def __init__(self, include_extra: bool = True) -> None:
        self.scrapers: list[BaseScraper] = [
            HackerNewsScraper(),
            TechCrunchScraper(),
            RedditScraper(),
            TheVergeScraper(),
            ArsTechnicaScraper(),
        ]
        if include_extra:
            # ponytail: 2 extra heterogeneous sources for variety (JSON+XML), disabled via SNIFFER_MINIMAL=1
            import os as _os
            if _os.getenv("SNIFFER_MINIMAL") != "1":
                self.scrapers.extend([GithubTrendingScraper(), ArxivScraper()])
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

        # Deduplicate by link across sources (keep first seen)
        seen = set()
        deduped = []
        for a in self.articles:
            link = a.get('link')
            if link and link not in seen:
                seen.add(link)
                deduped.append(a)
        self.articles = deduped

        # Async image enrichment (single event loop)
        await self._enrich_images_async()

        self._last_scrape_time = time.time()
        logger.info(f"Total articles scraped: {len(self.articles)}")

    def scrape_all(self, hn_pages: int = 1, force: bool = False) -> None:
        """Synchronous wrapper for backward compatibility."""
        asyncio.run(self.scrape_all_async(hn_pages, force))

    async def _enrich_images_async(self) -> None:
        """Fetch real images for articles missing image_url concurrently (bounded)."""
        missing = [a for a in self.articles if not a.get('image_url')]
        if not missing:
            return
        logger.info(f"Enriching images for {len(missing)} articles...")
        # ponytail: bounded concurrency to avoid socket exhaustion / 429
        sem = asyncio.Semaphore(8)
        async with aiohttp.ClientSession(headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0'}) as session:
            tasks = [_fetch_article_image_async(session, a['link'], sem) for a in missing]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for article, img in zip(missing, results):
                if isinstance(img, str) and img:
                    article['image_url'] = img

    def get_articles(self) -> list[dict]:
        return self.articles

    def get_health(self) -> list[dict]:
        """Returns health status of all scrapers."""
        return [s.get_health() for s in self.scrapers]
