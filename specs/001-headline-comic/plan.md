# Implementation Plan: Headline Comic

**Spec**: `specs/001-headline-comic/spec.md` (revision 3, 2026-10-11)
**Window**: 10 working days, Sunday 2026-10-11 to Thursday 2026-10-22 (Sunday to Thursday weeks), two people in two tracks. The presenter confirmed two people and an approximate presentation date around two weeks from 2026-10-11; the exact date remains TBD. A solo variant is in section 5.
**Stack**: Python 3.11, jiuwenswarm (core: Swarmflow, Leader/Teammates, Skill packages, Permission Engine), ffmpeg, Tavily (article text), a small local web UI (Streamlit or FastAPI plus one HTML page) for the live demo.

## 1. Architecture

Same pattern as the paper claim checker plan: jiuwenswarm embedded in-process, not over A2A. A fixed, deterministic stage graph on Swarmflow, with Leader/Teammates only where judgment is needed. Numbers, files, captions, checks and video assembly come from code. LLMs propose text and structure only.

```
 S1 [Fetch+Filter+Rank] -> S2 [Human: pick 5] -> S3 [Ledger + span check] -> S4 [Summarise]
   -> S5 [Writer] -> S6 [Director: storyboard] -> S7 [Code checks] -> S8 [Verifier]
          ^------------- fail: back to the owning agent (max 2 loops, then to the human) ---|
   -> S9 [Human: approve script + storyboard + cost]   (edit -> S7 and S8 run again)
   -> S10 [Keyframes: one per shot]
          -> S11 [Comic compose + fact cards]  -> comic.png
          -> S12 [Fallback video, every run]   -> fallback.mp4
          -> S13 [Shots, in parallel] -> S14 [Assemble] -> video.mp4
```

The text half is S1-S9. The visual half is S10-S14. The cast sheets and the town reference are not a stage: they are fixed project assets in `assets/cast/` (spec D8, FR-008).

### Stage to framework mapping

| # | Stage | Type | jiuwenswarm element | Notes |
|---|-------|------|---------------------|-------|
| S1 | Fetch, filter, rank | code + classifier call | Swarmflow stage + Skill `news_fetch` | Pool of about 40 from confirmed RSS feeds (optionally plus a Tavily news search), clustering by title/embedding similarity, safety tags, top 15 untagged. Host allowlist. |
| S2 | Pick 5 | human-in-the-loop | Swarmflow HITL stage | Exactly 5. Shows hidden count. |
| S3 | Evidence ledger | LLM extraction + code check | Skill `article_ledger` | Article text for the five URLs from Tavily Extract, with fallbacks (spec FR-002). One LLM call per article, in parallel. Each fact has a verbatim span; code matches it against the article text. Later stages may only use verified facts. |
| S4 | Summary writer | Teammate | Teammate "Summariser" | 2 sentences per story, cites ledger ids. Code citation checker. |
| S5 | Story writer | Teammate | Teammate "Writer" | Intro plus 5 beats, fixed cast and town, explicit fiction frame, no real names. |
| S6 | Storyboard | Teammate | Teammate "Director" | 8-10 shots with narration, dialogue, comic caption, durations. JSON schema-validated (spec FR-016). |
| S7 | Code checks | deterministic code | Swarmflow stage + Skill `checks` | Schemas, beat mapping, storyboard constraints, citations, real-person names. Blocking. |
| S8 | Fact and satire verifier | Teammate (different model) | Teammate "Verifier" | Blind to the other agents' reasoning; sees only ledger, summaries, story, storyboard. Returns pass/fail with reasons per item. |
| S9 | Script approval | HITL | Swarmflow HITL stage | Approve, edit, or reject. Shows check results and the cost estimate. Writes the approval record that unlocks paid media calls. |
| S10 | Keyframes | tool calls | Skill `image_gen` behind provider adapter | One clean 16:9 keyframe per shot, with cast sheets and town reference. Runs only after approval and under budget. |
| S11 | Comic and fact cards | deterministic code | Skill `compose` (Pillow) | Six flagged keyframes in a 2 x 3 layout; captions, bubbles, source markers on copies; five fact cards. |
| S12 | Fallback video | deterministic code | Skill `compose` (ffmpeg) | Pan and zoom over the keyframes, same narration, subtitles, music and cards. Rendered in every run. |
| S13 | Shots | tool calls | Skill `video_gen` behind provider adapter | Image-to-video per shot, in parallel up to the provider's limit. Model audio discarded. |
| S14 | Assemble | deterministic code | Skill `compose` (ffmpeg) | Transitions, subtitles, TTS narration, music, title and source cards, fiction mark. Never model-generated text. |
| - | Leader | Leader | Leader agent | Hands off between stages, handles retries and the swap to stills, writes run.log. Free-form reasoning only for failure recovery. |

### Why this shape for the presentation

- It shows Leader/Teammates doing real division of labour (Writer and Director versus an independent Verifier on a different model).
- It shows determinism where it matters (ledger span check, name check, captions, assembly) and agents where judgment matters.
- It shows permission gating on a costly, risky action (paid generation only after approval).

## 2. Framework notes

### What the public material confirms (checked 2026-10-10)

- The jiuwenswarm README describes Swarmflow as deterministic multi-stage workflows written as Python scripts, in which the Leader hands off between stage agents, with human-in-the-loop support, a team token budget and run-tree monitoring in the TUI.
- jiuwenswarm installs as an application with its own frontend and TUI (`jiuwenswarm-init`, `jiuwenswarm-start`).
- The agent-core release notes list SwarmFlow human-in-the-loop nodes, budget constraints and suspend/resume/cancel controls (v0.1.17), and runtime controls, budget operators and a redesigned Permission Engine (v0.1.18).
- The jiuwenswarm docs describe tool permissions as interception and control of system commands, file operations and tool calls.

### What the day 1-2 spike (T002) must answer, with the fallback for each "no"

| Question | Fallback if the answer is no |
|----------|------------------------------|
| Can a Swarmflow be driven from our own Python process, without the product's frontend? | Drive SwarmFlow through agent-core directly; failing that, run jiuwenswarm as its own process and have our UI talk to it. |
| Can a stage be pure code with no model call? | Wrap the code as a Skill called by a minimal stage agent with fixed instructions, and accept the extra latency; measure it against the 2-minute text-half target. |
| Can a human-in-the-loop stage be answered from our own UI? | Put the two gates in the UI layer and split the workflow into two Swarmflows (text half, visual half). |
| Can the Permission Engine express "paid media calls only after approval" and a domain allowlist? | Put the generation tools under an ask-first policy, and enforce both rules in the project's own guard (T007). |

Also check in the spike whether the built-in run-tree monitoring or TeamMonitor can serve as the stage view for US6. If yes, T035 shrinks to embedding or screen-sharing it.

The Swarmflow budget is a token budget, not a currency cap. The currency budget is the project's own guard (spec FR-012).

## 3. Key design choices

1. **Fixed cast and town.** Three characters (for example a mayor, a courier, a pigeon) with simple, round, colourful designs, and one town. Each character has one sheet image with four views (front, three-quarter, side, back), so one character takes one reference slot. Generated once, best chosen by hand, stored in `assets/cast/`. A shot shows at most two characters, so each generation call carries at most three references: two cast sheets and the town.
2. **One keyframe per shot.** The storyboard has 8-10 shots. Each gets one clean 16:9 keyframe at 720p with no text. Six of them (one per beat) are the comic panels. Text is added to copies only.
3. **Video path A (primary).** Image-to-video from each shot's keyframe, 720p, 4-8 s per shot, generated in parallel. Provider chosen in the spike behind `VideoProvider.generate(image, prompt, seconds) -> path`. If the spike shows that first-and-last-frame mode holds characters better, S10 also generates an end keyframe per shot; this is decided in T005.
4. **Video path B (fallback, every run).** Animated stills: slow pan and zoom over the keyframes via ffmpeg. No parallax and no sprite animation, since both need layer separation. Works offline from the keyframes and the cached audio.
5. **Text and audio.** Captions and bubbles drawn by Pillow; subtitles by ffmpeg, using the narration text; narration by a TTS provider behind an adapter, cached per run; music from a licensed or royalty-free local file. Narration is capped at 2 words per second of shot duration; if a clip still runs long, the shot's last frame is held. If TTS fails, the video ships with subtitles and music only. Total assembled duration is strictly under 60 seconds.
6. **News.** Two jobs, two tools.
   - The candidate list comes from publishers' RSS feeds, confirmed in the spike; candidates are BBC, the Guardian, NPR, Al Jazeera, plus Times of Israel or Ynet. A front-page feed is already an editor's choice of top stories, it is free, and it keeps the ranking explainable. Reuters and AP are not used: neither offers its own public feed any more.
   - The article text comes from the Tavily Extract API for the five chosen URLs. If Extract fails for an article, use the feed description; if that is too thin, the presenter pastes text. A local readability extractor is added only if the spike shows Extract failing on a chosen publisher.
   - Tavily is query-based search with no top-headlines feed, so it is not the primary list source. A Tavily news search restricted to the same publishers can be added as a second source if the spike shows it helps.
7. **Safety filter.** A classifier tags stories for violence, death, disaster casualties, crimes against individuals and minors. The default list hides tagged stories and shows how many were hidden. The name check in S7 and the Verifier enforce no real-person depiction.
8. **Checks before the Verifier.** S7 runs every check that code can run. The Verifier then judges only causation, recognisable real people, graphic content and the satire target. A planted-error set measures both (spec SC-4).
9. **Budget.** Estimated per run as:
   `shots x (1 + retry rate) x price per shot + keyframes x (1 + retry rate) x price per image + TTS + LLM tokens`,
   with all unit prices and the retry rate measured in the spike and recorded in `docs/provider-notes.md`. Per-run guard default 25 USD and project budget provisional 300 USD, both re-set after the spike. The earlier estimate from a vendor's retail example is dropped. Tavily usage is about 1-5 credits per run, inside its free allowance of 1,000 credits a month.
10. **Replay.** Every stage output is stored. "Replay" runs from a chosen stage with stored inputs. The demo's cached run is a replay with an on-screen "cached run" label and date.

## 4. Repository layout (spec-kit)

```
headline-comic/
  .specify/                      # spec-kit scaffolding
  specs/001-headline-comic/
    spec.md  plan.md  tasks.md
  docs/
    api-notes.md                 # T002 answers
    provider-notes.md            # T003 and T004 measurements, T005 decisions
    style-bible.md               # T021
  src/
    flow/        # Swarmflow graph, HITL stages, leader prompts
    agents/      # summariser, writer, director, verifier prompts + schemas
    skills/      # news_fetch, article_ledger, checks, image_gen, video_gen, compose
    providers/   # image, video, tts and tavily adapters
    ui/          # live demo UI
    permissions/ # allowlists, approval record, budget guard
  assets/
    cast/        # character sheets (four views each), town reference
    music/
  runs/          # artifacts per run
  demo/          # cached run + backup video
  tests/
    fixtures/        # hand-written sample run: ledger, story, storyboard
    planted_errors/  # 10 seeded errors for SC-4
```

## 5. Schedule and gates

### Two people, full scope (default)

Track A is text, flow and UI. Track B is visuals and video. Track B works from the hand-written fixture run (T006) until Track A's pipeline produces real storyboards.

| Days | Track A | Track B | Exit gate |
|------|---------|---------|-----------|
| 1-2 | T001-T003, T006, T007 (15 h) | T004, T005, T009, T019, T021 (14 h) | Gate 0: framework questions answered, feeds confirmed, same character in 2 images, one test shot, guards block a test call |
| 3-5 | T008, T010-T014 (21 h), start T017 | T022-T026 (20 h), then T028 (3 h) | Gate 2: comic page and fact cards from the fixture run, characters recognisable |
| 6-7 | T015-T018, T020 (18 h) | T027, T029-T031 (16 h) | Gate 1: text half runs end to end on 3 days of news. Gate 3: generated video and fallback video from one run |
| 8 | T034 (5 h), integration | T035-T037 (7 h) | Gate 4: press-go demo works start to finish on a real run |
| 9 | T038 rehearsal runs, fix top 3 issues | T038 with Track A | - |
| 10 | T039, T042 | T040, T041 | Gate 5: SC-1 to SC-8 met, presentation ready |

Totals: Track A 61 h, Track B 65 h, shared 6 h (T038), 132 h in all, against 160 h available. Both tracks are close to capacity through day 7 (54 and 53 of 56 hours); the margin is in days 8-10. Friday and Saturday are not planned and are for bug fixes only.

### Solo variant

One person at 8 hours a day needs about 17 working days for the full scope, which does not fit. If the build is solo, start with this reduced scope from day 1:

| Change | Hours saved |
|--------|-------------|
| No generated video: the animated-stills video is the demo output (drop T027 and T031, halve T004) | 10 |
| T035: built-in monitor or a static diagram instead of a custom stage view | 2 |
| T036: file-level replay from the command line only | 2 |
| T026: fact cards in the comic page footer | 2 |
| T038: 3 rehearsal runs instead of 5 | 2 |
| T008: rank by recency only | 1 |
| T019: 5 planted errors instead of 10 | 1 |

That leaves about 112 hours, which is every calendar day from 11 to 22 October at a little over 9 hours a day. If that is not acceptable, move the date or add the second person.

## 6. Risks to the plan

- Framework details come from the public README and release notes. T002 answers the four questions of section 2 on days 1-2, each with a fallback.
- Provider quality is the biggest unknown. The fallback video is rendered in every run, so the demo never ends without a video.
- Neither track has slack before day 8. If Track A slips, T010 or T020 moves to day 8, where Track A has 3 spare hours.
- Tavily is one more live dependency. Each article falls back to its feed description on its own, so a Tavily outage thins the ledger but does not stop the run.
- The exact presentation date is not confirmed. If it is earlier than 22 October, apply the cut list in tasks.md from the top.
- Do not add features beyond the spec during days 6-10; spare time goes to rehearsal.

## 7. Demo run-through

A full live run takes up to 10 minutes, so the demo is a hybrid (spec D7).

| Time | What happens | Live or cached |
|------|--------------|----------------|
| 0:00 | The problem in one line | - |
| 1:00 | Press "Run today", see the ranked list and the hidden count, pick 5 | Live |
| 2:00 | Text half runs: ledger, summaries, writer, director, code checks, verifier, shown in the stage view | Live |
| 4:00 | Approve the script and storyboard; show the cost estimate | Live |
| 5:00 | Reveal a finished comic and video | Cached run, labelled as cached with its date |
| 7:00 | Architecture slides while the live run continues | - |
| 10:00 | Return to the live run: show its comic and fallback video, and the generated video if it is finished | Live |
| 12:00 | Honest limits, then questions | - |

The live run's comic and fallback video should exist a few minutes after approval; rehearsal (T038) measures this. If the news fetch fails on the day, use the manual path; if Tavily fails, the run continues on feed descriptions; if the text half fails, replay the cached run from S9.

## 8. Presentation outline (suggested)

1. The problem in one line: news is heavy; five stories, one playful recap.
2. Live: pick 5, watch the stage view, approve the script.
3. Reveal comic and video (cached), then return to the live result.
4. Architecture: Leader/Teammates, deterministic stages versus agent stages, code checks plus an independent Verifier, permission gates.
5. Honest limits: fiction label, human gates, character drift, measured Verifier catch rate, cost per run.
