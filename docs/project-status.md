# Project status and continuation handoff

Updated: 2026-10-12

## Agreed working setup

- Two people can work on separate tracks: Track A owns text, workflow and UI; Track B owns visual assets and video. Use the two-person schedule in `specs/001-headline-comic/plan.md` section 5 rather than its solo cut list. Keep dependencies and gates in `tasks.md` authoritative.
- The presentation is roughly two weeks away; the exact date is not set.
- Keep video generation behind a provider-neutral adapter because the provider may change. The assembled output must remain under 60 seconds, as specified in the plan.
- `.env.example` contains placeholders for `TAVILY_API_KEY`, `LLM_API_KEY`, `LLM_BASE_URL` and `LLM_MODEL`. Add actual values to ignored `.env`; never commit `.env`.

## Accomplished

- **T001 — scaffold:** project scaffold, environment setup and project instructions are committed (`b384003`). The task is checked in `tasks.md`.
- **T002 — framework spike, partial:** installed JiuwenSwarm/openJiuwen source was inspected; the four framework questions and evidence/fallbacks are recorded in `docs/api-notes.md`. An offline three-stage mock workflow ran without model calls or cost. `scripts/spikes/t002_swarmflow.py` preserves the spike. The task remains open because the project Python 3.11 environment was not verified with the pinned dependency, and the real Team/UI human-reply and run-tree monitoring path was not exercised. See the API notes for environment caveats.
- **T003 - news spike, complete:** the four-feed RSS probe and clustering are recorded; Al Jazeera timed out and Times of Israel remains held for content-use review. Tavily Extract succeeded on 7/10 URLs (5 usable, 2 thin, 3 failed), and measured usage was 2 credits total. Search results were too BBC-heavy to add as a candidate source, so RSS remains the sole source. T003 is checked; Gate 0 remains open because usable extraction was 5/10 against the 8/10 requirement. See `docs/provider-notes.md`.
- T004 and later work have not been started. No paid image, video or TTS request has been made; T007 guards do not yet exist.

## Next step

T003 is complete. Continue with remaining Gate 0 work and the dependent text-pipeline tasks. Gate 0 still needs usable Tavily text on at least 8 of 10 articles; this probe reached 5/10. Preserve the per-article RSS-description and presenter-paste fallbacks in T010. Tavily Search stays disabled; do not change the four active feeds without new evidence. T002's Python 3.11 and Team/UI checks, T004-T007, and the visual call guard are also still open. Do not make paid image, video or TTS requests before T007 and separate cost approval.

## Continuation prompt

```text
Continue the Headline Comic project from docs/project-status.md. T003's RSS and Tavily probes are complete; read docs/provider-notes.md for measured results. Keep RSS as the only candidate source. Gate 0 remains open because only 5 of 10 tested extracts met the documented usable-text threshold, below its requirement of 8. Follow tasks.md dependencies and continue the remaining Gate 0 work. Preserve per-article fallbacks. Do not make paid image, video or TTS calls before T007 guards exist and separate cost approval is given. Keep media-provider adapters provider-agnostic and total video under 60 seconds. Preserve unrelated working-tree changes.
```
