# Project status and continuation handoff

Updated: 2026-10-12

## Agreed working setup

- Two people can work on separate tracks: Track A owns text, workflow and UI; Track B owns visual assets and video. Use the two-person schedule in `specs/001-headline-comic/plan.md` section 5 rather than its solo cut list. Keep dependencies and gates in `tasks.md` authoritative.
- The presentation is roughly two weeks away; the exact date is not set.
- Keep video generation behind a provider-neutral adapter because the provider may change. The assembled output must remain under 60 seconds, as specified in the plan.
- `.env.example` contains placeholders for `TAVILY_API_KEY`, `LLM_API_KEY`, `LLM_BASE_URL` and `LLM_MODEL`. Add actual values to ignored `.env`; never commit `.env`.

## Accomplished

- **T001 — scaffold:** project scaffold, environment setup and project instructions are committed (`b384003`). The task is checked in `tasks.md`.
- **T002 — framework spike, complete:** the four framework questions and API evidence are recorded in `docs/api-notes.md`. The three-stage offline workflow and mocked Team reply route passed under Python 3.11.9 with the exact pinned `agent-core` source. JiuwenSwarm source inspection confirmed the event bridge and `/swarmflows` viewer hierarchy; the interactive TUI was not launched because npm registry access failed. See API notes for version and integration caveats.
- **T003 - news spike, complete:** the four-feed RSS probe and clustering are recorded; Al Jazeera timed out and Times of Israel remains held for content-use review. The basic Tavily sample returned 7/10 extracts (5 usable, 2 thin, 3 failed); advanced retries plus one Ynet replacement produced a revised 10-article sample with 8 usable. Total reported usage was 3 credits. Search was too BBC-heavy to add as a candidate source, so RSS remains primary. See `docs/provider-notes.md`.
- **T004 - AniDoodle spike, complete:** rendered an 8-second, 1280x720 silent MP4 and two same-character frames. The renderer took 4.7 seconds for 192 frames and passed 6/6 determinism probes. The character stays consistent; the art is flat vector geometry rather than the planned clay look. The checkout is pinned at `06f8be2bef0faa94e7eb6009ef23b36a0ae7b8a8`. Artifacts and the $0 direct local render price are recorded under `runs/anidoodle-gate0/` and `docs/provider-notes.md`.
- **T005 — provider interfaces and AniDoodle adapter, complete:** committed as `7da9192`; provider-neutral image, video and TTS contracts and the local proof adapter are in `src/providers/`. Eight focused provider tests pass.
- **T006 — schemas and fixture, complete:** committed as `f86d527`; eight Draft 2020-12 schemas cover candidates, evidence ledger, summaries, story, storyboard, checks, cost and run manifest. The synthetic five-story fixture validates; support spans, beat/source mapping, comic panels, narration word rate and the 44-second shot total were also checked.
- **T006 — schemas and fixture, complete:** eight Draft 2020-12 schemas cover candidates, evidence ledger, summaries, story, storyboard, checks, cost, and run manifest. A synthetic five-story fixture in `tests/fixtures/t006-sample/` validates against the ledger/story/storyboard schemas; evidence spans, beat/source mapping, comic panels, word rate, and the 44-second shot total were checked.
- **T007 — permission and budget guards, complete:** approval, exact estimate, storyboard quote/reservation, run and project budget limits, exact HTTPS host checks, and run/cast write confinement are implemented in `src/permissions/`. Actual charges and unsettled reservations are tracked in `cost.json`. Thirteen permission tests pass; no paid media call was made.
- **T008 — news_fetch skill, complete:** RSS-only candidate fetch in `src/skills/news_fetch.py`. It loads the four active feeds, fetches a pool of about 40 items, clusters near-identical stories by title (union-find over Jaccard similarity), ranks clusters by cross-source coverage then recency, and emits schema-valid candidates. Feed hosts are validated through the T007 host allowlist. Tavily search stays disabled per T003. Thirteen tests pass; a live fetch validated 40 ranked candidates.
- No paid image, video or TTS request has been made. Video/audio model calls are deferred to backlog T043. The AniDoodle renderer is local and silent by default.

## Next step

Gate 0 closed on 2026-10-12; T005, T006, T007 and T008 are complete. Next follow the text-track dependencies: T009 (safety classifier) and T010 (article text and manual paths). Track B can start T021 style-bible work. T027 still owns bounded storyboard-to-scene mapping. No paid media requests were made; T023 must use the T007 composite guard with recorded prices and separate cost approval. Preserve the T010 per-article fallbacks and keep RSS as the only candidate source.

## Continuation prompt

```text
Continue the Headline Comic project from docs/project-status.md. Gate 0 closed 2026-10-12 and T005 provider-neutral contracts plus the local AniDoodle proof adapter are complete in src/providers/. T004's clip and inspected same-character frames are under runs/anidoodle-gate0/; measurements and visual caveats are in docs/provider-notes.md. Continue with T008/T009/T010 and Track B T021; T027 owns the bounded production storyboard-to-scene mapping; the proof is flat vector art, not the planned clay look. T007 approval, budget, domain and write policies are complete in src/permissions/. Preserve per-article fallbacks and keep RSS as the only candidate source. Do not make paid provider calls without T007 guards and separate cost approval. Keep total video under 60 seconds. Model-backed video and audio are deferred to T043. Preserve unrelated working-tree changes.
```
