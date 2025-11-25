from flask import Flask, render_template, request
from web_scraper import TechNewsScraper

app = Flask(__name__)

@app.route('/', methods=['GET', 'POST'])
def index():
    articles = []
    pages = 1
    keyword = ""

    if request.method == 'POST':
        try:
            pages = int(request.form.get('pages', 1))
            keyword = request.form.get('keyword', '').strip()
            
            # Initialize scraper
            scraper = TechNewsScraper()
            
            # Scrape data
            scraper.scrape_headlines(num_pages=pages)
            
            # Filter if keyword is provided
            if keyword:
                articles = scraper.filter_by_keyword(keyword)
            else:
                articles = scraper.articles
                
            # Sort by score descending
            articles = sorted(articles, key=lambda x: x['score'], reverse=True)
            
        except Exception as e:
            print(f"Error: {e}")

    return render_template('index.html', articles=articles, pages=pages, keyword=keyword)

if __name__ == '__main__':
    app.run(debug=True)