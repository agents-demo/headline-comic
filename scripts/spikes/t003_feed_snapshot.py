"""Summarize downloaded T003 RSS snapshots and cluster near-duplicate titles."""

from __future__ import annotations

import email.utils
import json
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path


FEEDS = {
    "BBC": Path("/tmp/headline-comic-bbc.rss"),
    "The Guardian": Path("/tmp/headline-comic-guardian.rss"),
    "NPR": Path("/tmp/headline-comic-npr.rss"),
    "Ynet": Path("/tmp/headline-comic-ynet.rss"),
}
NOW = datetime.now(timezone.utc)


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def item_value(item: ET.Element, key: str) -> str:
    for child in item:
        if local_name(child.tag) == key:
            return " ".join("".join(child.itertext()).split())
    return ""


def parse_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalized_words(title: str) -> set[str]:
    folded = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    return set(re.findall(r"[a-z0-9]+", folded))


def similar(left: str, right: str) -> bool:
    a, b = normalized_words(left), normalized_words(right)
    if not a or not b:
        return False
    jaccard = len(a & b) / len(a | b)
    sequence = SequenceMatcher(None, " ".join(sorted(a)), " ".join(sorted(b))).ratio()
    return jaccard >= 0.30 or sequence >= 0.62


def main() -> None:
    candidates = []
    feed_stats = {}
    errors = {}
    for publisher, path in FEEDS.items():
        try:
            root = ET.parse(path).getroot()
            items = [node for node in root.iter() if local_name(node.tag) in ("item", "entry")]
            stories = []
            for item in items:
                title = item_value(item, "title")
                date = parse_date(item_value(item, "pubDate") or item_value(item, "published") or item_value(item, "updated"))
                link = item_value(item, "link")
                if not title or date is None:
                    continue
                stories.append({"publisher": publisher, "title": title, "published": date.isoformat(), "url": link})
            recent = [story for story in stories if NOW - timedelta(days=1) <= datetime.fromisoformat(story["published"]) <= NOW + timedelta(hours=1)]
            recent.sort(key=lambda story: story["published"], reverse=True)
            chosen = recent[:10]
            candidates.extend(chosen)
            feed_stats[publisher] = {"xml_items": len(items), "dated_items": len(stories), "last_24h": len(recent), "selected": len(chosen)}
        except Exception as exc:  # snapshot parsing diagnostics
            errors[publisher] = f"{type(exc).__name__}: {exc}"

    clusters: list[list[dict]] = []
    for story in candidates:
        matching = [group for group in clusters if any(similar(story["title"], member["title"]) for member in group)]
        if not matching:
            clusters.append([story])
        else:
            target = matching[0]
            target.append(story)
            for extra in matching[1:]:
                target.extend(extra)
                clusters.remove(extra)

    duplicate_clusters = [group for group in clusters if len({story["publisher"] for story in group}) > 1]
    print(json.dumps({
        "snapshot_utc": NOW.isoformat(),
        "feed_stats": feed_stats,
        "parse_errors": errors,
        "selected_candidates": len(candidates),
        "clusters": len(clusters),
        "multi_publisher_clusters": [
            {"publishers": sorted({story["publisher"] for story in group}), "titles": [story["title"] for story in group]}
            for group in duplicate_clusters
        ],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
