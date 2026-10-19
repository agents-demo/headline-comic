"""Per-call LLM latency profiler for the text half (diagnostic).

Replays the S3-S8 LLM calls for one existing run dir (articles already cached,
so no Tavily) and records, per call: wall seconds, prompt tokens, completion
tokens, and the monotonic start/end so the parallel stages' overlap is visible.
This is the measurement that distinguishes prefill-bound (prompt tokens) from
decode-bound (completion tokens) latency and shows whether the parallel stages
actually overlap — before any optimisation is chosen.

Usage: .venv/Scripts/python.exe -m scripts.prof_llm [run_id]
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import threading
import time
from pathlib import Path

from src.env import load_env
from src.providers.llm import DeepSeekChatProvider
from src.skills import article_ledger, story, storyboard, verifier

# ``src.skills`` re-exports the ``summarise`` *function*, which shadows the
# module (same trap pipeline.py guards against); import the module directly.
summarise = importlib.import_module("src.skills.summarise")

ROOT = Path(__file__).resolve().parents[1]
_PROJECT_ROOT = ROOT

_records: list[dict] = []
_lock = threading.Lock()
_t0 = time.perf_counter()


class TimingChat:
    """A chat callable that times each call and records prompt/completion tokens."""

    def __init__(
        self,
        stage: str,
        *,
        json_mode: bool = True,
        model: str | None = None,
        temperature: float | None = 0.0,
        max_tokens: int | None = None,
    ):
        load_env(_PROJECT_ROOT / ".env")
        self.stage = stage
        self.json_mode = json_mode
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.provider = DeepSeekChatProvider(model=model)

    def __call__(self, messages):
        start = time.perf_counter()
        result = self.provider.complete(
            messages, json_mode=self.json_mode, temperature=self.temperature, max_tokens=self.max_tokens
        )
        end = time.perf_counter()
        seconds = end - start
        label = _label_for(self.stage, messages)
        with _lock:
            _records.append({
                "stage": self.stage,
                "label": label,
                "start": round(start - _t0, 2),
                "end": round(end - _t0, 2),
                "seconds": round(seconds, 2),
                "prompt": result.prompt_tokens,
                "completion": result.completion_tokens,
                "tok_s": round(result.completion_tokens / seconds, 1) if seconds else 0,
            })
            print(f"[{label}] {seconds:.1f}s  prompt={result.prompt_tokens}  completion={result.completion_tokens}  "
                  f"({result.completion_tokens / seconds:.1f} tok/s)" if seconds else f"[{label}] {seconds:.1f}s",
                  flush=True)
        return result


def _label_for(stage: str, messages) -> str:
    """Pull a story title / story id out of the user message for the parallel stages."""
    for role, content in messages:
        if role != "user":
            continue
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("Title: "):
                return f"{stage}:{line[7:][:36]}"
            if line.startswith("Story id: "):
                return f"{stage}:{line[10:][:20]}"
    return stage


def _sources(run_dir: Path) -> list[article_ledger.LedgerSource]:
    cands = {c["candidate_id"]: c for c in json.loads((run_dir / "candidates.json").read_text(encoding="utf-8"))["candidates"]}
    ledger = json.loads((run_dir / "ledger.json").read_text(encoding="utf-8"))
    sources = []
    for s in ledger["stories"]:
        c = cands.get(s["story_id"], {})
        sources.append(article_ledger.LedgerSource(
            story_id=s["story_id"],
            title=str(c.get("title") or ""),
            url=s["url"],
            publisher=s["publisher"],
            published_at=s["published_at"],
            text_source=s["text_source"],
            article_text=s["article_text"],
        ))
    return sources


def _report() -> None:
    print("\n=== per-call trace (sorted by start) ===")
    for r in sorted(_records, key=lambda r: r["start"]):
        print(f"{r['start']:6.1f}-{r['end']:6.1f}  {r['label']:42s} {r['seconds']:6.1f}s  "
              f"prompt={r['prompt']:6d} completion={r['completion']:5d}  {r['tok_s']:6.1f} tok/s")
    total = sum(r["seconds"] for r in _records)
    print(f"\nTotal LLM wall time (sum of calls): {total:.1f}s across {len(_records)} calls")
    # stage totals + max (parallel wall)
    by_stage: dict[str, list[float]] = {}
    for r in _records:
        by_stage.setdefault(r["stage"], []).append(r["seconds"])
    print("Per stage: sum vs max (max = parallel wall time)")
    for stage, durs in by_stage.items():
        print(f"  {stage}: sum={sum(durs):.1f}s  max={max(durs):.1f}s  n={len(durs)}")


def main() -> int:
    run_id = sys.argv[1] if len(sys.argv) > 1 else "t020-2026-10-19"
    run_dir = ROOT / "runs" / run_id
    if not run_dir.exists():
        print(f"run dir not found: {run_dir}", file=sys.stderr)
        return 2
    sources = _sources(run_dir)
    print(f"Replaying S3-S8 for {run_id} with {len(sources)} stories\n", flush=True)

    # S3 evidence ledger (5 parallel extractions)
    extractions = article_ledger.extract_ledgers(sources, chat=TimingChat("S3"))
    stories_doc, _ = article_ledger.span_check(sources, extractions)
    ledger_doc = article_ledger.build_ledger_document(stories_doc)

    # S4 summaries (5 parallel)
    summary_list = summarise.summarise(ledger_doc, chat=TimingChat("S4"))
    summaries_doc = summarise.build_summaries_document(summary_list)

    # S5 story (single call)
    raw_story = story._parse_reply(
        TimingChat("S5")([("system", story._SYSTEM_PROMPT), ("user", story._format_summaries(summary_list))]).content
    )
    story_doc = story.build_story(raw_story, characters=story.DEFAULT_CAST)

    # S6 storyboard (single call)
    raw_sb = storyboard._parse_reply(
        TimingChat("S6")([("system", storyboard._SYSTEM_PROMPT), ("user", storyboard._format_story(story_doc))]).content
    )
    sb_doc = storyboard.build_storyboard(raw_sb, cast=storyboard.DEFAULT_CAST)

    # S8 verifier (single call, reasoner model)
    verifier_model = os.environ.get("LLM_VERIFIER_MODEL") or "deepseek-reasoner"
    TimingChat("S8", json_mode=False, model=verifier_model, temperature=None)([
        ("system", verifier._SYSTEM_PROMPT),
        ("user", verifier._format_input(ledger_doc, summaries_doc, story_doc, sb_doc)),
    ])

    _report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
