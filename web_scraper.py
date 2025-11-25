import requests
from bs4 import BeautifulSoup
import csv
import time
import sys

class TechNewsScraper:
    def __init__(self):
        # Base URL for the news page
        self.base_url = "https://news.ycombinator.com/news"
        self.articles = []

    def scrape_headlines(self, num_pages=3):
        """
        Scrapes multiple pages of Hacker News.
        num_pages: How many pages to scrape (default 3, approx 90 stories).
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

    def _fetch_url(self, url):
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

    def _parse_html(self, html_content):
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
                
                # 2. Get Score (from the subtext row below the title)
                metadata_row = row.find_next_sibling('tr')
                score_element = metadata_row.find('span', class_='score')
                
                if score_element:
                    score = int(score_element.text.split()[0])
                else:
                    score = 0
                
                # Append to the main list
                self.articles.append({
                    'title': title,
                    'link': link,
                    'score': score
                })
                found_on_page += 1
                
            except AttributeError:
                continue
                
        print(f"  -> Found {found_on_page} articles on this page.")

    def filter_by_keyword(self, keyword):
        """Filters the collected articles."""
        print(f"\nSearching {len(self.articles)} articles for: '{keyword}'")
        filtered = [
            art for art in self.articles 
            if keyword.lower() in art['title'].lower()
        ]
        return filtered

    def save_to_csv(self, filename="tech_news.csv"):
        """Saves all collected articles to CSV."""
        if not self.articles:
            print("No data to save.")
            return

        try:
            with open(filename, mode='w', newline='', encoding='utf-8') as file:
                writer = csv.DictWriter(file, fieldnames=["title", "score", "link"])
                writer.writeheader()
                writer.writerows(self.articles)
            print(f"Data successfully saved to {filename}")
        except Exception as e:
            print(f"Error saving file: {e}")

    def display_articles(self, articles_list):
        """Pretty prints a list of articles."""
        print("\n" + "-"*80)
        print(f"{'SCORE':<8} | {'TITLE'}")
        print("-"*80)
        
        if not articles_list:
            print("No articles found matching that criteria.")
        
        for art in articles_list:
            display_title = (art['title'][:70] + '..') if len(art['title']) > 70 else art['title']
            print(f"{str(art['score']):<8} | {display_title}")
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
        command = input("Enter keyword filter, 'save' to download, or 'q' to quit: ").strip().lower()
        
        if command == 'q':
            break
        elif command == 'save':
            scraper.save_to_csv()
        else:
            results = scraper.filter_by_keyword(command)
            scraper.display_articles(results)

if __name__ == "__main__":
    main()