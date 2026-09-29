import logging
import os
import sys
import time

# Make sure src is in pythonpath
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

import nltk
from nltk.sentiment.vader import SentimentIntensityAnalyzer

from categories import classify_article
from database import Database
from pipeline.enrich import enrich_batch as _enrich_batch
from web_scraper import NewsAggregator

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("github_scrape")

NLTK_RESOURCES = [
    'tokenizers/punkt',
    'tokenizers/punkt_tab',
    'sentiment/vader_lexicon',
    'corpora/stopwords',
]

METADATA_BATCH = 2000


def ensure_nltk_data():
    """Download any missing NLTK resource, failing loudly if unavailable.

    nltk.download returns False on failure. Ignoring that meant a runner with
    no network sailed through here and hit LookupError 50 lines later, after
    add_articles and prune_old_articles had already committed.
    """
    for resource in NLTK_RESOURCES:
        try:
            nltk.data.find(resource)
        except LookupError as e:
            if not nltk.download(resource.split('/')[-1], quiet=True):
                raise RuntimeError(
                    f"NLTK resource unavailable: {resource}. The runner needs "
                    f"network access on first run, or a pre-populated nltk_data."
                ) from e


def estimate_read_time(title: str, excerpt: str = '') -> int:
    text = (excerpt or title).strip()
    word_count = len(text.split())
    if word_count > 80:
        return 7
    if word_count > 40:
        return 5
    if word_count > 20:
        return 4
    return 3


def build_metadata_rows(sia, articles, processed_at):
    """Compute sentiment/category/read_time for each article.

    A broken VADER lexicon must abort the run. Catching it and writing
    'neutral' stamped wrong data AND set metadata_processed_at, so those rows
    were never revisited and permanently skewed /api/stats.
    """
    rows = []
    for article in articles:
        title = article.get('title', '') or ''
        excerpt = article.get('excerpt', '') or ''

        scores = sia.polarity_scores(title)
        compound = scores['compound']
        if compound >= 0.05:
            label = 'positive'
        elif compound <= -0.05:
            label = 'negative'
        else:
            label = 'neutral'

        rows.append((
            label,
            compound,
            classify_article(title),
            estimate_read_time(title, excerpt),
            processed_at,
            article['id'],
        ))
    return rows


def write_metadata_batch(db, rows):
    """One connection and one executemany for the whole batch.

    update_article_metadata opens a fresh get_connection() per call, so this
    was up to 2000 sequential getconn/BEGIN/UPDATE/COMMIT/putconn round trips
    — the largest single chunk of the hourly run's wall clock.
    """
    if not rows:
        return
    with db.get_connection() as conn:
        ph = db._ph(len(rows))
        conn.cursor().executemany(
            f"UPDATE articles SET sentiment = {ph}, sentiment_score = {ph}, "
            f"category = {ph}, read_time = {ph}, metadata_processed_at = {ph} "
            f"WHERE id = {ph}",
            rows,
        )
        conn.commit()


def main():
    logger.info("Starting automated background scrape...")

    if not os.environ.get('DATABASE_URL'):
        logger.error("DATABASE_URL not set in environment!")
        sys.exit(1)

    # Database reads DATABASE_URL itself.  Do not pass a connection URI as the
    # SQLite fallback filename in case PostgreSQL is temporarily unavailable.
    db = Database()
    agg = NewsAggregator()

    t_scrape = time.perf_counter()
    agg.scrape_all(hn_pages=2, force=True)
    logger.info(f"Phase scrape took {time.perf_counter() - t_scrape:.1f}s.")
    new_articles = agg.get_articles()

    t_db = time.perf_counter()
    inserted = skipped = removed = 0
    if new_articles:
        logger.info(f"Enriching {len(new_articles)} articles with deep fetch...")
        t_enrich = time.perf_counter()
        new_articles = _enrich_batch(new_articles, fetch=True)
        logger.info(f"Phase enrich took {time.perf_counter() - t_enrich:.1f}s.")
        inserted, skipped = db.add_articles(new_articles)
        db.upsert_images(new_articles)
        logger.info(f"Inserted {inserted} new articles, skipped {skipped} duplicates.")

    # Prune and drain the metadata backlog on EVERY run, including a zero-article
    # one. prune_old_articles is the only thing that deletes rows, so exiting
    # early during a feed outage meant the table grew without bound while the
    # cron kept firing.
    try:
        retention = int(os.environ.get('RETENTION_DAYS', '2'))
    except ValueError:
        retention = 2
    removed = db.prune_old_articles(max_age_days=retention)
    logger.info(f"Pruned {removed} articles older than {retention}d.")
    logger.info(f"Phase db-write+prune took {time.perf_counter() - t_db:.1f}s.")

    if not new_articles:
        logger.error("Scraped 0 articles from all sources — failing loud so a dead feed turns the run red.")
        sys.exit(1)

    unprocessed = db.get_unprocessed_articles(limit=METADATA_BATCH)
    if unprocessed:
        # Lazy: only needed when there is metadata to compute.
        ensure_nltk_data()
        sia = SentimentIntensityAnalyzer()
        t_nlp = time.perf_counter()
        write_metadata_batch(db, build_metadata_rows(sia, unprocessed, time.time()))
        logger.info(
            f"Processed NLP metadata for {len(unprocessed)} articles in "
            f"{time.perf_counter() - t_nlp:.1f}s.")

    logger.info("Automated scrape complete.")


if __name__ == '__main__':
    main()
