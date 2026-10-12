import json
import unittest

from src.permissions.approval_guard import ApprovalRequired, guarded_paid_call


class FakeProvider:
    def __init__(self):
        self.calls = 0

    def generate(self, **kwargs):
        self.calls += 1
        return kwargs


class ApprovalGuardTests(unittest.TestCase):
    def test_paid_generation_is_blocked_without_approval_record(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as temp_dir:
            provider = FakeProvider()
            with self.assertRaises(ApprovalRequired):
                guarded_paid_call(
                    provider,
                    action="video.generate",
                    approval_path=Path(temp_dir) / "approval.json",
                    run_id="run-001",
                    prompt="test",
                )

            self.assertEqual(provider.calls, 0)

    def test_paid_generation_requires_matching_run_and_action(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as temp_dir:
            approval = Path(temp_dir) / "approval.json"
            approval.write_text(
                json.dumps({"run_id": "run-001", "approved_actions": ["video.generate"]}),
                encoding="utf-8",
            )
            provider = FakeProvider()

            result = guarded_paid_call(
                provider,
                action="video.generate",
                approval_path=approval,
                run_id="run-001",
                prompt="approved",
            )

            self.assertEqual(result, {"prompt": "approved"})
            self.assertEqual(provider.calls, 1)

    def test_paid_generation_blocks_wrong_run(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as temp_dir:
            approval = Path(temp_dir) / "approval.json"
            approval.write_text(
                json.dumps({"run_id": "other-run", "approved_actions": ["video.generate"]}),
                encoding="utf-8",
            )

            with self.assertRaises(ApprovalRequired):
                guarded_paid_call(
                    FakeProvider(),
                    action="video.generate",
                    approval_path=approval,
                    run_id="run-001",
                )


if __name__ == "__main__":
    unittest.main()
