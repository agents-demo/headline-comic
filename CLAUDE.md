# Headline Comic project instructions

## Source of truth and working rules

- `specs/001-headline-comic/spec.md`, `plan.md`, and `tasks.md` define the project. Read them before making project changes. If a requirement is impossible, contradictory, or clearly worse than an alternative, stop and discuss it; record agreed changes in the spec files.
- Follow `tasks.md` in dependency order. Mark a task complete only when its work is done, and commit each task separately with its task ID in the commit message.
- Do not guess jiuwenswarm APIs. Install the framework, inspect its documentation and source, and record confirmed APIs and findings in `docs/api-notes.md`.
- Do not make a paid image, video, or TTS call until T007's guards exist. Before any paid call, report the expected cost and wait for explicit approval.
- API keys belong in `.env`; never commit that file. Ask the presenter to add required keys and name them clearly.
- Use code for deterministic checks and outputs, including support-span and name checks, captions, subtitles, and media assembly. Models produce text and structure only.
- Write tests for deterministic code. Do not add features beyond the spec.

## Team split

Use the two-person schedule in `plan.md` section 5. Track A owns news, text, flow, and UI. Track B owns visual assets, comic/video, and presentation materials. Coordinate through the fixture run and the gates in `tasks.md`; integrate together. The presenter has not supplied an exact presentation date; the current target is roughly two weeks from 2026-10-11.

## Repository layout

```text
headline-comic/
  .specify/                      # spec-kit scaffolding, if present
  specs/001-headline-comic/      # spec, plan, and task checklist
  config/                        # confirmed publisher feed list
  docs/                          # API notes, provider notes, style bible
  src/flow/                      # Swarmflow graph and HITL stages
  src/agents/                    # agent prompts and schemas
  src/skills/                    # news, ledger, checks, media, composition
  src/providers/                 # image, video, TTS, and Tavily adapters
  src/ui/                        # live demo UI
  src/permissions/               # allowlists, approvals, and budget guard
  assets/cast/                   # fixed character and town references
  assets/music/                  # local licensed/royalty-free music
  runs/                           # per-run artifacts
  demo/                           # cached run and backup video
  tests/fixtures/                 # hand-written sample run
  tests/planted_errors/           # seeded verification errors
```

## Commands

- Create the project environment: `uv venv --python 3.11 .venv`
- Install project dependencies: `uv sync`
- Run the local app once implemented: `uv run python -m src.ui`
- Run the test suite: `uv run pytest`
- Check ffmpeg: `ffmpeg -version`

Use the project commands as they are added; update this section if the app entry point changes.
