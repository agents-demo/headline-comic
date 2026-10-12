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
from .article_text import (
    ArticleText,
    StoryRequest,
    build_articles_document,
    fetch_article_text,
    run as run_article_text,
    save_articles_document,
    story_request_from_candidate,
)

__all__ = [
    "ArticleText",
    "FeedSpec",
    "RawItem",
    "StoryRequest",
    "allowed_hosts_for",
    "build_articles_document",
    "build_candidates_document",
    "cluster_items",
    "fetch_article_text",
    "fetch_feed",
    "fetch_news",
    "load_feeds",
    "normalize_title",
    "parse_feed",
    "rank_clusters",
    "run_article_text",
    "save_articles_document",
    "save_candidates_document",
    "story_request_from_candidate",
]
