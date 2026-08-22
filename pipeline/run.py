"""
Run — Sniffer one-command lake build
Usage: python pipeline/run.py  [--no-scrape]  [--day 2026/08/22]
Scrapes (if needed) → Bronze → validate → Silver → Gold (Spark if available else pandas)
"""
import argparse
import sys
from pathlib import Path

# ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.ingest import write_bronze_by_source
from pipeline.validate import validate_batch
from pipeline.enrich import enrich_batch
from pipeline.transform import to_silver, _read_bronze_day
from datetime import datetime, timezone


def _scrape(hn_pages=1, force=True):
    from web_scraper import NewsAggregator
    agg = NewsAggregator()
    agg.scrape_all(hn_pages=hn_pages, force=force)
    arts = agg.get_articles()
    # also load from sources.yaml if available (future 7 sources)
    try:
        import yaml
        cfg = yaml.safe_load(Path("configs/sources.yaml").read_text(encoding="utf-8"))
        # already covered by aggregator for now; yaml is for docs/config-driven claim
    except Exception:
        pass
    return arts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-scrape", action="store_true", help="reuse existing Bronze")
    ap.add_argument("--day", default=None, help="day partition YYYY/MM/DD")
    args = ap.parse_args()

    day = args.day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day = day.replace("/", "-")

    if not args.no_scrape:
        print("[run] scraping...")
        articles = _scrape()
        print(f"[run] scraped {len(articles)} articles")
        # ingest bronze
        out = write_bronze_by_source(articles)
        print(f"[run] bronze: {out}")
    else:
        articles = _read_bronze_day(day)
        print(f"[run] reusing bronze {day}: {len(articles)} rows")

    # validate
    if not args.no_scrape:
        valid, invalid = validate_batch(articles)
        print(f"[run] valid {len(valid)}/{len(articles)}, invalid {len(invalid)}")
        if invalid:
            Path("data/silver").mkdir(parents=True, exist_ok=True)
            Path("data/data_quality.log").write_text(
                "\n".join(str(x.get("_errors")) for x in invalid[:20]), encoding="utf-8"
            )
        articles = valid

    # enrich — dek + 3 bullets (free, offline)
    articles = enrich_batch(articles, fetch=False)
    print(f"[run] enriched {len(articles)} with dek/bullets")
    if articles and articles[0].get("dek"):
        print(f"  example dek: {articles[0]['dek'][:100]}")
        print(f"  bullets: {articles[0].get('bullets')}")

    # silver
    silver_path = to_silver(articles, day=day)
    print(f"[run] silver -> {silver_path}")

    # gold (try Spark, else pandas fallback)
    try:
        from processing.spark_job import run_gold
        gold_path = run_gold(day=day)
        print(f"[run] gold (spark) -> {gold_path}")
    except Exception as e:
        print(f"[run] spark gold failed ({e}), trying pandas fallback...")
        try:
            from processing.spark_job import run_gold_pandas
            gold_path = run_gold_pandas(day=day)
            print(f"[run] gold (pandas) -> {gold_path}")
        except Exception as e2:
            print(f"[run] gold failed: {e2}")
            gold_path = None

    print("[run] done.")


if __name__ == "__main__":
    main()
