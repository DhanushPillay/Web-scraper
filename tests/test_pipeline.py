"""
Automated Pytest Suite — Medallion Lakehouse Pipeline & Application Core
Comprehensive unit and integration tests covering:
- Declarative schema validation & quarantine routing
- Ingestion idempotency & SHA-256 fingerprinting
- Silver Snappy Parquet Hive partitioning & DuckDB SQL analytics
- Credibility scoring, FTS5 sanitization, personalized feed, and NLP read-time estimation.
"""
import json
import os
import sys

import pytest

# Ensure environment flags for isolated testing
os.environ["SNIFFER_NO_AUTO_INIT"] = "1"
sys.path.insert(0, os.path.abspath("src"))

from pipeline.ingest import generate_record_hash, write_bronze
from pipeline.transform import to_silver
from pipeline.validate import is_valid_url, validate_article_record, validate_batch
from processing.spark_job import run_gold_duckdb
from src.app import classify_article, is_safe_url
from src.database import Database
from utils.credibility import get_scorer
from web_scraper import _clean_excerpt


@pytest.fixture
def temp_lake_dir(tmp_path, monkeypatch):
    """Fixture providing isolated temporary directories for lake testing."""
    bronze = tmp_path / "bronze"
    silver = tmp_path / "silver"
    gold = tmp_path / "gold"
    quarantine = tmp_path / "quarantine"
    logs = tmp_path / "logs"

    monkeypatch.setattr("pipeline.ingest.BRONZE_ROOT", bronze)
    monkeypatch.setattr("pipeline.validate.QUARANTINE_ROOT", quarantine)
    monkeypatch.setattr("pipeline.validate.LOGS_ROOT", logs)
    monkeypatch.setattr("pipeline.transform.BRONZE_ROOT", bronze)
    monkeypatch.setattr("pipeline.transform.SILVER_ROOT", silver)
    monkeypatch.setattr("processing.spark_job.SILVER_ROOT", silver)
    monkeypatch.setattr("processing.spark_job.GOLD_ROOT", gold)

    return tmp_path


# -----------------------------------------------------------------------------
# 1. URL & Record Validation Tests
# -----------------------------------------------------------------------------
def test_url_validation():
    assert is_valid_url("https://techcrunch.com/article-1") is True
    assert is_valid_url("http://news.ycombinator.com/item?id=123") is True
    assert is_valid_url("ftp://invalid-protocol.com") is False
    assert is_valid_url("not-a-url") is False
    assert is_valid_url("") is False


def test_safe_url_security():
    assert not is_safe_url("http://localhost/test")
    assert not is_safe_url("http://127.0.0.1:8000")
    assert not is_safe_url("http://169.254.169.254/latest/meta-data/")
    assert is_safe_url("https://techcrunch.com/article")
    assert not is_safe_url("ftp://example.com/file")
    assert not is_safe_url("https://example.com:8080/")


def test_article_validation_valid():
    valid_record = {
        "title": "OpenAI Releases Next Generation Transformer Architecture",
        "link": "https://example.com/openai-transformer",
        "source": "TechCrunch",
        "score": 150,
    }
    errors = validate_article_record(valid_record)
    assert len(errors) == 0


def test_article_validation_invalid_rules():
    # Missing required field
    missing_title = {"link": "https://example.com/1", "source": "Hacker News"}
    assert any("missing_required_field: title" in e for e in validate_article_record(missing_title))

    # Short title
    short_title = {"title": "Short", "link": "https://example.com/2", "source": "Reddit"}
    assert any("title_too_short" in e for e in validate_article_record(short_title))

    # Negative score
    negative_score = {
        "title": "A Valid Long Article Title for Testing",
        "link": "https://example.com/3",
        "source": "Reddit",
        "score": -10,
    }
    assert any("negative_score" in e for e in validate_article_record(negative_score))


def test_validate_batch_and_quarantine():
    batch = [
        {"title": "Valid Article Title One With Length", "link": "https://example.com/1", "source": "Hacker News", "score": 10},
        {"title": "Too Short", "link": "https://example.com/2", "source": "Reddit", "score": 0},
        {"title": "Valid Article Title Two With Length", "link": "https://example.com/3", "source": "TechCrunch", "score": 50},
        {"title": "Duplicate Link Record", "link": "https://example.com/1", "source": "Hacker News", "score": 20},
    ]
    valid, quarantined, metrics = validate_batch(batch, day="2026-08-22")

    assert len(valid) == 2
    assert len(quarantined) == 2
    assert metrics["data_quality_pass_rate_percent"] == 50.0
    assert metrics["total_records_evaluated"] == 4


# -----------------------------------------------------------------------------
# 2. Ingestion & Idempotency Tests
# -----------------------------------------------------------------------------
def test_deterministic_hashing():
    h1 = generate_record_hash("https://example.com/test", "Hacker News")
    h2 = generate_record_hash("https://example.com/test", "Hacker News")
    h3 = generate_record_hash("https://example.com/different", "Hacker News")

    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 64


def test_bronze_idempotent_writes(temp_lake_dir):
    records = [
        {"title": "Article Number One Long Title", "link": "https://example.com/1", "source": "HN", "score": 10},
        {"title": "Article Number Two Long Title", "link": "https://example.com/2", "source": "HN", "score": 20},
    ]
    out_file = write_bronze(records, source="HN", day="2026-08-22")
    assert out_file.exists()
    lines_first = out_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines_first) == 2

    # Second write with same records
    write_bronze(records, source="HN", day="2026-08-22")
    lines_second = out_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines_second) == 2


# -----------------------------------------------------------------------------
# 3. Silver & Gold Layer Analytical Tests
# -----------------------------------------------------------------------------
def test_classification():
    assert classify_article("OpenAI releases GPT-5 with transformer") == "AI & ML"
    assert classify_article("New quantum chip from Intel") == "Hardware"
    assert classify_article("Air quality improves in city") != "AI & ML"


def test_lakehouse_end_to_end(temp_lake_dir):
    import duckdb

    test_articles = [
        {"title": "Breakthrough in Generative LLMs and AI", "link": "https://example.com/ai-1", "source": "Hacker News", "score": 100, "sentiment_score": 0.8},
        {"title": "Critical Security Breach Patched in Cloud Provider", "link": "https://example.com/sec-1", "source": "TechCrunch", "score": 75, "sentiment_score": -0.5},
        {"title": "High Performance Computing GPU Benchmarks", "link": "https://example.com/hw-1", "source": "Ars Technica", "score": 40, "sentiment_score": 0.2},
    ]

    # Transform to Silver Parquet
    silver_path = to_silver(test_articles, day="2026-08-22")
    assert silver_path is not None

    # Verify Silver via DuckDB
    con = duckdb.connect(database=":memory:")
    pattern = f"{str(silver_path).replace('\\', '/')}/**/*.parquet"
    count = con.execute(f"SELECT count(*) FROM read_parquet('{pattern}', hive_partitioning=1)").fetchone()[0]
    assert count == 3

    # Run Gold Analytics Marts
    gold_dir = run_gold_duckdb(day="2026-08-22")
    assert (gold_dir / "category_metrics.parquet").exists()
    assert (gold_dir / "daily_stats.json").exists()

    stats = json.loads((gold_dir / "daily_stats.json").read_text(encoding="utf-8"))
    assert stats["total_articles"] == 3
    assert "AI & ML" in stats["by_category"]


# -----------------------------------------------------------------------------
# 4. Utilities & Database Core Tests
# -----------------------------------------------------------------------------
def test_excerpt_cleaning():
    assert _clean_excerpt("<p>Hello &amp; world</p>") == "Hello & world"
    t = "word " * 100
    assert len(_clean_excerpt(t)) <= 281


def test_credibility_boundaries():
    s = get_scorer()
    _, d1 = s.score("New secretary appointed", "https://example.com/a")
    _, d2 = s.score("Secret revealed in leaked report", "https://example.com/b")
    assert d1["title_penalty"] < d2["title_penalty"]




def test_fts_and_database_operations(tmp_path):
    db_path = str(tmp_path / "test_sniffer.db")
    db = Database(db_path)

    # Sanitize FTS
    assert db._sanitize_fts_query('hello OR "world" *') != ""
    assert db._sanitize_fts_query("   ") == ""

    # Add articles
    db.add_articles([{
        "title": "Quantum Computing Breakthrough",
        "link": "https://example.com/quantum",
        "source": "Hacker News",
        "author": "Researcher",
        "time": "Today",
        "comments": "12",
        "excerpt": "A major breakthrough in quantum computing.",
        "image_url": "",
        "score": 100,
    }])

    # Search
    results = db.search_articles("Quantum", limit=5)
    assert isinstance(results, list)
    assert len(results) >= 1

    # Bookmarking & Personalized feed
    arts = db.get_articles(limit=1)
    assert len(arts) > 0
    db.toggle_bookmark(arts[0]["id"])

    feed = db.get_personalized_feed(limit=5)
    assert isinstance(feed, list)


# -----------------------------------------------------------------------------
# Honest worker accounting (green CI must mean real work)
# -----------------------------------------------------------------------------
def _article(link, title="T"):
    return {"title": title, "link": link, "source": "HN", "excerpt": "x"}


def test_add_articles_honest_counts(tmp_path):
    db = Database(str(tmp_path / "counts.db"))
    assert db.add_articles([_article("https://e.com/1"), _article("https://e.com/2")]) == (2, 0)
    assert db.get_article_count() == 2
    # Identical re-insert: nothing new, count unchanged.
    assert db.add_articles([_article("https://e.com/1"), _article("https://e.com/2")]) == (0, 2)
    assert db.get_article_count() == 2
    # Mixed batch reports the exact split.
    assert db.add_articles([_article("https://e.com/2"), _article("https://e.com/3")]) == (1, 1)
    assert db.get_article_count() == 3
    assert db.add_articles([]) == (0, 0)


def test_add_articles_drops_linkless_rows_without_losing_the_batch(tmp_path):
    """A row with no link can never satisfy link TEXT UNIQUE NOT NULL.

    Its presence used to abort the whole executemany, and the failure was
    reported as (0, len(articles)) — indistinguishable from "all duplicates".
    """
    db = Database(str(tmp_path / "linkless.db"))
    batch = [
        _article("https://e.com/ok1", "Good one"),
        {"title": "No link", "source": "Reddit", "excerpt": "x"},
        _article("https://e.com/ok2", "Good two"),
    ]
    inserted, skipped = db.add_articles(batch)
    assert (inserted, skipped) == (2, 1)
    assert db.get_article_count() == 2
    titles = {a["title"] for a in db.get_articles(limit=10)}
    assert titles == {"Good one", "Good two"}
    # An all-linkless batch inserts nothing rather than raising.
    assert db.add_articles([{"title": "still no link"}]) == (0, 0)


def test_add_articles_raises_on_db_error(tmp_path, monkeypatch):
    """A failed insert must not masquerade as (0, N)."""
    db = Database(str(tmp_path / "boom.db"))

    def _explode(*a, **k):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(db, "get_connection", _explode)
    with pytest.raises(RuntimeError):
        db.add_articles([_article("https://e.com/x")])


def test_keyword_like_wildcards_are_escaped(tmp_path):
    """`_` is a LIKE wildcard; unescaped it matched the whole table and made
    the pager report the wrong page count."""
    db = Database(str(tmp_path / "like.db"))
    db.add_articles([
        {"title": "React hooks deep dive", "link": "https://e.com/1", "source": "HN"},
        {"title": "Postgres index tuning", "link": "https://e.com/2", "source": "HN"},
        {"title": "snake_case naming explained", "link": "https://e.com/3", "source": "HN"},
    ])
    assert len(db.get_articles(keyword="_", limit=10)) == 1
    assert db.get_total_count(keyword="_") == 1
    assert db.get_articles(keyword="%", limit=10) == []
    assert db.get_articles(keyword="React", limit=10)[0]["title"] == "React hooks deep dive"


def test_toggle_flag_treats_null_as_unset(tmp_path):
    """`not None` is True, so a NULL column used to read as "saved"."""
    db = Database(str(tmp_path / "toggle.db"))
    db.add_articles([_article("https://e.com/1")])
    aid = db.get_articles(limit=1)[0]["id"]
    with db.get_connection() as conn:
        conn.execute(f"UPDATE articles SET is_saved = NULL WHERE id = {db._ph(1)}", (aid,))
        conn.commit()
    assert db.toggle_bookmark(aid) is True
    assert db.toggle_bookmark(aid) is False
    assert db.toggle_read(aid) is True
    assert db.toggle_read(99999) is None


def test_gold_stats_read_one_mart(tmp_path, monkeypatch):
    """The old data/gold/** glob spanned three incompatible schemas.

    DuckDB bound the alphabetically-first file and raised BinderException,
    which a bare `except Exception: pass` swallowed — so Gold stats were
    permanently unreachable from the dashboard.
    """
    from datetime import datetime, timezone

    import pandas as pd

    import src.app as web

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    gold = tmp_path / "data" / "gold" / today
    gold.mkdir(parents=True)
    # Decoy mart with a completely different schema and an alphabetically
    # earlier name than source_metrics.parquet.
    pd.DataFrame({"category": ["AI & ML"], "count": [99]}).to_parquet(gold / "a_category.parquet")
    pd.DataFrame({"title": ["t"], "link": ["l"], "source": ["HN"], "category": ["c"],
                  "score": [1], "category_rank": [1]}).to_parquet(gold / "b_top.parquet")
    pd.DataFrame({"source": ["Hacker News", "Reddit"],
                  "total_articles": [30, 20]}).to_parquet(gold / "source_metrics.parquet")

    monkeypatch.chdir(tmp_path)
    web._stats_cache["data"] = None
    web._stats_cache["ts"] = 0
    stats = web._get_gold_stats()
    assert stats is not None, "Gold stats must not be swallowed"
    assert stats["by_source"] == {"Hacker News": 30, "Reddit": 20}
    assert stats["total"] == 50
    # The 60s cache must wrap the Gold lookup, not sit below it.
    web.get_cached_stats()
    first = web._stats_cache["data"]
    (tmp_path / "data" / "gold" / today / "source_metrics.parquet").unlink()
    assert web.get_cached_stats() == first


def test_ingest_survives_a_corrupt_line(tmp_path, monkeypatch):
    """One unparseable line used to discard the whole partition's hash set,
    so every record was re-appended. And a crash mid-append left a line with
    no trailing newline, which the next append concatenated onto."""
    from pipeline import ingest
    monkeypatch.setattr(ingest, "BRONZE_ROOT", tmp_path / "bronze")

    recs = [{"title": f"T{i}", "link": f"https://e.com/{i}", "source": "HN"} for i in range(3)]
    ingest.write_bronze(recs, source="HN", day="2026-01-01")
    part = tmp_path / "bronze" / "2026-01-01" / "HN.jsonl"
    lines = part.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    part.write_text(
        lines[0] + "\n" + '{"record_hash": "truncated", "tit' + "\n" + lines[2] + "\n",
        encoding="utf-8")

    # The third record must still be recognised as already ingested. The corrupt
    # line is kept (only its hash is skipped) so it does not lose data.
    ingest.write_bronze(recs, source="HN", day="2026-01-01")
    raw = part.read_text(encoding="utf-8").splitlines()
    valid = []
    for line in raw:
        if not line.strip():
            continue
        try:
            valid.append(json.loads(line))
        except ValueError:
            continue
    assert len(raw) == 4, f"a valid record was re-appended: {raw}"
    assert len(valid) == 3, f"partition re-appended after a corrupt line: {len(valid)}"
    assert {v["link"] for v in valid} == {r["link"] for r in recs}

    # Truncated final line: the next append must not concatenate onto it.
    part.write_text('{"record_hash": "aaa", "ti', encoding="utf-8")
    ingest.write_bronze([{"title": "New", "link": "https://e.com/new", "source": "HN"}],
                        source="HN", day="2026-01-01")
    tail = part.read_text(encoding="utf-8")
    assert '"record_hash": "aaa", "ti\n' in tail
    assert '"https://e.com/new"' in tail
    good = []
    for line in tail.splitlines():
        if not line.strip():
            continue
        try:
            good.append(json.loads(line))
        except ValueError:
            continue
    assert {"https://e.com/new"}.issubset({g.get("link") for g in good})


def test_silver_repeat_writes_are_idempotent(temp_lake_dir):
    """overwrite_or_ignore does not overwrite; pyarrow writes a new file per
    call, so a re-run tripled every partition's rows."""
    from pipeline.ingest import write_bronze
    from pipeline.transform import read_bronze_records
    from processing.spark_job import run_gold_duckdb

    day = "2026-01-02"
    recs = [{"title": f"S{i}", "link": f"https://e.com/{i}", "source": "HN",
             "score": i, "category": "AI & ML", "excerpt": "body"} for i in range(3)]
    write_bronze(recs, day=day)
    for _ in range(3):
        to_silver(read_bronze_records(day=day), day=day)
    import duckdb
    n = duckdb.query(
        f"SELECT count(*) FROM read_parquet('{temp_lake_dir / 'silver'}/**/*.parquet', hive_partitioning=1)"
    ).fetchone()[0]
    assert n == 3, f"expected 3 rows after 3 identical runs, got {n}"
    out = run_gold_duckdb(day=day)
    assert json.loads((out / "daily_stats.json").read_text(encoding="utf-8"))["total_articles"] == 3


def test_gold_refuses_to_fall_back_to_bronze(temp_lake_dir):
    """The Bronze fallback defaulted every row to category="general" and logged
    success, producing a valid-looking but wrong category mart."""
    from pipeline.ingest import write_bronze
    from processing.spark_job import run_gold

    day = "2026-01-03"
    write_bronze([{"title": "Raw bronze", "link": "https://e.com/b", "source": "HN"}], day=day)
    with pytest.raises(ValueError):
        run_gold(day=day)


def test_enrich_never_repeats_the_dek_as_a_bullet():
    """A 4+ char token floor made Jaccard 0.0 on sparse sentences, so bullet
    #1 was the dek for most Reddit posts and arXiv abstracts."""
    from pipeline.enrich import enrich_article
    out = enrich_article({
        "title": "Council approves the budget",
        "link": "https://e.com/c",
        "excerpt": "The council met on Monday. They approved a new budget for the coming year.",
    })
    assert out["dek"] not in out["bullets"]
    assert out["bullets"] and len(out["bullets"]) <= 3


def test_canonical_link_keeps_meaningful_params():
    from pipeline.ingest import canonical_link as cl
    # A real .com TLD must survive www-stripping.
    assert cl("https://www.com/x") == "https://www.com/x"
    assert cl("https://www.example.com/x") == "https://example.com/x"
    # Param order must not create two records for one article.
    assert cl("https://e.com/x?b=2&a=1") == cl("https://e.com/x?a=1&b=2")
    # Valueless params used to be dropped entirely.
    assert "page" in cl("https://e.com/x?a=1&page")
    # A real id must NOT be stripped.
    assert "id=123" in cl("https://e.com/x?id=123")
    assert "utm_" not in cl("https://e.com/x?utm_source=rss&id=1")


def test_validate_batch_survives_non_dict_records():
    """canonical_link(str(record.get(...))) crashed the whole batch on any
    non-dict, even though validate_article_record handles that case."""
    valid, quarantined, metrics = validate_batch([
        {"title": "A real headline", "link": "https://e.com/1", "source": "HN", "score": 1},
        "a bare string",
        ["a", "list"],
    ], day="2026-01-04")
    assert len(valid) == 1
    assert len(quarantined) == 2
    assert metrics["status"] in ("PASS", "WARNING")


def test_health_helpers():
    from src.app import is_safe_url, payload_str, sanitize_keyword
    # urlparse().port raises on these; is_safe_url must return False, not raise.
    assert is_safe_url("http://example.com:99999/") is False
    assert is_safe_url("http://example.com:abc/") is False
    assert is_safe_url("http://example.com:0/") is False
    assert is_safe_url("https://example.com/x") is True
    # A rejected keyword must be None so the caller can 400; '' would drop the
    # WHERE clause and serve the entire unfiltered feed.
    assert sanitize_keyword("ok query") == "ok query"
    assert sanitize_keyword("50% off") is None
    assert sanitize_keyword("") == ""
    # A non-string field is treated as absent, never coerced.
    assert payload_str({"url": 123}, "url") == ""
    assert payload_str({"url": None}, "url") == ""
    assert payload_str({}, "url") == ""
    assert payload_str({"url": "  https://e.com  "}, "url") == "https://e.com"


def test_email_digest_requires_opt_in():
    from src.app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        r = c.post("/api/email/digest", json={"email": "someone@example.com"})
    assert r.status_code == 403
    app.config["TESTING"] = False


def test_rate_limit_response_sends_retry_after():
    """flask-limiter 3.8 never populates e.retry_after, so the 429 body was
    {"retry_after": null} with no Retry-After header at all."""
    from src.app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        last = None
        for _ in range(15):
            last = c.post("/subscribe", json={"email": "a@b.com"})
            if last.status_code == 429:
                break
    assert last is not None and last.status_code == 429, "limit was never reached"
    assert last.headers.get("Retry-After"), "429 must carry a Retry-After header"
    assert last.get_json()["retry_after"]
    app.config["TESTING"] = False


def test_require_postgres_flag_fails_fast(tmp_path, monkeypatch):
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda s: None)
    monkeypatch.setenv("DATABASE_URL", "postgresql://127.0.0.1:1/db")
    monkeypatch.setenv("SNIFFER_REQUIRE_POSTGRES", "1")
    with pytest.raises(RuntimeError):
        Database(str(tmp_path / "never.db"))


def test_zero_scrape_fails_loud(monkeypatch):
    import importlib.util
    path = os.path.join(os.path.dirname(__file__), "..", "scripts", "github_scrape.py")
    spec = importlib.util.spec_from_file_location("github_scrape", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    class _EmptyAgg:
        def scrape_all(self, **kw):
            pass

        def get_articles(self):
            return []

    class _Db:
        pruned = []

        def prune_old_articles(self, max_age_days):
            self.pruned.append(max_age_days)
            return 7

        def add_articles(self, *a, **k):
            raise AssertionError("must not insert when there are no articles")

        def get_unprocessed_articles(self, *a, **k):
            raise AssertionError("must not process metadata on a zero run")

    db = _Db()
    monkeypatch.setattr(mod, "NewsAggregator", _EmptyAgg)
    monkeypatch.setattr(mod, "Database", lambda *a, **k: db)
    monkeypatch.setattr(mod, "ensure_nltk_data", lambda: None)
    monkeypatch.setattr(mod, "SentimentIntensityAnalyzer", lambda *a, **k: None)
    monkeypatch.setenv("DATABASE_URL", "postgresql://dummy/dummy")
    with pytest.raises(SystemExit) as e:
        mod.main()
    assert e.value.code == 1
    # Retention must still run on a zero-article run: it is the only thing
    # that deletes rows, so exiting before it grew the table without bound.
    assert db.pruned == [2]


def test_credibility_csv_loads():
    """The CSV lives at the repo root, but the module is src/utils/, so a
    path derived from __file__ missed it and every domain scored the
    default 50 — silently disabling domain credibility everywhere except
    the Docker layout that happened to have /app/data/."""
    from src.utils.credibility import CredibilityScorer
    scorer = CredibilityScorer()
    assert len(scorer.domain_scores) > 50, (
        "credibility CSV not found - the scorer is running on defaults only"
    )
    assert scorer.domain_scores["techcrunch.com"]["score"] > 0


def test_canonical_link_rejects_non_strings():
    """A BeautifulSoup Tag reaches canonical_link when a scraper shadows its
    link variable. Tag.__getattr__ returns None for '.strip', so the old
    `(link or "").strip()` raised "TypeError: 'NoneType' object is not
    callable" and aborted the whole scrape."""
    from bs4 import BeautifulSoup
    from pipeline.ingest import canonical_link
    tag = BeautifulSoup('<a href="x">y</a>', "html.parser").find("a")
    assert canonical_link(tag) == ""
    assert canonical_link(None) == ""
    assert canonical_link(12345) == ""
    assert canonical_link("  https://e.com/a/  ") == "https://e.com/a"


def test_hn_html_fallback_link_is_not_a_soup_tag():
    """Regression: the comment-link loop reused the name `link`, shadowing
    the article URL, so every HN story parsed through the HTML fallback got a
    bs4 Tag as its link and the scrape crashed in the dedup pass."""
    from web_scraper import HackerNewsScraper
    html = """
    <table><tr class="athing" id="1">
      <td><span class="titleline"><a href="https://example.com/story">Story title</a></span></td>
    </tr><tr>
      <td class="subtext">
        <span class="score">42 points</span>
        <a class="hnuser" href="user?id=x">someuser</a>
        <span class="age">2 hours ago</span>
        <a href="item?id=1">17&nbsp;comments</a>
      </td>
    </tr></table>
    """
    scraper = HackerNewsScraper()
    articles = scraper._parse_html(html)
    assert len(articles) == 1
    assert articles[0]["link"] == "https://example.com/story"
    assert isinstance(articles[0]["link"], str)
    assert articles[0]["comments"] == "17"


def test_scrapers_report_error_on_empty_result():
    """A feed that returns 200 with 0 entries (arXiv 429 "Rate exceeded." was
    parsed as a syntax error, Reddit 403, a dead RSS feed) must not report
    `ok` — that is how a dead source stayed green in get_health()."""
    from web_scraper import RssScraper

    _EMPTY_RSS = b'<?xml version="1.0"?><rss version="2.0"><channel/></rss>'
    _ONE_RSS = (
        b'<?xml version="1.0"?><rss version="2.0"><channel>'
        b"<item><title>T</title><link>https://e.com/1</link>"
        b"<description>s</description></item></channel></rss>"
    )

    class _Body:
        def __init__(self, raw):
            self.content = raw

        def raise_for_status(self):
            pass

    class _Dead(RssScraper):
        def __init__(self):
            super().__init__()
            self.feed_url = "https://example.invalid/feed"
            self.source = "Dead"
            self.tag = "Dead"

    rss = _Dead()
    rss.session.get = lambda *a, **k: _Body(_EMPTY_RSS)
    assert rss.scrape() == []
    assert rss.last_status == "error", "empty RSS feed must not report ok"
    assert "0 entries" in rss.last_error

    # A 200 with entries still reports ok and clears any stale error.
    alive = _Dead()
    alive.last_error = "stale"
    alive.session.get = lambda *a, **k: _Body(_ONE_RSS)
    assert len(alive.scrape()) == 1
    assert alive.last_status == "ok"
    assert alive.last_error == ""
