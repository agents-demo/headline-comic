"""Deterministic pipeline skills (pure-code stages)."""

from .news_fetch import (
    FeedSpec,
    RawItem,
    allowed_hosts_for,
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

__all__ = [
    "FeedSpec",
    "RawItem",
    "allowed_hosts_for",
    "build_candidates_document",
    "cluster_items",
    "fetch_feed",
    "fetch_news",
    "load_feeds",
    "normalize_title",
    "parse_feed",
    "rank_clusters",
    "save_candidates_document",
]
