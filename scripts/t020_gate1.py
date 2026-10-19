"""T020 Gate 1 validation: run the text half on three days of real news.

Fetches the confirmed RSS feeds, buckets their items by publish date, selects the
three most-recent well-populated days, picks five distinct stories per day, pulls
all fifteen articles in ONE Tavily Extract batch, then runs the S2-S9 text half
(ledger -> summaries -> story -> storyboard -> checks -> verifier -> approval)
for each day with per-day wall-clock timing. Finally it prints a gate summary:
per-day time, Tavily credits, and a deterministic SC-3 fabricated-fact check
(span re-verification + citation check + a summary-to-source listing for the
presenter's hand-check).

Usage::

    PYTHONPATH=. .venv/Scripts/python.exe -m scripts.t020_gate1 [--days 3] [--no-tavily]

``--no-tavily`` skips the Tavily batch and lets every story fall back to its feed
description, for a free dry run.
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from src.env import load_env
from src.flow.pipeline import TextPipeline
from src.providers.llm import DeepSeekChatProvider
from src.providers.tavily import ExtractResult, TavilyExtractProvider
from src.skills import article_ledger, article_text, curation, news_fetch, safety
from src.skills.checks import check_citations

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "news_feeds.json"
MIN_STORIES = 5
DAYS = 3


def collect_items_by_day(feeds: list[news_fetch.FeedSpec]) -> dict[str, list[news_fetch.RawItem]]:
    """Fetch every active feed and bucket its items by publish date (UTC)."""

    allowed = news_fetch.allowed_hosts_for(feeds)
    by_day: dict[str, list[news_fetch.RawItem]] = defaultdict(list)
    for feed in feeds:
        raw = None
        for attempt in (1, 2):
            try:
                raw = news_fetch.fetch_feed(feed.url, allowed_hosts=allowed)
                break
            except Exception as exc:  # a dead feed must not sink the whole run
                print(f"WARN  {feed.publisher} attempt {attempt}: {type(exc).__name__}: {exc}")
                time.sleep(1)
        if raw is None:
            continue
        for item in news_fetch.parse_feed(raw, feed.publisher):
            if item.published_at is not None:
                by_day[item.published_at.date().isoformat()].append(item)
    return dict(by_day)


def candidates_for(items: list[news_fetch.RawItem]) -> list[dict]:
    """Cluster, rank and safety-tag every distinct candidate for a set of items."""

    clusters = news_fetch.rank_clusters(news_fetch.cluster_items(items))
    candidates = [
        news_fetch.to_candidate(news_fetch.choose_representative(cluster), cluster, index)
        for index, cluster in enumerate(clusters)
    ]
    return safety.tag_candidates(candidates)


def curate_five(items: list[news_fetch.RawItem], chat: curation.Chat) -> curation.CurationResult:
    """Let the LLM pick exactly five distinct candidate stories for a day."""

    return curation.curate(candidates_for(items), chat=chat)


def pick_days(by_day: dict[str, list[news_fetch.RawItem]], count: int = DAYS) -> list[str]:
    """Return the most-recent dates that each yield at least five visible stories."""

    days: list[str] = []
    for day in sorted(by_day, reverse=True):
        visible = [c for c in candidates_for(by_day[day]) if not c["hidden_by_safety"]]
        if len(visible) >= MIN_STORIES:
            days.append(day)
        if len(days) >= count:
            break
    return days


def extractor_for(extracted: dict[str, str], failed: dict[str, str]) -> article_text.Extractor:
    """Build a per-day extractor that serves pre-extracted text (no live Tavily)."""

    def extractor(urls: list[str], extract_depth: str = "basic") -> ExtractResult:
        got = {url: extracted[url] for url in urls if extracted.get(url)}
        missing = {url: failed.get(url, "no extracted text") for url in urls if url not in got}
        return ExtractResult(got, missing, 0.0)

    return extractor


class DayPipeline(TextPipeline):
    """A pipeline whose S1/S3 stages use pre-built candidates and pre-extracted text."""

    def __init__(self, *, candidates: list[dict], extractor: article_text.Extractor, **kwargs: object) -> None:
        self._candidates = candidates
        self._extractor = extractor
        super().__init__(selected_ids=[c["candidate_id"] for c in candidates], **kwargs)  # type: ignore[arg-type]

    def _s1_fetch(self) -> None:
        document = news_fetch.build_candidates_document(self._candidates)
        news_fetch.save_candidates_document(document, workspace_root=self.workspace_root, run_id=self.run_id)
        tagged = safety.tag_candidates(self._candidates)
        self.state["candidates"] = document
        self.state["tagged"] = tagged
        self.state["view"] = safety.default_view(tagged)

    def _s3_articles(self) -> None:
        selected = self.state.get("selected") or []
        requests = [article_text.story_request_from_candidate(c) for c in selected]
        articles, credits = article_text.fetch_article_text(requests, extractor=self._extractor)
        document = article_text.build_articles_document(articles, credits)
        article_text.save_articles_document(document, workspace_root=self.workspace_root, run_id=self.run_id)
        self.state["articles"] = document["articles"]
        self._log("tavily_credits", credits=credits)


def _span_ok(span: str, article_text: str) -> bool:
    return article_ledger.normalize_whitespace(span) in article_ledger.normalize_whitespace(article_text)


def sc3_check(run_dir: Path) -> dict:
    """Deterministically re-verify spans and citations, and list summary sources."""

    ledger = json.loads((run_dir / "ledger.json").read_text(encoding="utf-8"))
    summaries = json.loads((run_dir / "summaries.json").read_text(encoding="utf-8"))

    span_failures: list[str] = []
    facts_by_id: dict[str, dict] = {}
    for story in ledger["stories"]:
        text = story["article_text"]
        for fact in story["facts"]:
            facts_by_id[fact["fact_id"]] = fact
            if not _span_ok(fact["support_span"], text):
                span_failures.append(f"{story['story_id']} {fact['fact_id']} span missing")
        for quote in story.get("quotes", []):
            if not _span_ok(quote["support_span"], text):
                span_failures.append(f"{story['story_id']} quote {quote.get('quote_id')} span missing")

    citations_ok = check_citations(ledger, summaries).passed

    rows: list[dict] = []
    for summary in summaries["summaries"]:
        for sentence in summary["sentences"]:
            cited = [facts_by_id.get(fid, {}).get("claim", "?") for fid in sentence["ledger_fact_ids"]]
            rows.append({"story": summary["story_id"], "summary": sentence["text"], "cited_claims": cited})

    return {"span_failures": span_failures, "citations_ok": citations_ok, "rows": rows}


def render_sc3(result: dict) -> str:
    lines = [
        f"  span re-verification failures: {len(result['span_failures'])}",
        f"  citations check passed: {result['citations_ok']}",
        "  summary sentence -> cited fact claim(s):",
    ]
    for row in result["rows"]:
        lines.append(f"    [{row['story']}] {row['summary']}")
        for claim in row["cited_claims"]:
            lines.append(f"        <- {claim}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T020 Gate 1 validation run")
    parser.add_argument("--days", type=int, default=DAYS, help="number of days to run")
    parser.add_argument("--no-tavily", action="store_true", help="skip the Tavily batch, use feed descriptions")
    args = parser.parse_args(argv)

    load_env(ROOT / ".env")  # providers read keys from the process environment
    provider = DeepSeekChatProvider()

    def chat(messages: list[tuple[str, str]]):
        return provider.complete(messages, json_mode=True)

    feeds = news_fetch.load_feeds(CONFIG)
    by_day = collect_items_by_day(feeds)
    days = pick_days(by_day, count=args.days)
    if not days:
        print("No days with enough distinct stories; aborting.")
        return 1

    per_day = {day: curate_five(by_day[day], chat) for day in days}
    print(f"Selected {len(days)} days: {', '.join(days)}")

    # Clear stale per-day artifacts from a prior run so the skills' refuse-to-
    # overwrite guards do not abort S1 (this driver owns these run dirs).
    for day in days:
        run_dir = ROOT / "runs" / f"t020-{day}"
        if run_dir.exists():
            shutil.rmtree(run_dir)

    # Persist Step 3's JSON output so the live run dir carries the curation
    # document the same way the pipeline's auto-curate path does.
    for day, result in per_day.items():
        curation.save_curation_document(
            curation.build_curation_document(result),
            workspace_root=ROOT,
            run_id=f"t020-{day}",
        )

    for day, result in per_day.items():
        print(f"  {day}: {len(result.selected)} stories")
        for candidate, reason in zip(result.selected, result.reasons):
            print(f"    - [{candidate['publisher']}] {candidate['title'][:70]}")
            if reason:
                print(f"        why: {reason}")

    # One Tavily Extract batch over the selected URLs, but cached per-URL to disk
    # so a re-run after a downstream failure does not spend a second batch
    # (Tavily is the one rate/cost-limited provider). Each cache entry is either
    # ``{"text": ...}`` or ``{"failed": reason}``.
    urls = [candidate["url"] for result in per_day.values() for candidate in result.selected]
    cache_path = ROOT / "runs" / "t020-gate1" / "extract-cache.json"
    cache: dict[str, dict] = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))

    if args.no_tavily:
        extracted: dict[str, str] = {}
        failed = {url: "dry run" for url in urls}
        credits = 0.0
        print("\n--no-tavily: falling back to feed descriptions (0 credits)")
    else:
        extracted = {url: entry["text"] for url, entry in cache.items() if "text" in entry}
        failed = {url: entry["failed"] for url, entry in cache.items() if "failed" in entry}
        missing = [url for url in urls if url not in extracted and url not in failed]
        credits = 0.0
        if missing:
            provider = TavilyExtractProvider()
            result = provider.extract(missing, extract_depth="basic")
            for url, text in result.extracted.items():
                cache[url] = {"text": text}
                extracted[url] = text
            for url, reason in result.failed.items():
                cache[url] = {"failed": reason}
                failed[url] = reason
            credits = result.credits_used
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(cache, indent=2) + "\n", encoding="utf-8")
        print(f"\nTavily Extract: {len(extracted)}/{len(urls)} have text, {len(missing)} fetched now, {credits} new credits")

    results: list[dict] = []
    for day in days:
        run_id = f"t020-{day}"
        pipeline = DayPipeline(
            candidates=list(per_day[day].selected),
            extractor=extractor_for(extracted, failed),
            workspace_root=ROOT,
            run_id=run_id,
        )
        start = time.perf_counter()
        try:
            outcome = pipeline.run()
            error = None
        except Exception as exc:  # report the failure, keep the other days running
            outcome = None
            error = f"{type(exc).__name__}: {exc}"
        elapsed = time.perf_counter() - start
        status = "PASS" if outcome and outcome.passed else "FAIL"
        line = f"  {day}: {elapsed:.1f}s {status} loops={outcome.loops if outcome else '-'}"
        if error:
            line += f" ERROR {error}"
        print(line)
        results.append({"day": day, "run_id": run_id, "seconds": round(elapsed, 1), "passed": bool(outcome and outcome.passed), "loops": outcome.loops if outcome else None, "error": error})

    print("\n=== Gate 1 summary ===")
    print(f"Tavily credits used: {credits}")
    total = sum(r["seconds"] for r in results)
    print(f"Total text-half wall time across {len(results)} days: {total:.1f}s (target <= 120s)")
    print(f"Runs passed: {sum(1 for r in results if r['passed'])}/{len(results)}")

    print("\n=== SC-3 fabricated-fact check (deterministic) ===")
    for result in results:
        run_dir = ROOT / "runs" / result["run_id"]
        if not (run_dir / "ledger.json").exists():
            print(f"  {result['day']}: no ledger produced" + (f" ({result['error']})" if result["error"] else ""))
            continue
        print(f"  {result['day']} ({result['run_id']}):")
        print(render_sc3(sc3_check(run_dir)))

    summary_path = ROOT / "runs" / "t020-gate1" / "summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "days": days,
        "tavily_credits_used": credits,
        "runs": results,
        "planted_error_catch_rate": "10/10 (see T019 real-verifier run)",
    }
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"\nSummary written to {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
