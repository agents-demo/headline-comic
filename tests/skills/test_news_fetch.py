"""Tests for the deterministic news_fetch skill (T008)."""

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.permissions.media_guard import PolicyDenied
from src.skills.news_fetch import (
    FeedSpec,
    RawItem,
    build_candidates_document,
    cluster_items,
    fetch_feed,
    fetch_news,
    load_feeds,
    normalize_title,
    parse_feed,
    rank_clusters,
    save_candidates_document,
)

# --- fixture XML -----------------------------------------------------------

_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>Test</title>
  <item>
    <title>Global leaders agree on climate deal</title>
    <link>https://feeds.bbci.co.uk/a/1</link>
    <description>Leaders met today.</description>
    <pubDate>Sat, 12 Oct 2026 08:00:00 GMT</pubDate>
  </item>
  <item>
    <title>Local bakery wins national prize</title>
    <link>https://feeds.bbci.co.uk/b/2</link>
    <description>A small bakery won.</description>
    <pubDate>Sat, 12 Oct 2026 12:00:00 GMT</pubDate>
  </item>
</channel></rss>
"""

_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Tech firm unveils new phone</title>
    <link href="https://feeds.npr.org/c/3"/>
    <summary>New hardware announced.</summary>
    <published>2026-10-12T10:00:00Z</published>
  </entry>
</feed>
"""


class ParseTests(unittest.TestCase):
    def test_parse_rss_items(self) -> None:
        items = parse_feed(_RSS.encode(), "BBC")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].title, "Global leaders agree on climate deal")
        self.assertEqual(items[0].url, "https://feeds.bbci.co.uk/a/1")
        self.assertEqual(items[0].publisher, "BBC")
        self.assertEqual(items[0].published_at, datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc))

    def test_parse_atom_entry(self) -> None:
        items = parse_feed(_ATOM.encode(), "NPR")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "Tech firm unveils new phone")
        self.assertEqual(items[0].url, "https://feeds.npr.org/c/3")
        self.assertEqual(items[0].published_at, datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc))

    def test_skips_items_without_title_or_url(self) -> None:
        xml = b'<rss version="2.0"><channel><item><description>x</description></item></channel></rss>'
        self.assertEqual(parse_feed(xml, "BBC"), [])


class NormalizeTests(unittest.TestCase):
    def test_normalize_title(self) -> None:
        tokens = normalize_title("The World Leaders Agree on Climate!? Deal")
        self.assertEqual(tokens, frozenset({"world", "leaders", "agree", "climate", "deal"}))


class ClusterTests(unittest.TestCase):
    def _item(self, title: str, publisher: str = "BBC", url: str = "") -> RawItem:
        return RawItem(title=title, url=url or f"https://x/{title}", description="",
                       published_at=None, publisher=publisher)

    def test_near_identical_titles_cluster_together(self) -> None:
        items = [
            self._item("Global leaders agree on climate deal", "BBC", "https://x/1"),
            self._item("World leaders agree on climate deal", "NPR", "https://x/2"),
            self._item("Local bakery wins national prize", "BBC", "https://x/3"),
        ]
        clusters = cluster_items(items)
        self.assertEqual(len(clusters), 2)
        by_size = sorted((len(c) for c in clusters), reverse=True)
        self.assertEqual(by_size, [2, 1])

    def test_rank_by_coverage_then_recency(self) -> None:
        early = datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc)
        late = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
        mid = datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc)

        # A cluster covering two publishers must rank above either single-source one.
        shared = [
            RawItem("Global leaders agree on climate deal", "https://x/1", "", early, "BBC"),
            RawItem("World leaders agree on climate deal", "https://x/2", "", mid, "NPR"),
        ]
        b = [RawItem("Local bakery wins national prize", "https://x/3", "", late, "BBC")]
        c = [RawItem("Tech firm unveils new phone", "https://x/4", "", mid, "NPR")]

        ranked = rank_clusters([c, b, shared])
        self.assertEqual(ranked[0], shared)  # coverage 2
        self.assertEqual(ranked[1], b)       # single-source, more recent
        self.assertEqual(ranked[2], c)


class FetchNewsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bbc = _RSS.encode()
        self.npr = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<rss version="2.0"><channel>'
            '<item><title>World leaders agree on climate deal</title>'
            '<link>https://feeds.npr.org/x/1</link><description>d</description>'
            '<pubDate>Sat, 12 Oct 2026 09:00:00 GMT</pubDate></item>'
            '<item><title>Tech firm unveils new phone</title>'
            '<link>https://feeds.npr.org/x/2</link><description>d</description>'
            '<pubDate>Sat, 12 Oct 2026 10:00:00 GMT</pubDate></item>'
            '</channel></rss>'
        ).encode()
        self.feeds = [
            FeedSpec("BBC", "https://feeds.bbci.co.uk/news/world/rss.xml"),
            FeedSpec("NPR", "https://feeds.npr.org/1001/rss.xml"),
        ]

    def _fetcher(self):
        mapping = {
            self.feeds[0].url: self.bbc,
            self.feeds[1].url: self.npr,
        }
        return lambda url: mapping[url]

    def test_fetch_dedupes_and_ranks(self) -> None:
        candidates = fetch_news(self.feeds, fetcher=self._fetcher())
        # 4 raw items collapse to 3 clusters.
        self.assertEqual(len(candidates), 3)
        # The two-source climate story ranks first and picks the more recent source.
        self.assertEqual(candidates[0]["publisher"], "NPR")
        self.assertIn("climate deal", candidates[0]["title"].lower())
        # Remaining single-source stories order by recency.
        self.assertEqual(candidates[1]["title"], "Local bakery wins national prize")
        self.assertEqual(candidates[2]["title"], "Tech firm unveils new phone")

    def test_candidate_shapes_match_schema(self) -> None:
        candidates = fetch_news(self.feeds, fetcher=self._fetcher())
        required = {
            "candidate_id", "title", "url", "publisher", "published_at",
            "description", "source", "cluster_id", "safety_tags", "hidden_by_safety",
        }
        for candidate in candidates:
            self.assertEqual(set(candidate), required)
            self.assertEqual(candidate["source"], "rss")
            self.assertEqual(candidate["safety_tags"], [])
            self.assertIs(candidate["hidden_by_safety"], False)
            # published_at is an ISO 8601 date-time string.
            datetime.fromisoformat(candidate["published_at"])
            self.assertTrue(candidate["candidate_id"].startswith("c-"))
            self.assertTrue(candidate["cluster_id"].startswith("cl-"))

    def test_build_candidates_document_envelope(self) -> None:
        document = build_candidates_document([], generated_at=datetime(2026, 10, 12, tzinfo=timezone.utc))
        self.assertEqual(document["schema_version"], "1.0")
        self.assertEqual(document["generated_at"], "2026-10-12T00:00:00+00:00")
        self.assertEqual(document["candidates"], [])


class GuardAndSaveTests(unittest.TestCase):
    def test_fetch_feed_rejects_non_allowlisted_host(self) -> None:
        with self.assertRaises(PolicyDenied):
            fetch_feed("https://evil.example.com/rss", allowed_hosts={"feeds.bbci.co.uk"})

    def test_save_writes_inside_run_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = save_candidates_document(
                build_candidates_document([]),
                workspace_root=root,
                run_id="r1",
            )
            self.assertTrue(path.is_file())
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["candidates"], [])

    def test_save_refuses_outside_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Nothing here writes; the guard must reject before any I/O.
            with self.assertRaises(PolicyDenied):
                save_candidates_document(
                    build_candidates_document([]),
                    workspace_root=root,
                    run_id="../../escape",
                )


class ConfigTests(unittest.TestCase):
    def test_load_feeds_reads_active_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "feeds.json"
            config.write_text(json.dumps({
                "candidate_feeds": [
                    {"publisher": "BBC", "url": "https://feeds.bbci.co.uk/world/rss.xml", "status": "active"},
                    {"publisher": "Al Jazeera", "url": "https://www.aljazeera.com/xml/rss/all.xml", "status": "timeout"},
                ]
            }), encoding="utf-8")
            feeds = load_feeds(config)
            self.assertEqual([f.publisher for f in feeds], ["BBC"])


if __name__ == "__main__":
    unittest.main()
