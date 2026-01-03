import requests
from bs4 import BeautifulSoup
import csv
import time
import sys
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor

class BaseScraper(ABC):
    """Abstract base class for all news scrapers."""
    
    def __init__(self) -> None:
        self.articles: list[dict] = []
        self.display_fields: list[str] = ['score', 'title', 'source']

    @abstractmethod
    def scrape(self, num_pages: int = 1) -> None:
        pass

    def get_articles(self) -> list[dict]:
        return self.articles

class HackerNewsScraper(BaseScraper):
    """Scraper for Hacker News."""
    
    def __init__(self) -> None:
        super().__init__()
        self.base_url: str = "https://news.ycombinator.com/news"

    def scrape(self, num_pages: int = 3) -> None:
        print(f"[HN] Starting scrape for {num_pages} pages...")
        for p in range(1, num_pages + 1):
            url = f"{self.base_url}?p={p}"
            html = self._fetch_url(url)
            if html:
                self._parse_html(html)
            if p < num_pages:
                time.sleep(1)
        print(f"[HN] Done. Collected {len(self.articles)} articles.")

    def _fetch_url(self, url: str) -> str | None:
        try:
            headers = {'User-Agent': 'Python TechScraper Project/2.0'}
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                return response.text
            return None
        except Exception as e:
            print(f"[HN] Error fetching {url}: {e}")
            return None

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
                            if comments == 'discuss': comments = "0"
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
            except AttributeError:
                continue

    def get_top_comment(self, article_link: str) -> str | None:
        """Fetches the top comment for a given HN story link."""
        # Note: Logic to find the specific item ID from the link might be tricky if it's external
        # But if we have the 'comments' link (from subtext), we can use that.
        # For now, let's assume we don't have the internal ID easily mapped unless we saved it.
        # TODO: Enhanced scraper could save the 'item?id=...' link as the 'comments_link'
        return None

class TechCrunchScraper(BaseScraper):
    """Scraper for TechCrunch."""
    
    def __init__(self) -> None:
        super().__init__()
        self.base_url: str = "https://techcrunch.com/"

    def scrape(self, num_pages: int = 1) -> None:
        # TechCrunch is harder to verify for pagination without JS for some layouts,
        # but the main page has latest stories.
        # simpler implementation: scrape main page only for now or use /category/technology/page/x
        
        print(f"[TC] Starting scrape...")
        # Scraping page 1 only for stability in this demo version
        url = self.base_url
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                # TechCrunch markup changes often, targeting standard article headers
                # Looking for h2 or h3 with links
                articles = soup.find_all('h3', class_='loop-card__title')
                if not articles:
                    articles = soup.select('.post-block__title a') # Backup selector

                for art in articles:
                    a_tag = art.find('a') if art.name != 'a' else art
                    if not a_tag: continue
                    
                    title = a_tag.text.strip()
                    link = a_tag['href']
                    
                    # Try to find author/time if possible (complex on TC without specific selectors)
                    # keeping it simple
                    
                    self.articles.append({
                        'title': title,
                        'link': link,
                        'score': 0, # TC doesn't have scores
                        'author': 'TechCrunch',
                        'time': 'Recent',
                        'comments': '0',
                        'source': 'TechCrunch'
                    })
        except Exception as e:
            print(f"[TC] Error: {e}")
        print(f"[TC] Done. Collected {len(self.articles)} articles.")

class RedditScraper(BaseScraper):
    """Scraper for r/technology using JSON API."""
    
    def __init__(self) -> None:
        super().__init__()
        self.base_url: str = "https://www.reddit.com/r/technology/top.json?t=day&limit=25"

    def scrape(self, num_pages: int = 1) -> None:
        print(f"[Reddit] Starting scrape...")
        try:
            headers = {'User-Agent': 'Python TechScraper Project/2.0'}
            # num_pages calculation is rough for JSON API, just doing one batch
            url = self.base_url
            response = requests.get(url, headers=headers, timeout=10)
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
                        'time': 'Today', # simplifying
                        'comments': str(p_data.get('num_comments', 0)),
                        'source': 'Reddit'
                    })
        except Exception as e:
            print(f"[Reddit] Error: {e}")
        print(f"[Reddit] Done. Collected {len(self.articles)} articles.")


class TheVergeScraper(BaseScraper):
    def __init__(self) -> None:
        super().__init__()
        self.base_url: str = "https://www.theverge.com/"

    def scrape(self, num_pages: int = 1) -> None:
        try:
            response = requests.get(self.base_url, headers=self.headers)
            if response.status_code != 200:
                print(f"Failed to fetch {self.base_url}")
                return

            soup = BeautifulSoup(response.text, 'html.parser')
            # The Verge uses h2 for article titles in the feed
            articles = soup.find_all('h2')

            count = 0
            for h2 in articles:
                if count >= 15: # Limit to top 15 to avoid clutter
                    break
                
                a_tag = h2.find('a')
                if not a_tag:
                    continue

                title = a_tag.get_text().strip()
                link = a_tag['href']
                
                # Fix relative URLs
                if link.startswith('/'):
                    link = f"https://www.theverge.com{link}"

                # Try to find container to locate metadata
                # Usually the h2 is inside a div or li which contains the author/time
                container = h2.find_parent('div') 
                if not container:
                    continue
                    
                # Author (look for link with /authors/)
                author_tag = container.find('a', href=lambda x: x and '/authors/' in x)
                author = author_tag.get_text().strip() if author_tag else "The Verge Staff"

                # Time (look for time tag)
                time_tag = container.find('time')
                time_str = time_tag.get_text().strip() if time_tag else "Recent"

                self.articles.append({
                    'title': title,
                    'link': link,
                    'score': 0, # No scores on Verge
                    'author': author,
                    'time': time_str,
                    'comments': '0', # Hard to scrape comments count easily
                    'source': 'The Verge'
                })
                count += 1
                
        except Exception as e:
            print(f"Error scraping The Verge: {e}")

class ArsTechnicaScraper(BaseScraper):
    def __init__(self) -> None:
        super().__init__()
        self.base_url: str = "https://arstechnica.com/"

    def scrape(self, num_pages: int = 1) -> None:
        try:
            response = requests.get(self.base_url, headers=self.headers)
            if response.status_code != 200:
                print(f"Failed to fetch {self.base_url}")
                return

            soup = BeautifulSoup(response.text, 'html.parser')
            # Ars Technica uses h2 for article titles
            articles = soup.find_all('h2')

            count = 0
            for h2 in articles:
                if count >= 15:
                    break
                
                a_tag = h2.find('a')
                if not a_tag or not a_tag.get('href'):
                    continue

                link = a_tag['href']
                # Skip if not an article link
                if not link.startswith('https://arstechnica.com/'):
                    continue

                title = a_tag.get_text().strip()
                
                # Find the parent article container
                container = h2.find_parent('article') or h2.find_parent('div')
                if not container:
                    continue

                # Author - look for byline or author class
                author_tag = container.find('a', href=lambda x: x and '/author/' in x) if container else None
                author = author_tag.get_text().strip() if author_tag else "Ars Staff"

                # Time
                time_tag = container.find('time') if container else None
                time_str = time_tag.get('datetime', time_tag.get_text()).strip() if time_tag else "Recent"

                self.articles.append({
                    'title': title,
                    'link': link,
                    'score': 0,
                    'author': author,
                    'time': time_str,
                    'comments': '0',
                    'source': 'Ars Technica'
                })
                count += 1
                
        except Exception as e:
            print(f"Error scraping Ars Technica: {e}")

class NewsAggregator:
    def __init__(self) -> None:
        self.scrapers: list[BaseScraper] = [
            HackerNewsScraper(),
            TechCrunchScraper(),
            RedditScraper(),
            TheVergeScraper(),
            ArsTechnicaScraper()
        ]
        self.articles: list[dict] = []


    def scrape_all(self, hn_pages: int = 1) -> None:
        """Runs all scrapers in parallel."""
        self.articles = []
        
        with ThreadPoolExecutor(max_workers=3) as executor:
            # HN gets variable pages, others get 1 for now
            executor.submit(self.scrapers[0].scrape, hn_pages)
            executor.submit(self.scrapers[1].scrape, 1)
            executor.submit(self.scrapers[2].scrape, 1) # Reddit
            
        # Collect results
        for scraper in self.scrapers:
            self.articles.extend(scraper.get_articles())
            
    def get_articles(self) -> list[dict]:
        return self.articles

    def filter_by_keyword(self, articles: list[dict], keyword: str) -> list[dict]:
        if not keyword: return articles
        return [art for art in articles if keyword.lower() in art['title'].lower()]

    def save_to_csv(self, filename: str = "tech_news.csv") -> None:
        if not self.articles:
            print("No data to save.")
            return

        try:
            with open(filename, mode='w', newline='', encoding='utf-8') as file:
                writer = csv.DictWriter(file, fieldnames=["title", "score", "link", "author", "time", "comments", "source"])
                writer.writeheader()
                writer.writerows(self.articles)
            print(f"Data successfully saved to {filename}")
        except Exception as e:
            print(f"Error saving file: {e}")

# Legacy support for main execution
def main() -> None:
    agg = NewsAggregator()
    print("Scraping all sources...")
    agg.scrape_all(hn_pages=2)
    
    # Sort by score for display
    sorted_arts = sorted(agg.articles, key=lambda x: x['score'] if isinstance(x['score'], int) else 0, reverse=True)
    
    print(f"\nTotal articles: {len(sorted_arts)}")
    print("-" * 80)
    print(f"{'SOURCE':<12} | {'SCORE':<5} | {'TITLE'}")
    print("-" * 80)
    
    for art in sorted_arts[:20]:
        print(f"{art['source'][:12]:<12} | {str(art['score']):<5} | {art['title'][:60]}")

if __name__ == "__main__":
    main()