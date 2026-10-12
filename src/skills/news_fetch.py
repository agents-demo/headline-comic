"""S1 fetch/deduplicate/rank: the ``news_fetch`` skill (FR-001).

Deterministic candidate-fetching code. It reads the confirmed RSS feed list,
fetches a pool of about 40 items, clusters near-identical stories by title, and
ranks clusters by cross-source coverage then recency. No model is called.

Tavily news search stays disabled (T003): RSS is the only candidate source.
Safety tagging belongs to T009 and is not done here; candidates leave untagged
and visible (``safety_tags == []``, ``hidden_by_safety == false``).
"""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable, Iterable, Sequence
from urllib import request
from urllib.parse import urlsplit

from src.permissions.media_guard import require_allowed_host, require_allowed_write_path

# --- tuning ---

TITLE_SIMILARITY_THRESHOLD = 0.5  # Jaccard over normalized title tokens
MAX_ITEMS_PER_FEED = 10  # 4 active feeds -> a pool of about 40 (FR-001)
HTTP_TIMEOUT_S = 10.0
MAX_FEED_BYTES = 2_000_000

_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
        "has", "have", "in", "is", "it", "its", "of", "on", "or", "that", "the",
        "to", "was", "were", "with",
    }
)

# Earliest usable timestamp; stands in for "no publish date" so sorting stays
# total and timezone-aware without touching datetime.min (which Windows rejects).
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

Fetcher = Callable[[str], bytes]


@dataclass(frozen=True)
class FeedSpec:
    publisher: str
    url: str


@dataclass(frozen=True)
class RawItem:
    title: str
    url: str
    description: str
    published_at: datetime | None
    publisher: str


def load_feeds(config_path: Path) -> list[FeedSpec]:
    """Return the active candidate feeds from the confirmed feed list."""

    data = json.loads(config_path.read_text(encoding="utf-8"))
    feeds: list[FeedSpec] = []
    for entry in data.get("candidate_feeds", []):
        if entry.get("status") != "active":
            continue
        publisher = entry.get("publisher")
        url = entry.get("url")
        if not publisher or not url:
            raise ValueError(f"Feed entry is missing publisher or url: {entry!r}")
        feeds.append(FeedSpec(publisher=str(publisher), url=str(url)))
    return feeds


def allowed_hosts_for(feeds: Sequence[FeedSpec]) -> frozenset[str]:
    """Return the exact HTTPS hostnames the configured feeds may be fetched from."""

    hosts: set[str] = set()
    for feed in feeds:
        host = urlsplit(feed.url).hostname
        if not host:
            raise ValueError(f"Configured feed URL has no hostname: {feed.url!r}")
        # Validate the URL is a clean HTTPS URL and normalize the host the same
        # way fetch_feed will, keeping allowlist logic in one place.
        hosts.add(require_allowed_host(feed.url, [host]))
    return frozenset(hosts)


def fetch_feed(url: str, *, allowed_hosts: Iterable[str], timeout: float = HTTP_TIMEOUT_S) -> bytes:
    """Fetch one feed over HTTPS after checking it against the host allowlist."""

    require_allowed_host(url, allowed_hosts)
    req = request.Request(url, headers={"User-Agent": "headline-comic/0.1 (demo)"})
    with request.urlopen(req, timeout=timeout) as resp:
        body = resp.read(MAX_FEED_BYTES + 1)
    if len(body) > MAX_FEED_BYTES:
        raise ValueError(f"Feed exceeds the size limit: {url}")
    return body


def _local(tag: str) -> str:
    """Strip an XML namespace prefix, keeping only the element local name."""

    return tag.rsplit("}", 1)[-1] if tag and "}" in tag else tag


def _child_text(node: ET.Element, *names: str) -> str | None:
    for child in node:
        if _local(child.tag) in names:
            text = (child.text or "").strip()
            if text:
                return text
    return None


def _item_url(node: ET.Element, kind: str) -> str | None:
    if kind == "entry":  # Atom link carries its href on an attribute
        for child in node:
            if _local(child.tag) == "link":
                href = child.get("href")
                if href:
                    return href.strip()
    return _child_text(node, "link", "guid")


def _parse_date(text: str) -> datetime | None:
    text = text.strip()
    if not text:
        return None
    try:
        parsed = parsedate_to_datetime(text)
        if parsed is not None:
            return _as_utc(parsed)
    except (ValueError, TypeError, OverflowError):
        pass
    try:  # ISO 8601 (Atom)
        return _as_utc(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_item(node: ET.Element, kind: str, publisher: str) -> RawItem | None:
    title = _child_text(node, "title")
    url = _item_url(node, kind)
    if not title or not url:
        return None
    description = _child_text(node, "description", "summary", "content") or ""
    published_at = _parse_date(_child_text(node, "pubDate", "published", "updated") or "")
    return RawItem(
        title=title,
        url=url,
        description=description,
        published_at=published_at,
        publisher=publisher,
    )


def parse_feed(xml_bytes: bytes, publisher: str) -> list[RawItem]:
    """Parse an RSS 2.0 or Atom feed into raw candidate items."""

    root = ET.fromstring(xml_bytes)
    items: list[RawItem] = []
    for node in root.iter():
        kind = _local(node.tag)
        if kind not in ("item", "entry"):
            continue
        item = _parse_item(node, kind, publisher)
        if item is not None:
            items.append(item)
    return items


def normalize_title(title: str) -> frozenset[str]:
    """Lowercase, strip punctuation, tokenize and drop stopwords for comparison."""

    text = re.sub(r"[^\w\s]", " ", title.lower())
    return frozenset(token for token in text.split() if token not in _STOPWORDS)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def cluster_items(
    items: Sequence[RawItem],
    threshold: float = TITLE_SIMILARITY_THRESHOLD,
) -> list[list[RawItem]]:
    """Group near-identical stories by title similarity (union-find, order-free)."""

    n = len(items)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    tokens = [normalize_title(item.title) for item in items]
    for i in range(n):
        for j in range(i + 1, n):
            if _jaccard(tokens[i], tokens[j]) >= threshold:
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[rj] = ri

    groups: dict[int, list[RawItem]] = {}
    for i, item in enumerate(items):
        groups.setdefault(find(i), []).append(item)
    return list(groups.values())


def _cluster_coverage(cluster: Sequence[RawItem]) -> int:
    return len({item.publisher for item in cluster})


def _cluster_recency_key(cluster: Sequence[RawItem]) -> float:
    times = [item.published_at for item in cluster if item.published_at is not None]
    return max(times).timestamp() if times else _EPOCH.timestamp()


def rank_clusters(clusters: Iterable[Sequence[RawItem]]) -> list[list[RawItem]]:
    """Rank clusters by cross-source coverage (desc), then recency (desc)."""

    return sorted(
        clusters,
        key=lambda c: (
            -_cluster_coverage(c),
            -_cluster_recency_key(c),
            min(item.url for item in c),  # deterministic tie-break
        ),
    )


def choose_representative(cluster: Sequence[RawItem]) -> RawItem:
    """Pick the most recent item as the cluster's representative candidate."""

    def sort_key(item: RawItem) -> tuple[float, str]:
        stamp = item.published_at.timestamp() if item.published_at else _EPOCH.timestamp()
        return (stamp, item.url)

    return max(cluster, key=sort_key)


def _short_id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]


def to_candidate(representative: RawItem, cluster: Sequence[RawItem], cluster_index: int) -> dict:
    """Map one ranked cluster to a candidates.schema.json candidate object."""

    published = representative.published_at or _EPOCH
    return {
        "candidate_id": "c-" + _short_id(representative.url),
        "title": representative.title,
        "url": representative.url,
        "publisher": representative.publisher,
        "published_at": published.isoformat(),
        "description": representative.description,
        "source": "rss",
        "cluster_id": f"cl-{cluster_index}",
        "safety_tags": [],
        "hidden_by_safety": False,
    }


def fetch_news(
    feeds: Sequence[FeedSpec],
    *,
    fetcher: Fetcher | None = None,
    max_items_per_feed: int = MAX_ITEMS_PER_FEED,
    threshold: float = TITLE_SIMILARITY_THRESHOLD,
) -> list[dict]:
    """Fetch, deduplicate and rank candidate stories into ranked candidate dicts."""

    allowed_hosts = allowed_hosts_for(feeds)
    do_fetch = fetcher if fetcher is not None else (lambda url: fetch_feed(url, allowed_hosts=allowed_hosts))

    pool: list[RawItem] = []
    for feed in feeds:
        items = parse_feed(do_fetch(feed.url), feed.publisher)
        pool.extend(items[:max_items_per_feed])

    ranked = rank_clusters(cluster_items(pool, threshold))
    return [to_candidate(choose_representative(c), c, idx) for idx, c in enumerate(ranked)]


def build_candidates_document(
    candidates: Sequence[dict],
    generated_at: datetime | None = None,
) -> dict:
    """Wrap ranked candidates in the candidates.schema.json document envelope."""

    return {
        "schema_version": "1.0",
        "generated_at": (generated_at or datetime.now(timezone.utc)).isoformat(),
        "candidates": list(candidates),
    }


def save_candidates_document(
    document: dict,
    *,
    workspace_root: Path,
    run_id: str,
) -> Path:
    """Write candidates.json into the run's own ``runs/<run-id>/`` directory."""

    path = require_allowed_write_path(
        workspace_root / "runs" / run_id / "candidates.json",
        workspace_root=workspace_root,
    )
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite existing candidates file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return path


def run(config_path: Path, *, fetcher: Fetcher | None = None) -> dict:
    """Load the confirmed feeds and produce the ranked candidates document."""

    feeds = load_feeds(config_path)
    candidates = fetch_news(feeds, fetcher=fetcher)
    return build_candidates_document(candidates)
