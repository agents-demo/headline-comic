# Tasks: Headline Comic

Revision 3 (2026-10-11). Task ids were renumbered in revision 2 and are unchanged in revision 3, which adds Tavily to T003, T008 and T010.

Legend: `[A]` Track A (text, flow, UI). `[B]` Track B (visuals, video). `[AB]` both. `US#`, `FR-###` and `SC-#` refer to spec.md; `S#` refers to the stages in plan.md. Estimates are in hours for one person. Sequence fits 10 working days for two people (plan.md section 5). Total: 132 h (Track A 61 h, Track B 65 h, shared 6 h).

## Phase 0 - Setup and spikes (Days 1-2) - 22 h

- [ ] T001 [A] Create repo from spec-kit template, copy spec/plan/tasks, set up Python env, ffmpeg, `.env` for keys (1h)
- [x] T002 [A] Spike: install jiuwenswarm core; run a 3-stage Swarmflow (one pure-code stage, one Teammate, one HITL stage) from our own Python process; answer the four questions in plan.md section 2 and check the built-in run-tree monitoring; record real API names and the answers in `docs/api-notes.md` (5h) — offline workflow smoke run passed; system Python 3.13 only, see environment caveat in API notes.
- [ ] T003 [A] Spike: confirm which candidate feeds work (BBC, the Guardian, NPR, Al Jazeera, Times of Israel or Ynet); fetch about 40 items and cluster duplicates. Get a Tavily key; run Extract on 10 of the article URLs and record the success rate per publisher and the text quality; run one Tavily news search (topic news, last day, same publishers) and compare its list with the RSS list. Record the results in `docs/provider-notes.md`, decide whether Tavily search becomes a second candidate source, and save the confirmed feed list in config (3h)
- [ ] T004 [B] Spike: make one four-view character sheet; generate 2 scene images of that character using references; test 1 image-to-video shot on 2 candidate providers. Record in `docs/provider-notes.md`: quality, latency, price per image and per shot, concurrency limit, number of reference images accepted, first-and-last-frame support. AIComicBuilder's Docker image may be used as the test bench (5h)
- [ ] T005 [B] Decide image, video and TTS providers, and single-keyframe versus first-and-last-frame mode; write `providers/` adapter interfaces `ImageProvider`, `VideoProvider`, `TTSProvider` (2h)
- [ ] T006 [A] Define JSON schemas: candidates, ledger (facts with support spans, person names), summaries, story, storyboard (FR-016 fields), checks, cost, run manifest. Write one fixture run by hand in `tests/fixtures/` (ledger, story, storyboard) so Track B can start (3h)
- [ ] T007 [A] Guards, before any paid pipeline call: budget guard core (estimate from storyboard and unit prices, hard stop, per-run and project totals in `cost.json`); approval record; Permission Engine policies or own guard per T002 for the domain allowlist, paid calls only after approval, writes only to `runs/` and `assets/cast/` (FR-012, FR-014) (3h)
- **Gate 0**: four framework questions answered; at least 4 working feeds; Tavily Extract returns usable text for at least 8 of 10 test articles; one same-character pair of images plus one shot exist; unit prices recorded; the guard blocks a test generation call made without an approval record.

## Phase 1 - Text pipeline (Track A, Days 3-7; T009 and T019 on Track B, Day 2) - 43 h

- [ ] T008 [A] [US1] Skill `news_fetch`: feed config, pool of about 40, clustering, ranking by cross-source coverage then recency; Tavily news search as a second source only if T003 chose it (FR-001) (4h)
- [ ] T009 [B] [US1] Safety classifier: tag candidates, default list of the top 15 untagged, hidden count, fewer-than-8 message (FR-015) (2h)
- [ ] T010 [A] [US1] Article text and manual paths: Tavily adapter in `providers/`; Extract for the five chosen URLs, and for 5 pasted URLs; per-article fallback to the feed description, then pasted text; record the text source and the credits used (FR-002) (2h)
- [ ] T011 [A] [US2] Skill `article_ledger`: one call per article in parallel; facts, quotes and person names with verbatim support spans; code span check drops and logs failures (FR-003) (5h)
- [ ] T012 [A] [US2] Teammate Summariser: 2 sentences per story citing ledger ids; code citation checker (FR-004) (3h)
- [ ] T013 [A] [US3] Teammate Writer: intro plus 5 beats, beat 5 closes, fixed cast bible and town, fiction frame, no real names; prompt forbids causal claims between stories (FR-005) (4h)
- [ ] T014 [A] [US3] Teammate Director: storyboard JSON with shots, characters (at most 2), camera, action, narration, dialogue, comic caption, durations, comic-panel flags; schema validation (FR-016) (3h)
- [ ] T015 [A] [US3] Skill `checks`: beat mapping, storyboard constraints, narration word cap, citations, real-person name check across story, storyboard and prompts; writes `checks.json` (FR-006) (2h)
- [ ] T016 [A] [US3] Teammate Verifier on a different model: summaries versus ledger, implied causation, recognisable real people, graphic content, satire target; pass/fail with reasons per item; failures routed to the owning agent, max 2 loops, then stop at approval with failures listed (FR-006) (4h)
- [ ] T017 [A] [US1, US3] HITL stages and UI skeleton: pick-5 screen; approval screen with script, storyboard, check results and cost estimate; edit path that re-runs T015 and T016; explicit override logged (FR-007) (5h)
- [ ] T018 [A] Swarmflow wiring for S1-S9; Leader retry and error handling; token budget; `run.log` with stage timings (4h)
- [ ] T019 [B] Planted-error set in `tests/planted_errors/`, built on the fixture run: 10 seeded errors (for example a fabricated number, a swapped name, an uncited sentence, a real person's name in the story, implied causation between two stories, a graphic detail, a private individual as the satire target, a narration over the word cap, a missing beat, a shot with three characters); script that reports the catch rate (SC-4) (2h)
- [ ] T020 [A] Test on 3 different days of real news; hand-check summaries against the source articles; run the planted-error set; time the text half (SC-3, SC-4, SC-5) (3h)
- **Gate 1**: text half runs end to end on 3 days of news in 2 minutes or less; zero fabricated facts on 3 checks; planted-error catch rate recorded.

## Phase 2 - Visuals and comic (Track B, Days 2-5) - 23 h

- [ ] T021 [B] Style bible in `docs/style-bible.md`: clay/miniature look, palette, 3 characters, town set, prompt templates (3h)
- [ ] T022 [B] One-off cast setup: generate four-view sheets for the 3 characters and the town reference, choose the best by hand, store in `assets/cast/` (FR-008) (4h)
- [ ] T023 [B] [US4] Skill `image_gen`: one clean 16:9 keyframe per shot from the storyboard, with up to 3 references per call, in parallel, retries, budget guard hook (FR-009) (5h)
- [ ] T024 [B] [US4] Skill `compose` (comic): 2 x 3 layout from the six panel keyframes, captions and speech bubbles in Pillow on copies, source markers 1-5, header and footer fiction label (FR-009, FR-013) (5h)
- [ ] T025 [B] Character check: build the SC-2 protocol (shuffled clean panels and shot frames, labelling sheet); run it on the fixture run; adjust sheets and prompts (3h)
- [ ] T026 [B] [US2] Facts strip: five source-linked cards (title, 2-sentence summary, link) rendered next to the comic (3h)
- **Gate 2**: comic page and fact cards from the fixture run, characters recognisable.

## Phase 3 - Video (Track B, Days 5-7) - 19 h

- [ ] T027 [B] [US5] Skill `video_gen`: shots from keyframes via the provider adapter, 4-8 s, 720p, in parallel up to the provider limit, model audio discarded, retries, per-shot cost log (FR-010) (6h)
- [ ] T028 [B] [US5] TTS narration per shot, cached in `audio/`; music bed; loudness normalise; hold-last-frame rule when narration runs long; subtitles-only path if TTS fails (FR-010, FR-017) (3h)
- [ ] T029 [B] [US5] Assembly with ffmpeg: transitions, subtitles, title card, "Based on: 5 sources" closing card, "AI-generated fiction" mark on every frame, metadata (FR-010, FR-013) (5h)
- [ ] T030 [B] [US7] Fallback renderer: pan and zoom over the keyframes, same audio, subtitles and cards, run in every run as S12 (FR-017) (3h)
- [ ] T031 [B] Leader recovery: a shot fails on API error, timeout, or duration/resolution check; retry once; then use that shot's animated still (FR-017) (2h)
- **Gate 3**: generated video and fallback video from the same run.

Not scheduled (optional, only if time remains):

- [ ] T032 Vision check: a model compares a frame of each shot with the cast sheets and flags drift (3h)
- [ ] T033 9:16 export (2h)

## Phase 4 - Demo app (Day 8) - 12 h

- [ ] T034 [A] [US1] Demo UI complete: Run today button, candidate list, pick-5, approval, progress, results view with comic, fact cards, fallback and generated video (5h)
- [ ] T035 [B] [US6] Stage view showing each stage's status and which agent or code step ran it; reuse the built-in run-tree monitoring if T002 found it adequate (3h)
- [ ] T036 [B] Replay from a stage using stored outputs; cached-run mode with an on-screen "cached run" label and date (3h)
- [ ] T037 [B] Running cost display and per-run and project totals in the UI (1h)
- **Gate 4**: press-go demo works start to finish on a real run.

## Phase 5 - Rehearsal and polish (Days 9-10) - 13 h

- [ ] T038 [AB] 5 full rehearsal runs on different days of news; record SC-1, SC-2, SC-3, SC-5 and SC-6 for each; time when the live comic and fallback video become available; log failures; fix top 3 (6h)
- [ ] T039 [A] Prepare the cached demo run and the pre-rendered backup video; store in `demo/`; test with the network off (SC-7) (2h)
- [ ] T040 [B] Presentation deck: 5 slides per plan section 8; speaker notes with the accuracy and IP answers; rehearse the run-through of plan section 7 (4h)
- [ ] T041 [B] Q&A prep: accuracy (human gates, span-checked ledger, code checks, Verifier catch rate), IP (original style, fiction label), cost per run, why agents (6 bullet answers) (1h)
- [ ] T042 [AB] Buffer: bug fixes only, no new features
- **Gate 5 (done)**: SC-1 to SC-8 in spec.md met.

## Dependencies

- T002 -> T018.
- T003 -> T008, T009, T010.
- T004, T005 -> T022, T023, T027, T028.
- T006 -> T011-T016, T019; the fixture run lets T023-T030 start before T014 is done.
- T007 -> T022 (first paid pipeline call), T023, T027.
- T010 -> T011.
- T011 -> T012, T015.
- T013 -> T014 -> T015 -> T016 -> T017 (approval screen).
- T019 -> T020.
- T021 -> T022 -> T023.
- T023 -> T024, T027, T030.
- T027, T028 -> T029. T028 -> T030.
- T018, T029, T030 -> T034.
- T034 -> T038.

## Cut list if time slips (in this order)

T032 and T033 are already unscheduled.

1. T035 (stage view becomes the built-in monitor or a static diagram)
2. T036 (replay from the command line only; keep the cached-run label)
3. T026 (fact cards in the comic page footer instead of separate)
4. T019 (5 planted errors instead of 10)
5. T027 and T031: ship the animated-stills video as the primary demo output.

For a solo build, apply the reduced scope in plan.md section 5 from day 1.
