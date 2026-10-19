"""S1-S9 text-half pipeline runner (T018).

Wires the T008-T017 skills into one Swarmflow-shaped run and adds the three
things the individual stages do not provide on their own:

* the Leader retry loop (FR-006) — after the Verifier, every failed blocking
  check is routed back to the stage that owns it and that stage (plus everything
  downstream) is regenerated, at most ``max_loops`` times, then the run stops
  with the open failures listed for the approval gate;
* the LLM token budget (FR-012) — every model call is charged against a
  :class:`~src.flow.token_budget.TokenBudget` and the total is written to
  ``run.log``;
* ``run.log`` stage timings (FR-011) — one entry per stage execution with its
  elapsed time and outcome.

The framework's own ``run_swarmflow`` needs a live Team runtime and a model key
(see ``docs/api-notes.md``); this module is the deterministic orchestrator that
runs in-process today. The S1-S9 stage list and the failure-routing rules here
are exactly what a Swarmflow script would encode, and T034/T035 mount this on
the interactive gateway.

Stages (plan.md section 4):

    S1 fetch/filter/rank   S2 curate/pick-5       S3 evidence ledger
    S4 summaries           S5 writer              S6 director
    S7 code checks         S8 verifier            S9 approval

The generation stages S3-S6 produce their artifacts in memory during the retry
loop; only the accepted artifacts are saved, which keeps the skills' refuse-
to-overwrite guards intact while still allowing a bounded number of retries.
"""

from __future__ import annotations

import importlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Sequence

from src.flow.hitl import (
    ApprovalOutcome,
    Decision,
    build_approval_record,
    checks_from,
    evaluate_approval,
    log_approval,
    pick_stories,
    save_approval,
)
from src.flow.runlog import append_entry, log_entry, validate_run_id
from src.flow.token_budget import (
    DEFAULT_TOKEN_LIMIT,
    TokenAccountingChat,
    TokenBudget,
)
from src.providers.llm import ChatResult, DeepSeekChatProvider
from src.skills import article_ledger, article_text, checks, curation, news_fetch, safety, story, storyboard, verifier

# ``src.skills`` re-exports the ``summarise`` *function* under the same name, so
# both ``from src.skills import summarise`` and ``import src.skills.summarise``
# bind the function (the package attribute) and shadow the module. Resolve the
# module straight from ``sys.modules`` so ``summarise.summarise`` and friends
# reach the skill's entry points.
summarise = importlib.import_module("src.skills.summarise")

Chat = Callable[[Sequence[tuple[str, str]]], ChatResult]

STAGE_ORDER = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9")
GENERATION_STAGES = ("S3", "S4", "S5", "S6")

STAGE_TITLES = {
    "S1": "Fetch, filter, rank",
    "S2": "Curate / pick 5",
    "S3": "Evidence ledger",
    "S4": "Summaries",
    "S5": "Writer",
    "S6": "Director",
    "S7": "Code checks",
    "S8": "Verifier",
    "S9": "Approval",
}

# A failed blocking check routes back to the stage that owns it (FR-006). The
# Verifier reports ``owner`` as summary/story (the stage to route back to), so
# this map is shared by code and Verifier failures alike.
OWNER_STAGE = {
    "ledger": "S3",
    "summary": "S4",
    "story": "S5",
    "storyboard": "S6",
    "verifier": "S8",
    "system": "S7",
}


class PipelineError(RuntimeError):
    """Raised when a stage fails and the run must stop fail-closed."""


@dataclass(frozen=True)
class StageResult:
    stage_id: str
    label: str
    ok: bool
    seconds: float


@dataclass(frozen=True)
class PipelineResult:
    passed: bool
    stages: tuple[StageResult, ...]
    failures: Mapping[str, tuple[str, ...]]
    loops: int
    token_used: int
    token_limit: int
    approval: ApprovalOutcome | None
    message: str


def route_failures(
    checks_document: Mapping[str, object],
    verifier_document: Mapping[str, object],
) -> dict[str, list[str]]:
    """Map failed blocking checks to the stage that owns each (FR-006)."""

    routed: dict[str, list[str]] = {}
    for document in (checks_document, verifier_document):
        for check in checks_from(document):
            if check.get("passed"):
                continue
            if check.get("blocking", True) is False:
                continue
            check_id = str(check.get("check_id") or "?")
            stage = OWNER_STAGE.get(str(check.get("owner") or ""), "S7")
            routed.setdefault(stage, []).append(check_id)
    return {stage: sorted(ids) for stage, ids in sorted(routed.items())}


def rerun_window(routed: Mapping[str, Sequence[str]]) -> tuple[str, ...]:
    """Return the generation stages to regenerate, from the earliest failure on."""

    generation = [stage for stage in GENERATION_STAGES if stage in routed]
    if not generation:
        return ()
    earliest = min(generation, key=STAGE_ORDER.index)
    start = STAGE_ORDER.index(earliest)
    return tuple(stage for stage in GENERATION_STAGES if STAGE_ORDER.index(stage) >= start)


def _default_chat() -> Chat:
    provider = DeepSeekChatProvider()

    def chat(messages: Sequence[tuple[str, str]]) -> ChatResult:
        return provider.complete(messages, json_mode=True)

    return chat


class TextPipeline:
    """Orchestrate the S1-S9 text half with retry, budget and run.log timings."""

    def __init__(
        self,
        *,
        workspace_root: Path,
        run_id: str,
        selected_ids: Sequence[str] = (),
        chat: Chat | None = None,
        verify_chat: Chat | None = None,
        fetcher: news_fetch.Fetcher | None = None,
        config_path: Path | None = None,
        cast: Sequence[str] = story.DEFAULT_CAST,
        token_limit: int = DEFAULT_TOKEN_LIMIT,
        max_loops: int = 2,
        approved_actions: Sequence[str] = (),
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.workspace_root = workspace_root
        self.run_id = run_id
        self.selected_ids = list(selected_ids)
        self.cast = list(cast)
        self.max_loops = max_loops
        self.approved_actions = list(approved_actions)
        self.clock = clock

        self.budget = TokenBudget(limit=token_limit)
        # Chats are built lazily so constructing a pipeline never touches the
        # environment or a provider (important for test isolation).
        self._raw_chat = chat
        self._raw_verify_chat = verify_chat
        self._chat: TokenAccountingChat | None = None
        self._verify_chat: TokenAccountingChat | None = None

        self.fetcher = fetcher
        self.config_path = config_path

        self.state: dict[str, object] = {}
        self.stages: list[StageResult] = []

    @property
    def chat(self) -> TokenAccountingChat:
        if self._chat is None:
            self._chat = TokenAccountingChat(self._raw_chat or _default_chat(), self.budget)
        return self._chat

    @property
    def verify_chat(self) -> TokenAccountingChat:
        if self._verify_chat is None:
            self._verify_chat = TokenAccountingChat(
                self._raw_verify_chat or verifier._default_chat(), self.budget
            )
        return self._verify_chat

    # ---- orchestration -------------------------------------------------

    def run(self) -> PipelineResult:
        validate_run_id(self.run_id)
        self._log("run_start", run_id=self.run_id, token_limit=self.budget.limit, max_loops=self.max_loops)
        try:
            self._timed("S1", self._s1_fetch, "fetch+filter+rank")
            self._timed("S2", self._s2_pick, "pick-5")
            self._timed("S3", self._s3_articles, "article text")

            loops = 0
            self._run_generation(("S3", "S4", "S5", "S6", "S7", "S8"))
            failures = self._current_failures()
            while failures and loops < self.max_loops:
                window = rerun_window(failures)
                if not window:
                    break
                self._log("retry", loop=loops + 1, rerun=list(window), failures=failures)
                self._run_generation(window + ("S7", "S8"))
                failures = self._current_failures()
                loops += 1

            self._finalize()
            self._timed("S9", self._s9_approval, "approval")
        except PipelineError as exc:
            self._log("run_end", passed=False, error=str(exc))
            return self._result(failures={}, passed=False, message=str(exc), loops=0)

        self._log(
            "token_usage",
            used=self.budget.used,
            limit=self.budget.limit,
            remaining=self.budget.remaining,
        )
        approval = self.state.get("approval")
        passed = approval.allowed if isinstance(approval, ApprovalOutcome) else not failures
        self._log("run_end", passed=passed, loops=loops, failures=failures)
        return self._result(failures=failures, passed=passed, message="", loops=loops)

    # ---- stage helpers -------------------------------------------------

    def _run_generation(self, stages: Sequence[str]) -> None:
        for stage_id in stages:
            self._timed(stage_id, lambda s=stage_id: self._generate(s), STAGE_TITLES.get(stage_id, stage_id))

    def _timed(self, stage_id: str, fn: Callable[[], None], label: str) -> StageResult:
        start = self.clock()
        ok = True
        try:
            fn()
        except Exception as exc:
            ok = False
            self._log("stage_error", stage=stage_id, label=label, error=f"{type(exc).__name__}: {exc}")
            raise PipelineError(f"{label} failed: {exc}") from exc
        finally:
            elapsed = self.clock() - start
            self._log("stage", stage=stage_id, label=label, seconds=round(elapsed, 3), ok=ok)
            self.stages.append(StageResult(stage_id=stage_id, label=label, ok=ok, seconds=elapsed))
        return self.stages[-1]

    def _result(
        self,
        *,
        failures: Mapping[str, Sequence[str]],
        passed: bool,
        message: str,
        loops: int,
    ) -> PipelineResult:
        normalized = {stage: tuple(ids) for stage, ids in failures.items()}
        approval = self.state.get("approval")
        return PipelineResult(
            passed=passed,
            stages=tuple(self.stages),
            failures=normalized,
            loops=loops,
            token_used=self.budget.used,
            token_limit=self.budget.limit,
            approval=approval if isinstance(approval, ApprovalOutcome) else None,
            message=message,
        )

    # ---- S1-S3 ---------------------------------------------------------

    def _s1_fetch(self) -> None:
        if self.config_path is None:
            raise PipelineError("S1 requires a config_path to the feed list")
        candidates = news_fetch.run(self.config_path, fetcher=self.fetcher)
        news_fetch.save_candidates_document(
            candidates, workspace_root=self.workspace_root, run_id=self.run_id
        )
        tagged = safety.tag_candidates(candidates["candidates"])
        self.state["candidates"] = candidates
        self.state["tagged"] = tagged
        self.state["view"] = safety.default_view(tagged)

    def _s2_pick(self) -> None:
        tagged = self.state.get("tagged") or []
        by_id = {str(c["candidate_id"]): c for c in tagged}
        if self.selected_ids:
            ids = pick_stories(self.selected_ids)
            source = "human"
        else:
            result = curation.curate(tagged, chat=self.chat)
            curation.save_curation_document(
                curation.build_curation_document(result),
                workspace_root=self.workspace_root,
                run_id=self.run_id,
            )
            ids = [str(c["candidate_id"]) for c in result.selected]
            source = "curation"
        missing = [cid for cid in ids if cid not in by_id]
        if missing:
            raise PipelineError("Picked ids not in the candidate list: " + ", ".join(missing))
        self.state["selected"] = [by_id[cid] for cid in ids]
        self._log("selection", ids=ids, source=source)

    def _s3_articles(self) -> None:
        selected = self.state.get("selected") or []
        requests = [article_text.story_request_from_candidate(c) for c in selected]
        articles, credits = article_text.fetch_article_text(requests, extractor=None)
        document = article_text.build_articles_document(articles, credits)
        article_text.save_articles_document(
            document, workspace_root=self.workspace_root, run_id=self.run_id
        )
        self.state["articles"] = document["articles"]
        self._log("tavily_credits", credits=credits)

    # ---- S3-S8 generation (in memory) ----------------------------------

    def _generate(self, stage_id: str) -> None:
        if stage_id == "S3":
            self._generate_ledger()
        elif stage_id == "S4":
            self._generate_summaries()
        elif stage_id == "S5":
            self._generate_story()
        elif stage_id == "S6":
            self._generate_storyboard()
        elif stage_id == "S7":
            self._generate_checks()
        elif stage_id == "S8":
            self._generate_verifier()
        else:
            raise PipelineError(f"Unknown generation stage: {stage_id}")

    def _generate_ledger(self) -> None:
        selected = self.state.get("selected") or []
        articles = self.state.get("articles") or []
        sources = [
            article_ledger.ledger_source_from(article, candidate)
            for article, candidate in zip(articles, selected)
        ]
        extractions = article_ledger.extract_ledgers(sources, chat=self.chat)
        stories, dropped = article_ledger.span_check(sources, extractions)
        self.state["ledger"] = article_ledger.build_ledger_document(stories)
        self.state["dropped"] = dropped

    def _generate_summaries(self) -> None:
        ledger = self.state.get("ledger") or {}
        summaries = summarise.summarise(ledger, chat=self.chat)
        self.state["summary_list"] = summaries
        self.state["summaries"] = summarise.build_summaries_document(summaries)

    def _generate_story(self) -> None:
        summaries = self.state.get("summary_list") or []
        raw = story._parse_reply(
            self.chat([("system", story._SYSTEM_PROMPT), ("user", story._format_summaries(summaries))]).content
        )
        self.state["story"] = story.build_story(raw, characters=self.cast)

    def _generate_storyboard(self) -> None:
        story_doc = self.state.get("story") or {}
        raw = storyboard._parse_reply(
            self.chat([
                ("system", storyboard._SYSTEM_PROMPT),
                ("user", storyboard._format_story(story_doc)),
            ]).content
        )
        self.state["storyboard"] = storyboard.build_storyboard(raw, cast=self.cast)

    def _generate_checks(self) -> None:
        checks_list = checks.run_checks(
            self.state.get("ledger") or {},
            self.state.get("summaries") or {},
            self.state.get("story") or {},
            self.state.get("storyboard") or {},
            cast=self.cast,
        )
        self.state["checks"] = checks.build_checks_document(checks_list)

    def _generate_verifier(self) -> None:
        result = self.verify_chat([
            ("system", verifier._SYSTEM_PROMPT),
            (
                "user",
                verifier._format_input(
                    self.state.get("ledger") or {},
                    self.state.get("summaries") or {},
                    self.state.get("story") or {},
                    self.state.get("storyboard") or {},
                ),
            ),
        ])
        verdicts = verifier._verdicts_from(verifier._parse_reply(result.content))
        self.state["verifier"] = verifier.build_verifier_document(verdicts)

    def _current_failures(self) -> dict[str, list[str]]:
        return route_failures(self.state.get("checks", {}), self.state.get("verifier", {}))

    # ---- finalize and S9 -----------------------------------------------

    def _finalize(self) -> None:
        ledger = self.state.get("ledger") or {}
        article_ledger.save_ledger_document(
            ledger, self.state.get("dropped") or [], workspace_root=self.workspace_root, run_id=self.run_id
        )

        summary_list = self.state.get("summary_list") or []
        summarise.save_summaries_document(
            self.state.get("summaries") or {},
            summarise.render_summaries_markdown(summary_list),
            workspace_root=self.workspace_root,
            run_id=self.run_id,
        )
        story.save_story(self.state.get("story") or {}, workspace_root=self.workspace_root, run_id=self.run_id)
        storyboard.save_storyboard(
            self.state.get("storyboard") or {}, workspace_root=self.workspace_root, run_id=self.run_id
        )
        checks.save_checks(self.state.get("checks") or {}, workspace_root=self.workspace_root, run_id=self.run_id)
        verifier.save_verifier(
            self.state.get("verifier") or {}, workspace_root=self.workspace_root, run_id=self.run_id
        )

    def _s9_approval(self) -> None:
        checks_doc = self.state.get("checks") or {}
        verifier_doc = self.state.get("verifier") or {}
        outcome = evaluate_approval(checks_doc, verifier_doc, decision=Decision.APPROVE)
        self.state["approval"] = outcome
        if outcome.allowed:
            save_approval(
                build_approval_record(self.run_id, self.approved_actions, overrides=outcome.overridden),
                workspace_root=self.workspace_root,
                run_id=self.run_id,
            )
        log_approval(
            self.workspace_root,
            self.run_id,
            outcome,
            approved_actions=self.approved_actions if outcome.allowed else [],
        )

    # ---- logging -------------------------------------------------------

    def _log(self, event: str, **fields: object) -> None:
        append_entry(self.workspace_root, self.run_id, log_entry(event, **fields))
