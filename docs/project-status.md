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
- **T003 — news spike, partial:** five feeds parsed; Al Jazeera timed out. Four active feeds (BBC, The Guardian, NPR and Ynet) were selected; the Times of Israel is held pending content-use review. Forty recent candidates yielded 38 lexical clusters, including one cross-publisher three-item cluster. The feed config and snapshot script are committed (`ee3e588`). See `docs/provider-notes.md` for results.
- Tavily Extract on ten articles and one Tavily news Search have **not** been called. `TAVILY_API_KEY` is not available in `.env`; the cost/billing approval is also pending. T003 remains unchecked until those probes and the source decision are complete.
- T004 and later work have not been started. No paid image, video or TTS request has been made; T007 guards do not yet exist.

## Next step

Continue **T003** by checking for `TAVILY_API_KEY` without printing its value, then obtaining approval before any request that may incur a charge. The existing provider notes estimate the requested 10 basic Extract URLs plus one basic news Search at up to 3 credits and at most $0.024 if billable; verify current pricing/account billing status before requesting approval. If the key or approval is unavailable, leave T003 open and report the blocker. Once approved, run the ten-article Extract and one restricted-domain, last-day news Search, record per-publisher success and text quality, compare Search with RSS, and update `docs/provider-notes.md` and `config/news_feeds.json` only if evidence supports a change. Then update `tasks.md` and commit with `T003` in the message when the task is actually complete.

## Continuation prompt

```text
Continue the Headline Comic project from docs/project-status.md. First read specs/001-headline-comic/spec.md, plan.md and tasks.md completely, then read docs/provider-notes.md and docs/api-notes.md. Follow tasks.md dependencies and do not change the design silently. Resume T003 only: check whether TAVILY_API_KEY exists without revealing its value; verify current Tavily pricing and whether this run could be billed; tell me the expected maximum cost and wait for my explicit approval before making any potentially billable API request. If approved and the key exists, run Tavily Extract on 10 articles and one Tavily news Search, record measured usage, extraction success/text quality by publisher, compare results with RSS, and make an evidence-based source decision. If blocked, record the exact blocker and leave T003 unchecked. Update the relevant docs and task checklist, then commit the completed task with T003 in the commit message. Do not make paid image, video or TTS calls before T007 guards exist and separate cost approval is given. Keep media-provider adapters provider-agnostic and total video under 60 seconds. Preserve unrelated working-tree changes.
```
