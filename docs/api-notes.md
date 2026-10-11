# JiuwenSwarm / openJiuwen API notes (T002)

Checked against the JiuwenSwarm source checkout at `/home/amir/workspace/jiuwenswarm` and the openJiuwen core source checkout at `/home/amir/workspace/agent-core`. The JiuwenSwarm `pyproject.toml` pins `openjiuwen` to commit `b5f189ba1054a338d8fa3e009b13053776340e44`.

## Confirmed answers to plan.md section 2

1. **Can a Swarmflow run from our own Python process? Yes.** Core entry point: `openjiuwen.agent_teams.workflow.engine.runner.run_workflow(path, *, args, backend, progress_sink, ...)`. It loads a script with top-level `META` and `async def run(args)`, then executes it in-process. For the framework's real teammate/human-session backend, `openjiuwen.agent_teams.workflow.runner.run_swarmflow(...)` takes the team's `model`, `observer`, `messager`, `session_id`, and worker specs. The latter needs the owning Team runtime context; our app can call it from its Python process but must supply that context.
2. **Can a stage be pure code? Yes.** A workflow is an ordinary Python async function. Python code can run between imported DSL operations such as `phase`, `agent`, and `human`. T002's offline script ran `2 + 3` as code stage, `agent(...)` as the worker stage, and `human(...)` as the approval stage.
3. **Can our own UI answer a human stage? Yes, through the Team runtime's reply route.** `run_swarmflow` uses a `messager` and `session_id`. Core raises a `HUMAN_PROMPT` progress event and listens on `swarmflow_human_reply_topic(session_id, team_name, run_id)`. `TeamRuntimeManager` accepts a `HumanAgentMessage` target formatted by `format_swarmflow_human_reply_target(correlation_id, run_id)` and routes the answer to that topic. The demo UI must submit via that Team interaction route; the standalone `run_workflow` + `MockBackend` smoke test only exercises the offline human stub. This UI connection still needs an integration spike when the app flow is wired.
4. **Can Permission Engine enforce our provider host allowlist and paid-media approval? No, not as the sole guard.** The security guide says network parameter rules are currently not matched. The engine governs framework tool calls; it does not intercept arbitrary network requests made inside our Python provider adapters. Use the plan's fallback: require an ask-first policy for exposed generation tools and enforce host allowlists, approval records, and budget checks in our own provider/permission code (T007).

## Confirmed symbols and source locations

- Script import alias: `from swarmflow import agent, human, phase, log`; the facade is `openjiuwen/agent_teams/workflow/engine/facade.py`.
- In-process engine: `openjiuwen/agent_teams/workflow/engine/runner.py:run_workflow`.
- Team integration: `openjiuwen/agent_teams/workflow/runner.py:run_swarmflow` and `preprocess_swarmflow`.
- Tool integration: `openjiuwen/agent_teams/workflow/tool_swarmflow.py:SwarmflowTool`; JiuwenSwarm's `docs/en/TUISwarmFlowGuide.md` says the Team Leader launches scripts through this tool and `/swarmflows` displays the run tree.
- Human reply protocol: `openjiuwen/agent_teams/schema/events.py` (`TeamEvent.WORKFLOW_HUMAN_REPLY`, `swarmflow_human_reply_topic`, `format_swarmflow_human_reply_target`) and `openjiuwen/agent_teams/runtime/manager.py`.
- Permission limitation: JiuwenSwarm `docs/en/ToolPermissionsSecurity.md`, section 2.2, states network parameter rules are currently not matched.

## T002 smoke run

`scripts/spikes/t002_swarmflow.py` ran using the installed system Python 3.13 openJiuwen package with `MockBackend`; result was code value `5`, worker fixture `mock teammate response`, and human fixture `approved: true`. The event stream included workflow start/completion, phases, and agent start/completion. No model API was called and no token or currency cost was incurred. This confirms the workflow engine path, not a real teammate backend or UI reply round trip.

Environment caveat: the project `.venv` is Python 3.11. `openjiuwen` is installed and importable in the host Python 3.13 environment (distribution metadata reports 0.1.16; the editable source checkout reports 0.1.18). Syncing the app's pinned core dependency into `.venv` did not complete, so the exact pin has not yet been exercised under Python 3.11. The JiuwenSwarm CLI help failed to start in the sandbox because its logger tried to write `/home/amir/.jiuwenswarm/agent/.logs/gateway.log`; no product server was started. The workflow core did run in-process under the existing system installation. The docs/source confirm the `/swarmflows` tree, but the UI itself was not opened; whether its stage view is adequate remains unverified.
