import requests
from bs4 import BeautifulSoup
import csv
import time
import sys

class TechNewsScraper:
    def __init__(self) -> None:
        """Initializes the scraper with base URL and default settings."""
        # Base URL for the news page
        self.base_url: str = "https://news.ycombinator.com/news"
        self.articles: list[dict] = []
        # Default fields to display
        self.display_fields: list[str] = ['score', 'title']

    def scrape_headlines(self, num_pages: int = 3) -> None:
        """
        Scrapes multiple pages of Hacker News.

        Args:
            num_pages (int): How many pages to scrape (default 3, approx 90 stories).
        """
        print(f"Starting scrape for {num_pages} pages...")
        
        for p in range(1, num_pages + 1):
            # Construct the URL for specific pages (e.g., ?p=1, ?p=2)
            url = f"{self.base_url}?p={p}"
            print(f"Fetching page {p}...")
            
            html = self._fetch_url(url)
            if html:
                self._parse_html(html)
                
            # ETHICAL SCRAPING: Wait 1 second between requests to be polite to the server
            if p < num_pages:
                time.sleep(1)
        
        print(f"\nDone! Collected {len(self.articles)} total articles.")

    def _fetch_url(self, url: str) -> str | None:
        """Helper to download a single page."""
        try:
            headers = {'User-Agent': 'Python TechScraper Project/2.0'}
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                return response.text
            else:
                print(f"Failed to connect to {url}. Status: {response.status_code}")
                return None
        except Exception as e:
            print(f"Error fetching {url}: {e}")
            return None

    def _parse_html(self, html_content: str) -> None:
        """Parses the HTML and appends found stories to self.articles."""
        soup = BeautifulSoup(html_content, 'html.parser')
        story_rows = soup.find_all('tr', class_='athing')
        
        found_on_page = 0
        
        for row in story_rows:
            try:
                # 1. Get Title and Link
                title_element = row.find('span', class_='titleline').find('a')
                title = title_element.text
                link = title_element['href']
                
                # Fix relative links (e.g., "item?id=...")
                if not link.startswith('http'):
                    link = f"https://news.ycombinator.com/{link}"
                
                # 2. Get Metadata (Score, Author, Time, Comments)
                metadata_row = row.find_next_sibling('tr')
                subtext = metadata_row.find('td', class_='subtext')
                
                score = 0
                author = "Unknown"
                time_posted = "Unknown"
                comments = "0"

                if subtext:
                    # Score
                    score_elem = subtext.find('span', class_='score')
                    if score_elem:
                        score = int(score_elem.text.split()[0])
                    
                    # Author
                    author_elem = subtext.find('a', class_='hnuser')
                    if author_elem:
                        author = author_elem.text
                        
                    # Time
                    age_elem = subtext.find('span', class_='age')
                    if age_elem:
                        time_posted = age_elem.text
                        
                    # Comments
                    links = subtext.find_all('a')
                    for l in links:
                        if 'comment' in l.text:
                            comments = l.text.split()[0]
                            if comments == 'discuss': comments = "0"
                            break
                        if 'discuss' in l.text:
                            comments = "0"
                            break
                
                # Append to the main list
                self.articles.append({
                    'title': title,
                    'link': link,
                    'score': score,
                    'author': author,
                    'time': time_posted,
                    'comments': comments
                })
                found_on_page += 1
                
            except AttributeError:
                continue
                
        print(f"  -> Found {found_on_page} articles on this page.")

    def filter_by_keyword(self, keyword: str) -> list[dict]:
        """Filters the collected articles."""
        print(f"\nSearching {len(self.articles)} articles for: '{keyword}'")
        filtered = [
            art for art in self.articles 
            if keyword.lower() in art['title'].lower()
        ]
        return filtered

    def save_to_csv(self, filename: str = "tech_news.csv") -> None:
        """Saves all collected articles to CSV."""
        if not self.articles:
            print("No data to save.")
            return

        try:
            with open(filename, mode='w', newline='', encoding='utf-8') as file:
                writer = csv.DictWriter(file, fieldnames=["title", "score", "link", "author", "time", "comments"])
                writer.writeheader()
                writer.writerows(self.articles)
            print(f"Data successfully saved to {filename}")
        except Exception as e:
            print(f"Error saving file: {e}")

    def display_articles(self, articles_list: list[dict]) -> None:
        """Pretty prints a list of articles."""
        print("\n" + "-"*80)
        
        # Build header
        header_parts = []
        for field in self.display_fields:
            header_parts.append(field.upper())
        print(" | ".join(header_parts))
        print("-"*80)
        
        if not articles_list:
            print("No articles found matching that criteria.")
        
        for art in articles_list:
            row_parts = []
            for field in self.display_fields:
                val = str(art.get(field, 'N/A'))
                if field == 'title' and len(val) > 60:
                    val = val[:57] + "..."
                elif field == 'link' and len(val) > 40:
                    val = val[:37] + "..."
                row_parts.append(val)
            print(" | ".join(row_parts))
        print("-"*80 + "\n")

def main():
    scraper = TechNewsScraper()
    
    # ASK USER: How deep do you want to dig?
    try:
        pages = int(input("How many pages do you want to scrape? (1-10): ").strip())
        if pages > 10: pages = 10 # Cap it at 10 for safety
    except ValueError:
        pages = 3 # Default if they type nonsense
    
    # 1. Scrape multiple pages
    scraper.scrape_headlines(num_pages=pages)
    
    # 2. Show top 5 highest rated from the WHOLE batch
    print("\n--- TOP TRENDING ACROSS ALL PAGES ---")
    sorted_articles = sorted(scraper.articles, key=lambda x: x['score'], reverse=True)
    scraper.display_articles(sorted_articles[:5])
    
    # 3. Interactive Mode
    while True:
        command = input("Enter keyword filter, 'options' to configure view, 'save' to download, or 'q' to quit: ").strip().lower()
        
        if command == 'q':
            break
        elif command == 'save':
            scraper.save_to_csv()
        elif command == 'options':
            print("\nAvailable fields: title, link, score, author, time, comments")
            print(f"Current fields: {', '.join(scraper.display_fields)}")
            new_fields = input("Enter new fields (comma separated): ").strip().lower()
            if new_fields:
                # Validate and set
                valid_fields = ['title', 'link', 'score', 'author', 'time', 'comments']
                chosen = [f.strip() for f in new_fields.split(',') if f.strip() in valid_fields]
                if chosen:
                    scraper.display_fields = chosen
                    print(f"Updated display fields to: {scraper.display_fields}")
                else:
                    print("Invalid fields provided. Keeping current settings.")
        else:
            results = scraper.filter_by_keyword(command)
            scraper.display_articles(results)

if __name__ == "__main__":
    main()