"""Offline T002 spike: code stage, agent stage, and human stage in-process."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from openjiuwen.agent_teams.workflow.engine.backends.mock import MockBackend
from openjiuwen.agent_teams.workflow.engine.runner import run_workflow


SCRIPT = '''
from swarmflow import agent, human, log, phase

META = {"name": "headline-comic-t002", "description": "T002 local smoke test", "phases": ["Code", "Teammate", "Human gate"]}
APPROVAL = {"type": "object", "properties": {"approved": {"type": "boolean"}}, "required": ["approved"]}

async def run(args):
    phase("Code")
    code_value = 2 + 3
    log(f"pure-code stage: {code_value}")

    phase("Teammate")
    answer = await agent("Return the fixed test phrase.", label="spike-teammate", phase="Teammate")

    phase("Human gate")
    decision = await human("Approve the offline spike?", schema=APPROVAL, label="spike-human", phase="Human gate")
    return {"code": code_value, "teammate": answer, "approval": decision}
'''


async def main() -> None:
    with TemporaryDirectory(prefix="headline-comic-t002-") as temp_dir:
        script_path = Path(temp_dir) / "workflow.py"
        script_path.write_text(SCRIPT, encoding="utf-8")
        progress = []
        logs = []
        result = await run_workflow(
            str(script_path),
            backend=MockBackend(
                fixtures={
                    "spike-teammate": "mock teammate response",
                    "spike-human": {"approved": True},
                }
            ),
            progress_sink=progress.append,
            log_sink=logs.append,
        )
        print(json.dumps({
            "result": result,
            "progress_kinds": [getattr(event.kind, "value", str(event.kind)) for event in progress],
            "logs": logs,
        }, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
