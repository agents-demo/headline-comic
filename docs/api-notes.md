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

Historical environment notes from the original source-checkout session, superseded by the Windows follow-up below: that session reported host Python 3.13/openjiuwen 0.1.16 and an initial `.venv` on Python 3.11; the exact pin had not been exercised then. Its JiuwenSwarm CLI help attempt failed while trying to write `/home/amir/.jiuwenswarm/agent/.logs/gateway.log`, and no product server was started.

## Windows follow-up check (2026-10-12)

- Cloned JiuwenSwarm at `c0a3ef9fbf073e41959293ed90a4824d48a75f6a` and `agent-core` at the project lock's exact commit `b5f189ba1054a338d8fa3e009b13053776340e44` from GitHub. The JiuwenSwarm checkout skipped an unavailable Git LFS introduction video; source files were present. This JiuwenSwarm revision pins openJiuwen `6df9699e650b3ad9b9835b46ae3c3b7572adb04b`, so its TUI integration was inspected but not run against this app's `b5f...` core.
- Python 3.11.9 and uv are installed. `uv sync --locked` stalled fetching the GitCode source. Installed openJiuwen from the local checkout at the exact pinned commit into `.venv`; `direct_url.json` points to that checkout. The core source pin is therefore verified, though a complete transitive lock sync was not completed.
- Re-ran `scripts/spikes/t002_swarmflow.py` under Python 3.11.9 with the pinned source. Result: code `5`, mock teammate response, approval `true`; events included workflow start/completion, phases, and agent start/completion. No model/API call was made.
- Exercised `TeamRuntimeManager._as_swarmflow_human_reply` and `_route_swarmflow_human_reply` under the pinned source with an in-memory fake messenger. The run-scoped reply was published as `workflow_human_reply` to `session:session-1:team:headline-comic:run:run-7:swarmflow_human_reply`; delivery succeeded.
- Confirmed the monitor path in the JiuwenSwarm source: `WorkflowMonitorHandler` consumes `TeamMonitor.workflow_events()` and emits incremental `workflow.updated` events. The TUI handles `/swarmflows` by entering its full-screen viewer, with workflow list → phase → node navigation; `h` opens pending human inputs, whose replies use `chat.swarmflow_reply`. This is adequate for the planned T035 stage view.
- The interactive TUI was not launched. Its frontend dependencies were unavailable: `npm ci` failed fetching `ws` from the npm registry with `EACCES`, so frontend checks could not run. The UI assessment above is based on source and guide inspection.
- The `EACCES` npm failures come from the corporate network: npm, git and curl do not inherit the Windows system proxy. When on-network, set `HTTP_PROXY`/`HTTPS_PROXY` to the session proxy (e.g. `http://proxy.huawei.com:8080`) for the command only; do not write it into `.npmrc` or set it for direct/off-network sessions.
- TUI frontend follow-up (2026-10-12): the npm blocker is resolved. This machine is now off the corporate network — `proxy.huawei.com` no longer resolves (local DNS is `dns-server.toganetworks.com`), so the proxy override must NOT be set; `registry.npmjs.org` is reachable directly (`npm ping` PONG). `npm ci` in `jiuwenswarm/channels/tui/frontend` installs 18 packages, `npm run build` (tsc) emits `dist/index.js`, and `node dist/index.js --help` loads the full module graph (including `@mariozechner/pi-tui`) and exits 0.
- The TUI's terminal rendering depends on `koffi` (pi-tui's FFI to Win32 terminal APIs). npm 11 skips install scripts not listed in `allowScripts`, so `npm ci` left koffi without its native binary; `npm install-scripts approve koffi` installed the `win32_x64/koffi.node` prebuilt and a live `kernel32.dll` `GetTickCount()` FFI call succeeds. The frontend is therefore launchable. A full interactive session still needs the JiuwenSwarm gateway running at `ws://127.0.0.1:19001/tui` plus a model key (`LLM_API_KEY`) for the teammate backend, which is a presenter-key and paid-call concern (T035), not a frontend build issue.
- Team imports needed `PYTHON_DOTENV_DISABLED=1` because python-dotenv encountered a UTF-8 decode error in the ignored `.env`. No `.env` contents were read or changed.

## T018 — pipeline wiring decision (2026-10-12)

The S1-S9 text half is orchestrated by a deterministic in-process runner (`src/flow/pipeline.py`) rather than the framework's `run_swarmflow`, because `run_swarmflow` needs a live Team runtime (model, observer, messager, session_id, worker specs) and a model key, which are presenter-key and paid-call concerns deferred to T034/T035. The runner encodes exactly the stage list and failure-routing rules a Swarmflow script would: a failed blocking check routes to the stage that owns it (`owner` -> stage), the earliest such stage and everything downstream regenerates in memory, and only accepted artifacts are saved — which keeps the skills' refuse-to-overwrite guards intact while still bounding retries at `max_loops=2` (FR-006). The same module writes `run.log` stage timings (FR-011) and charges every model call against a `TokenBudget` (FR-012). When the gateway is up, T034/T035 mount this runner on it.

## JSON2Video (evaluated 2026-10-13, set aside for T043)

JSON2Video was evaluated as a candidate "true video model" and **set aside**: it is a
deterministic FFmpeg *compositor* (motion graphics over stills + transitions + built-in
TTS), **not** a generative image-to-video model, so it cannot deliver the T043
image-to-video step-change. Confirmed facts from the official docs (no live calls made):

- **Auth/base**: header `x-api-key` (not Bearer); `Content-Type: application/json`;
  base `https://api.json2video.com/v2`. Missing/invalid key → 403; no credits → 401.
- **Workflow**: `POST /v2/movies` → `200` with a 16-char `project` id (no cost
  estimate in the response); poll `GET /v2/movies?project=<id>` (≥ 5 s apart) until
  `status` is `done` or `error`; download via `movie.url`. `DELETE /v2/movies` removes.
- **Request shape**: a Movie object (`resolution`/`quality`/`width`/`height`/`fps`,
  `scenes[]` of `elements[]`, `elements[]` overlaying every scene, `variables`,
  `exports[]`). Element `type` is required; the asset field is `src` (not `url`).
  `voice`/`audio` elements do inline TTS/audio at render time (Azure + ElevenLabs).
- **No dry-run/estimate endpoint.** Validate locally against
  `https://json2video.com/docs/v2/movie-schema.json` (or the OpenAPI spec at
  `https://json2video.com/docs/v2/openapi.json`); never call `POST /v2/movies` to
  validate. Invalid/oversized bodies are 400/413 pre-render; failed renders are not
  billed (but a render must still start).
- **Free tier**: ~600 one-time credits ≈ 1 credit/sec for ≤1080p; 60 s/movie cap;
  **output is watermarked** on the free plan. TTS voice-over costs 0 extra credits.

Implication recorded for T043: any adapter must be built validation-first (local
`movie-schema.json` check + an injectable/mock HTTP transport for tests) and only make a
live render under explicit approval, since there is no credit-free server-side dry run.
The watermark also means free-tier renders are unsuitable for the polished demo.

## MiniMax-H3 (Hailuo 3.0) — self-hosted image-to-video + native audio (T043)

Confirmed against the SGLang `minimax_h3` serving script and the MiniMax community
checkpoint notes (checked 2026-10-19). No live call was made; the adapter is
validated by a fake HTTP server in `tests/providers/test_minimax_h3.py`.

- **Checkpoints**: `FL2VA` (text / first-last-frame → video + audio) and `Ref2VA` (up
  to 9 references), served as separate SGLang services. The adapter uses **FL2VA
  first-frame image-to-video** — each shot's AniDoodle keyframe is the first frame so
  comic and video stay visually pinned (FR-010, D10). `task` is `fl2va` (default) or
  `ref2va`.
- **HTTP**: `POST {base}/v1/videos` (async, returns a JSON job `id`) →
  poll `GET {base}/v1/videos/{id}` for `status` (`pending`/`running`/`completed`/
  `failed`) → `GET {base}/v1/videos/{id}/content` for the MP4 bytes.
- **Request body** (confirmed shape):
  ```json
  {
    "model": "MiniMaxAI/MiniMax-H3",
    "prompt": "…",
    "seconds": 5,
    "task": "fl2va",
    "conditions": [
      {"type": "image", "uri": "file:///data/minimax-h3/<run>/keyframes/<shot>.png",
       "role": "keyframe", "frame_index": 0}
    ],
    "target": {"short_edge": 768, "aspect_ratio": "16:9", "duration_seconds": 5},
    "quality": "exact", "num_outputs_per_prompt": 1, "num_inference_steps": 50,
    "flow_shift": 12.0, "audio_flow_shift": 3.0, "seed": 2101
  }
  ```
  A keyframe condition's `uri` is a **server-visible `file://` URI** — not bytes,
  base64, or a URL. For first-frame-only image-to-video keep a single keyframe
  condition at `frame_index: 0` (`-1` for a last frame; `[0]`, `[-1]` or `[0,-1]` in
  order are the allowed combinations).
- **Output**: `target.short_edge 768` at 16:9 renders **1344×768** (dimensions are
  ÷32), 24 fps, 4–15 s, H.264 + **native stereo AAC audio (32 kHz)**. The adapter
  re-encodes to 1280×720/24fps/AAC-48k so the recovery resolution check and the
  ffmpeg assembly run unchanged. 2K resolution is hosted-only (not local).
- **Env vars** (`src/providers/minimax_h3.py`): `MINIMAX_H3_BASE_URL` (SGLang base,
  default `http://127.0.0.1:30010`), `MINIMAX_H3_MODEL` (`MiniMaxAI/MiniMax-H3`),
  `MINIMAX_H3_VARIANT` (`fl2va`), `MINIMAX_H3_MEDIA_BASE_URI`
  (`file:///data/minimax-h3`), `MINIMAX_H3_SHORT_EDGE` (768),
  `MINIMAX_H3_ASPECT_RATIO` (16:9), `MINIMAX_H3_NUM_INFERENCE_STEPS` (50).
- **Deployment note**: the adapter computes the keyframe `file://` URI as
  `MINIMAX_H3_MEDIA_BASE_URI/<run-id>/keyframes/<shot-id>.png`. The presenter must
  bind-mount (or symlink) this repo's `runs/` directory at the server path behind
  `MINIMAX_H3_MEDIA_BASE_URI` so SGLang can read each run's keyframes. Cost is $0 per
  call (self-hosted), so the adapter records a $0 `video` line and requires no T007
  approval record.
