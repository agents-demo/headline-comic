"""Tests for the planted-error set and catch-rate reporter (T019)."""

import json
import unittest

from src.providers.llm import ChatResult

from tests.planted_errors import catch_rate, planted


def _fake_chat(items: list[dict]) -> catch_rate.Chat:
    def chat(messages):
        return ChatResult(content=json.dumps({"items": items}), model="test", prompt_tokens=1, completion_tokens=1)

    return chat


class BaseTests(unittest.TestCase):
    def test_load_base_has_all_four_artifacts(self) -> None:
        base = planted.load_base()
        self.assertEqual(set(base), {"ledger", "summaries", "story", "storyboard"})

    def test_base_summaries_are_schema_shaped(self) -> None:
        base = planted.load_base()
        summaries = base["summaries"]["summaries"]
        self.assertEqual(len(summaries), 5)
        for summary in summaries:
            self.assertEqual(len(summary["sentences"]), 2)
            for sentence in summary["sentences"]:
                self.assertGreaterEqual(len(sentence["ledger_fact_ids"]), 1)

    def test_base_passes_all_code_checks(self) -> None:
        base = planted.load_base()
        self.assertEqual(catch_rate.code_failures(base), ())

    def test_apply_never_mutates_the_base(self) -> None:
        base = planted.load_base()
        before = json.dumps(base, sort_keys=True)
        for error in planted.ERRORS:
            error.apply(base)
            self.assertEqual(json.dumps(base, sort_keys=True), before, error.error_id)


class DefinitionsTests(unittest.TestCase):
    def test_ten_errors_with_unique_ids(self) -> None:
        ids = [error.error_id for error in planted.ERRORS]
        self.assertEqual(len(ids), 10)
        self.assertEqual(len(set(ids)), 10)

    def test_six_code_and_four_verifier_errors(self) -> None:
        code = [e for e in planted.ERRORS if e.layer == "checks"]
        review = [e for e in planted.ERRORS if e.layer == "verifier"]
        self.assertEqual(len(code), 6)
        self.assertEqual(len(review), 4)


class CodeLayerCatchTests(unittest.TestCase):
    def test_each_code_error_fails_its_target_check(self) -> None:
        base = planted.load_base()
        for error in planted.ERRORS:
            if error.layer != "checks":
                continue
            failed = catch_rate.code_failures(error.apply(base))
            for check_id in error.check_ids:
                self.assertIn(check_id, failed, error.error_id)


class VerifierSeparationTests(unittest.TestCase):
    def test_verifier_errors_are_code_clean(self) -> None:
        """The four Verifier errors must slip past every deterministic check."""

        base = planted.load_base()
        for error in planted.ERRORS:
            if error.layer != "verifier":
                continue
            self.assertEqual(catch_rate.code_failures(error.apply(base)), (), error.error_id)


class CatchRateTests(unittest.TestCase):
    def test_scripted_gold_catches_all_ten(self) -> None:
        report = catch_rate.run_catch_rate(catch_rate.scripted_verifier, verifier_mode="scripted")
        self.assertEqual(report.total, 10)
        self.assertEqual(report.caught, 10)
        self.assertEqual(report.code_caught, 6)
        self.assertEqual(report.verifier_caught, 4)

    def test_code_only_reports_six_caught(self) -> None:
        report = catch_rate.run_catch_rate(None, verifier_mode="off")
        self.assertEqual(report.caught, 6)
        self.assertEqual(report.code_caught, 6)
        self.assertEqual(report.verifier_caught, 0)

    def test_verifier_that_misses_all_reports_six_caught(self) -> None:
        def miss_everything(error_id, artifacts):
            raw = {"items": [{"check_id": cid, "passed": True, "reason": "ok"} for cid in catch_rate._VERIFIER_IDS]}
            from src.skills import verifier

            return verifier.build_verifier_document(verifier._verdicts_from(raw))

        report = catch_rate.run_catch_rate(miss_everything, verifier_mode="scripted")
        self.assertEqual(report.caught, 6)
        self.assertEqual(report.verifier_caught, 0)

    def test_verifier_document_parses_a_chat_reply(self) -> None:
        base = planted.load_base()
        items = [
            {"check_id": cid, "passed": cid != "verify-causation", "reason": "review"}
            for cid in catch_rate._VERIFIER_IDS
        ]
        document = catch_rate._verifier_document(_fake_chat(items), base)
        self.assertEqual(catch_rate.failed_check_ids(document), ("verify-causation",))
        self.assertEqual(len(document["checks"]), 5)


class RenderReportTests(unittest.TestCase):
    def test_report_mentions_rate_and_layers(self) -> None:
        report = catch_rate.run_catch_rate(catch_rate.scripted_verifier, verifier_mode="scripted")
        text = catch_rate.render_report(report)
        self.assertIn("10/10", text)
        self.assertIn("code checks", text)
        self.assertIn("verifier", text)
        self.assertIn("CAUGHT", text)


if __name__ == "__main__":
    unittest.main()
