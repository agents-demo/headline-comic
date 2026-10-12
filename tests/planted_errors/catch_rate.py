"""Catch-rate reporter for the planted-error set (SC-4).

Runs the deterministic T015 code checks over each of the ten planted errors and,
for the four Verifier-layer errors, the T016 Verifier (real or scripted), then
reports which errors were caught and the aggregate catch rate.

SC-4 requires the code-checkable errors to all be caught and at least 8 of 10
caught overall. The code layer is measured offline. The Verifier layer needs the
``deepseek-reasoner`` model, so the default offline mode uses a scripted "gold"
verifier that flags exactly the item a correct review should — this demonstrates
the wiring and the expected 10/10, but it is a baseline, not a measurement of the
model. The real model is measured with ``--verifier real`` (deferred to T020).

Usage::

    python -m tests.planted_errors.catch_rate               # code + scripted gold
    python -m tests.planted_errors.catch_rate --verifier real
    python -m tests.planted_errors.catch_rate --verifier off
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from src.skills import verifier
from src.skills.checks import build_checks_document, run_checks

from tests.planted_errors import planted

# A chat callable: messages -> ChatResult (see src/providers/llm.py).
Chat = Callable[[Sequence[tuple[str, str]]], object]

_VERIFIER_IDS = (
    "verify-summaries",
    "verify-causation",
    "verify-real-people",
    "verify-graphic",
    "verify-satire",
)

# The item a correct Verifier should flag for each planted Verifier-layer error.
_GOLD_TARGET = {
    "fabricated_number": "verify-summaries",
    "implied_causation": "verify-causation",
    "graphic_detail": "verify-graphic",
    "satire_private_individual": "verify-satire",
}

# A verifier callable: (error_id, artifacts) -> verifier checks-envelope document.
VerifierFn = Callable[[str, planted.Artifacts], Mapping[str, object]]


def failed_check_ids(document: Mapping[str, object]) -> tuple[str, ...]:
    """Return the check ids that failed in a checks-envelope document."""

    checks = document.get("checks") or []
    if not isinstance(checks, list):
        return ()
    return tuple(
        str(check.get("check_id"))
        for check in checks
        if isinstance(check, Mapping) and not check.get("passed")
    )


def code_failures(artifacts: planted.Artifacts) -> tuple[str, ...]:
    """Run the T015 checks over an artifacts bundle and return failed check ids."""

    document = build_checks_document(run_checks(
        artifacts["ledger"], artifacts["summaries"], artifacts["story"], artifacts["storyboard"]
    ))
    return failed_check_ids(document)


def _verifier_document(chat: Chat, artifacts: planted.Artifacts) -> Mapping[str, object]:
    """Run a Chat callable through the T016 Verifier and return its document."""

    result = chat([
        ("system", verifier._SYSTEM_PROMPT),
        (
            "user",
            verifier._format_input(
                artifacts["ledger"],
                artifacts["summaries"],
                artifacts["story"],
                artifacts["storyboard"],
            ),
        ),
    ])
    verdicts = verifier._verdicts_from(verifier._parse_reply(result.content))
    return verifier.build_verifier_document(verdicts)


def scripted_verifier(error_id: str, artifacts: planted.Artifacts) -> Mapping[str, object]:
    """A deterministic gold baseline: flag exactly the item a correct review should."""

    target = _GOLD_TARGET[error_id]
    raw = {
        "items": [
            {
                "check_id": check_id,
                "passed": check_id != target,
                "reason": "seeded error" if check_id == target else "ok",
            }
            for check_id in _VERIFIER_IDS
        ]
    }
    return verifier.build_verifier_document(verifier._verdicts_from(raw))


def _real_verifier() -> VerifierFn:
    chat = verifier._default_chat()

    def review(error_id: str, artifacts: planted.Artifacts) -> Mapping[str, object]:
        return _verifier_document(chat, artifacts)

    return review


@dataclass(frozen=True)
class CatchResult:
    error_id: str
    description: str
    layer: str
    caught: bool
    failed_checks: tuple[str, ...]


@dataclass(frozen=True)
class CatchRateReport:
    results: tuple[CatchResult, ...]
    code_total: int
    code_caught: int
    verifier_total: int
    verifier_caught: int
    verifier_mode: str

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def caught(self) -> int:
        return sum(1 for result in self.results if result.caught)

    @property
    def rate(self) -> float:
        return self.caught / self.total if self.total else 0.0


def run_catch_rate(verifier_fn: VerifierFn | None = None, *, verifier_mode: str = "off") -> CatchRateReport:
    """Seed each error, run the checks (and Verifier where applicable), and report.

    ``verifier_fn`` maps ``(error_id, artifacts)`` to a Verifier document. When it
    is ``None`` the four Verifier-layer errors are reported as missed (unmeasured);
    this is the deterministic offline path.
    """

    base = planted.load_base()
    results: list[CatchResult] = []
    code_total = code_caught = verifier_total = verifier_caught = 0

    for error in planted.ERRORS:
        artifacts = error.apply(base)
        if error.layer == "checks":
            code_total += 1
            failed = code_failures(artifacts)
            caught = any(check_id in failed for check_id in error.check_ids)
            code_caught += int(caught)
        else:
            verifier_total += 1
            if verifier_fn is None:
                caught, failed = False, ()
            else:
                failed = failed_check_ids(verifier_fn(error.error_id, artifacts))
                caught = any(check_id in failed for check_id in error.check_ids)
            verifier_caught += int(caught)

        results.append(CatchResult(error.error_id, error.description, error.layer, caught, failed))

    return CatchRateReport(
        tuple(results), code_total, code_caught, verifier_total, verifier_caught, verifier_mode
    )


def render_report(report: CatchRateReport) -> str:
    """Render the catch-rate report as plain text (the SC-4 artefact)."""

    lines = [
        f"Planted-error catch rate: {report.caught}/{report.total} ({report.rate:.0%})",
        f"  code checks  : {report.code_caught}/{report.code_total}",
        f"  verifier     : {report.verifier_caught}/{report.verifier_total}  (mode: {report.verifier_mode})",
        "",
    ]
    for result in report.results:
        status = "CAUGHT" if result.caught else "missed"
        failed = ", ".join(result.failed_checks) or "-"
        lines.append(f"  {status:6} [{result.layer:8}] {result.error_id:<28} failed: {failed}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Report the planted-error catch rate (SC-4).")
    parser.add_argument(
        "--verifier",
        choices=("off", "scripted", "real"),
        default="scripted",
        help="off = code checks only; scripted = gold baseline (default); real = deepseek-reasoner",
    )
    args = parser.parse_args(argv)

    if args.verifier == "real":
        review: VerifierFn | None = _real_verifier()
    elif args.verifier == "scripted":
        review = scripted_verifier
    else:
        review = None

    report = run_catch_rate(review, verifier_mode=args.verifier)
    print(render_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
