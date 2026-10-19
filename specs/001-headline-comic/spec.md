# Feature Specification: Headline Comic - five headlines, one miniature story

**Feature branch**: `001-headline-comic`
**Created**: 2026-10-10
**Revised**: 2026-10-11 (revision 3; see section 12)
**Status**: Draft
**Type**: Live-demo MVP (multimedia application). Not a product for sale.
**Deadline**: presentation is roughly two weeks from 2026-10-11; the exact date is not confirmed. The working target remains Thursday 2026-10-22, with the two-person schedule in plan.md section 5.

## 1. Summary

Input: five of today's top news stories, chosen by the presenter from a filtered, ranked list. Output: (a) five short summaries with source links, (b) a single-page comic recap that ties the five into ONE short storyline, (c) a 45-60 second miniature-world video of that storyline with a fixed cast of recurring characters.

The demo is: press go, watch a pipeline run, get a comic and a video. The 5 headlines are picked by an LLM curator (or a human), and a human approves the script and storyboard. The backend is jiuwenswarm, used as framework machinery only (Swarmflow, Leader/Teammates, Skill packages, Permission Engine), with no product shell.

## 2. Context and evidence

From the research done 2026-10-10. Items marked (unconfirmed) could not be confirmed in a second search on the same day; the others marked (first pass) were not re-checked.

- Closest existing thing: News Shuffle (App Store) fuses THREE unrelated headlines into one absurd narrative plus an AI cartoon. Free, no video, almost no ratings. (unconfirmed) https://apps.apple.com/us/app/news-shuffle/id6756138326
- Punchline turns trending news into short AI-generated comic stories. Small launch, no traction data found. https://www.hunted.space/dashboard/punchline
- Toy-brick video from a topic is already sold as a service (Hooked, Reviral). The price of about $3 per 15 s on Reviral's brick example is (unconfirmed) and is a retail price, so it is no longer used for the budget (FR-012). https://www.hooked.so/tools/lego-video-generator , https://reviral.ai/tools/brick-animation-video-generator
- AIComicBuilder is an open-source (Apache 2.0) app that turns a script into an animated video: character sheets with four views, storyboard, first and last frame per shot, video, assembly. It is a separate Next.js application, so it is used here as a reference and as a spike test bench, not as a component. https://github.com/LingyiChen-AI/AIComicBuilder
- Tavily is a query-based search API for agents. It has a news topic with published dates, a filter to a list of publisher domains, and an Extract endpoint that returns the text of given URLs. It has no top-headlines feed. The free allowance is 1,000 credits a month. Checked in its docs on 2026-10-11, not run. https://docs.tavily.com/documentation/api-reference/endpoint/search , https://docs.tavily.com/documentation/api-credits.md
- Many News does daily AI-selected news with story arcs and animated anchors. (first pass) https://www.many-worlds.com/manynews
- Audience data (Reuters Institute Digital News Report 2026): playful video fits how people watch, but 42% avoid news at least sometimes, creators are trusted less, few pay. (first pass) https://reutersinstitute.politics.ox.ac.uk/digital-news-report/2026/dnr-executive-summary
- Because this is a presentation MVP, differentiation versus existing apps matters less than a clear, reliable, explainable pipeline. The agentic pipeline is the story.

## 3. Constraints (stated by the user)

- Not a product to sell. An MVP multimedia application to present in under 2 weeks.
- Backend agent framework: jiuwenswarm (core only, same as the paper claim checker plan).
- Input is the latest 5 top news; summarize them; create a comic recap that connects them into one short storyline; create a miniature (Lego-like) short video of the storyline.

## 4. Decisions taken in this spec (change if you disagree)

| # | Decision | Why |
|---|----------|-----|
| D1 | Visual world is an ORIGINAL miniature/clay town, not literal LEGO. No "LEGO" name, no minifigures, no 2x4 brick shapes. | LEGO's policy covers the name, minifigure and 2x4 brick. An original look is clean for any future use and costs nothing in the demo. |
| D2 | Five source-linked factual cards stay visually separate from the fictional miniature story. The story is labelled "fiction inspired by today's news", and a small "AI-generated fiction" mark stays on every video frame. | Weaving five stories can imply false causation between real events. A clip can be shared without its closing card. |
| D3 | No accounts, no app store, no daily automation, no database beyond local files. | Two-week budget. |
| D4 | The 5 headlines are picked (an LLM curator by default, or a human, from the filtered, ranked list) and a human approves the script AND the storyboard, with a cost estimate, before any paid media generation in the run. | Accuracy answer for Q&A, and it caps generation cost. The storyboard decides the cost, so it must exist before approval. |
| D5 | All on-screen text (captions, titles, speech bubbles, subtitles) is composited by code, never generated by the image or video model. | Generated text is unreliable. |
| D6 | The video generation provider sits behind an adapter. A fallback video (animated stills via ffmpeg, pan and zoom only) is rendered in EVERY run, not on demand. | A live demo must not depend on one external API, and a fallback that is always rendered is always tested. |
| D7 | The demo is a hybrid. The text half runs live up to script approval. The visuals are then shown from a cached full run, labelled on screen as cached, while the live run finishes in the background. A pre-rendered backup video also exists. | A full run takes up to 10 minutes and the talk is 10-15 minutes. |
| D8 | The cast (three characters) and the town are fixed project assets: generated once, chosen by hand, reused in every run. The Writer writes for this cast. | Character consistency is the hardest visual problem. Fixed, hand-picked sheets remove most of it and take the sheets out of the 10-minute run. |
| D9 | Whatever code can check, code checks; the Verifier agent handles only what needs judgment. | Deterministic checks are cheaper, faster and easier to defend in Q&A than a model's opinion. |
| D10 | The storyboard is the single source for both outputs: one clean keyframe per shot; the comic uses six of them, the video uses all. | Removes the gap between 6 panels and 8-10 shots, and keeps comic and video visually identical. |

## 5. User scenarios

### US1 - Run the pipeline live (P1)
As the presenter I press "Run today", see about 15 ranked headlines, tick 5, and watch each stage report progress.
- Given a news fetch succeeds, when I run, then I see a ranked list of candidate headlines with source and time, and a count of stories hidden by the safety filter with a toggle to show them.
- Given fewer than 8 candidates remain after filtering, then the UI says so and offers the manual path (FR-002) or the cached run.
- Given I select 5, then the system will not proceed with fewer or more than 5.
- Given the pipeline finishes, then I get comic.png (or comic.pdf), story.json, storyboard.json, fallback.mp4 and video.mp4.

### US2 - Read the facts (P1)
As a viewer I see five cards, each with a 2-sentence summary and a link to the original article.
- Every sentence in a summary cites ledger facts, and every ledger fact carries a verbatim span of the article text that code has matched against the article.

### US3 - Approve the script (P1)
As the presenter I see the storyline (title, beats), the storyboard (shot list, narration, dialogue), the results of the checks and a cost estimate, and I approve, edit, or reject before any image or video generation.
- Nothing is sent to an image or video model in the run until approval.
- If I edit, the code checks and the Verifier run again. A code-check failure blocks approval. A remaining Verifier failure can only be overridden explicitly, and the override is written to run.log.

### US4 - Comic recap (P1)
A single page, 6 panels (one intro, five beats; one per headline), same characters throughout, captions and bubbles composited by code, with small "source 1-5" markers linking each panel to a card. The six panels are six of the video's keyframes.

### US5 - Miniature video (P1)
45-60 s including cards, 16:9, recurring characters, narration with matching subtitles, music bed, short title card, closing "Based on: 5 sources" card, and a small "AI-generated fiction" mark on every frame.

### US6 - See the agents work (P2)
The UI shows the stage list with each stage's status, and which agent (Leader or Teammate) or which code step did what. This is the presentation's architecture proof.

### US7 - Fallback (P2)
Every run also produces fallback.mp4 (animated stills). If video generation fails or is too slow, one click shows the fallback; nothing has to be rendered at that moment.

## 6. Functional requirements

- **FR-001** Fetch a pool of about 40 candidate stories from the configured publisher RSS feeds (the feed list is confirmed in the day 1-2 spike), deduplicate near-identical stories by clustering, and rank the clusters by cross-source coverage, then recency. A Tavily news search (topic news, last day, restricted to the same publishers) may be added as a second candidate source if the spike shows it improves the list; the ranking rule stays the same.
- **FR-002** Article text and manual paths. (a) The text of the five chosen articles is fetched with the Tavily Extract API, as plain text where the API offers it. (b) If Extract fails for an article, fall back to the feed's own description of the story, then to text pasted by the presenter. (c) The presenter can paste 5 URLs instead of using FR-001; their text is fetched the same way. The ledger records which text source was used for each story.
- **FR-003** Evidence ledger. For each selected story store: URL, publisher, timestamp, text source, the article text (kept locally, never displayed), key facts (who/what/when/where), short quotes (25 words or fewer), and the names of real people mentioned. Every fact and quote carries a verbatim support span from the article text. Code verifies that each span occurs in the stored text (exact match after whitespace normalisation). Facts that fail are dropped and logged. Later stages may use only verified facts.
- **FR-004** Produce a 2-sentence neutral summary per story. Every sentence must cite at least one verified ledger fact id. A code citation checker rejects uncited sentences and unknown ids.
- **FR-005** Produce ONE storyline of 6 beats: beat 0 is an intro with no source; beats 1-5 map one each to stories 1-5; beat 5 also closes the story. The storyline uses the fixed cast and town (FR-008). It must not state or imply that the real events caused each other, and it contains no real person's name.
- **FR-006** Verification in two layers.
  - Code checks (blocking): schemas valid; 6 beats mapped as in FR-005; storyboard constraints of FR-016; every summary sentence cited; no person name from the ledger appears in the story, the storyboard or any image or video prompt (whole-word match on full names and surnames).
  - Verifier (a different agent from the Writer and the Director, on a different model): summaries consistent with the ledger facts; the story does not state or imply causation between the real events; no real person recognisable through description; no graphic content; satire targets the situation, not a private individual. The Verifier sees only the ledger, summaries, story and storyboard, not the other agents' reasoning.
  - Failures return with reasons to the agent that owns the failing part (max 2 loops in total). After that the run stops at the approval screen with the open failures listed. A run is never passed automatically.
- **FR-007** Human gates. (a) Pick exactly 5 headlines — a human pick by default, or the automatic LLM curation step (Step 3) that ranks the candidate pool by newsworthiness and writes `curation.json`. (b) Approve the script and storyboard with the cost estimate: approve, edit, or reject. After an edit the code checks and the Verifier run again, as in US3.
- **FR-008** Fixed cast and town. Three characters and the town are defined in the style bible. For each character there is one sheet image showing four views (front, three-quarter, side, back), and there is one town reference image. They are generated once for the project, the best are chosen by hand, and they are stored in `assets/cast/`. They are not regenerated during a run.
- **FR-009** Keyframes and comic. Generate one clean 16:9 keyframe per shot, with no text in the image, using the cast sheets and the town reference. The comic page uses the six keyframes flagged as comic panels (one per beat) in a 2-column, 3-row layout. Captions, bubbles and source markers are composited by code on copies; the clean keyframes are kept for the video.
- **FR-010** Video. 8-10 shots of 4-8 s each, image-to-video from each shot's keyframe, generated in parallel up to the provider's limit. Audio from the video model is discarded. Assemble with ffmpeg: transitions, subtitles (the narration text), narration (TTS), music bed, title card (3 s) and closing "Based on: 5 sources" card (5 s). Total running time is 45-59 s including the cards, strictly under one minute. Transitions fit within shot durations. If a narration clip is longer than its shot, the shot's last frame is held to fit, within the 59 s total.
- **FR-011** Run-level artifact folder: `runs/<date-time>/` with candidates.json, article_text/, ledger.json, summaries.md, story.json, storyboard.json, checks.json, keyframes/ (clean), panels/ (with text), audio/, shots/, comic.png, fallback.mp4, video.mp4, cost.json, run.log (stage timings, cost, approvals and overrides).
- **FR-012** Cost guard. Before generation, estimate the run's cost from the storyboard and the unit prices measured in the spike, and show it at the approval gate. Hard stop with a message before exceeding the per-run budget (default 25 USD, to be re-set after the spike). The guard covers image, video and TTS calls. LLM tokens are capped separately by the Swarmflow token budget and logged. Tavily credits are logged too; a run uses about 1-5 credits against a free allowance of 1,000 a month, so they are tracked but not budgeted in currency. A project budget across all runs is also tracked (provisional 300 USD: 8 rehearsal runs at up to 25 USD plus about 100 USD for development; re-set after the spike).
- **FR-013** Label. "AI-generated fiction" appears as a small mark on every video frame, in the comic footer, on the closing card and in the file metadata.
- **FR-014** Permission gates: network fetch only to allowlisted hosts (the feed hosts, the Tavily API and the chosen providers' API hosts; article pages are not fetched directly); paid media generation only after an approval record exists for the run; file writes only inside `runs/` (and `assets/cast/` during the one-off cast setup). Enforced by the Permission Engine where it can express the rule, and by the project's own guard otherwise (decided in the day 1-2 spike).
- **FR-015** Safety filter. A classifier tags each candidate story (violence, death, disaster casualties, crimes against individuals, minors). The default list shows the top 15 untagged stories. The UI shows the hidden count and a toggle (US1).
- **FR-016** Storyboard. Each shot has: shot_id, beat, source_ref (0 for the intro, otherwise 1-5), characters (at most 2 of the 3), camera, action, narration, dialogue (optional, for comic bubbles), comic_caption (panel shots only), duration_s, comic_panel (true or false). Constraints: 8-10 shots; every beat has at least one shot; exactly one comic_panel shot per beat; narration at most 2 words per second of the shot's duration; shot durations sum to 37-51 s, which with 8 s of cards gives 45-59 s. Transitions are included within shot durations.
- **FR-017** Fallback and recovery. Every run renders fallback.mp4 from the keyframes (pan and zoom only) with the same narration, subtitles, music and cards. A shot counts as failed on an API error, a timeout, or an output that fails a duration or resolution check. A failed shot is retried once and then replaced by its animated still. If TTS fails, the video is assembled with subtitles and music only.

## 7. Non-functional

- Text half (ledger to checks, excluding human choices) in 2 minutes or less. Full live run in 10 minutes or less, excluding human choices. This requires the per-article ledger calls and the shot generations to run in parallel.
- Cached demo run opens in under 10 seconds and is labelled on screen as cached, with its date.
- Reproducible: a run can be replayed from any stage using its stored outputs, with no new news fetch. Narration audio is cached per run.
- Works on one laptop plus API keys. No cloud deployment.

## 8. Success criteria (for the demo)

Measured on 5 rehearsal runs unless stated otherwise.

- SC-1 Comic and a video (generated or fallback) are produced in 5 of 5 runs. A generated-shot video, with at most 2 shots replaced by stills, is produced in at least 3 of 5. Both rates are reported.
- SC-2 Character check with 2 people who have not seen the cast sheets: they are shown the 6 clean panels and one frame from each shot, shuffled, and label every character appearance. At least 90% correct on panels and 80% on video frames.
- SC-3 Zero fabricated facts in summaries, checked by hand against the original article pages (not only against the ledger or the extracted text).
- SC-4 Planted-error test: of 10 seeded errors (see tasks T019), the code-checkable ones are all caught and at least 8 of 10 are caught overall. The catch rate is reported.
- SC-5 Timing: text half in 2 minutes or less and full run in 10 minutes or less, excluding human choices, in at least 4 of 5 runs.
- SC-6 Cost: no run exceeds the per-run budget; mean cost per run is reported.
- SC-7 Backup: the cached run opens in under 10 seconds and the backup video plays with the network off.
- SC-8 Presenter can explain every stage of the agent pipeline in under 2 minutes.

## 9. Risks

| Risk | Mitigation |
|------|-----------|
| Schedule does not fit the deadline | Two-track plan for two people; solo scope and cut list defined in plan.md and tasks.md; date to be confirmed (open question 1). |
| Character drift between shots | Fixed, hand-picked cast sheets with four views (D8), at most 2 characters per shot, short shots, simple designs (round bodies, strong colours, few props), cut away quickly. |
| Video model slow or down during demo | Hybrid demo with cached run (D7), fallback video rendered in every run (D6), pre-rendered backup. |
| Framework cannot be embedded as planned | Four questions answered in the day 1-2 spike, each with a named fallback (plan.md section 2). |
| Misleading story linking real events | D2, FR-005, FR-006, labelled fiction. |
| Ledger extraction invents a fact | Verbatim support spans matched by code (FR-003); SC-3 checked against the articles. |
| Real people or tragedies in the news | Safety filter (FR-015); name check in code (FR-006); presenter picks from the filtered list by default. |
| Heavy news day leaves too few light stories | Pool of 40; hidden count shown; manual path; cached run (US1). |
| Tavily unavailable, or Extract fails on a publisher | Per-article fallback to the feed description, then pasted text (FR-002); cached run. Extract success rate per publisher is measured in the spike. |
| Generated text garbled | D5. |
| Cost overrun | FR-012, short shots, 720p generation, project budget tracked. |
| Trademark | D1. |

## 10. Out of scope

Accounts, payments, mobile app, daily schedule, social posting, multi-language, personalization, real-person likeness, long video. Not scheduled, optional if time remains: 9:16 export; a vision check that compares each shot with the cast sheets.

## 11. Open questions (defaults used if unanswered)

1. Presentation date and team size? The presenter confirmed a two-person split and a presentation roughly two weeks from 2026-10-11; exact date remains TBD. Working target: ready by end of Thursday 2026-10-22, working Sunday to Thursday. A solo variant remains in plan.md for contingency.
2. Preferred news sources? Default candidates, to be confirmed in the spike: BBC, the Guardian, NPR, Al Jazeera, plus Times of Israel or Ynet for local news. Reuters ended its public RSS feeds in 2020 and AP's own site feeds stopped in 2024, so neither is used. The feeds supply the candidate list; the article text comes from Tavily Extract (FR-002).
3. Output language? Default: English captions. Hebrew would need RTL handling in the compositor (about 1 extra day).
4. Which image, video and TTS providers? Decided in the day 1-2 spike by quality, price, latency, concurrency and reference-image support on one test shot.
5. Presentation audience and length? Default: 10-15 minutes with the hybrid demo of D7.

## 12. Revision history

Revision 2 (2026-10-11) applies the 23 review items of 2026-10-10.

| Item | Change | Where |
|------|--------|-------|
| 1 | Deadline assumption stated; date is open question 1 | Header, section 11; plan.md section 5 |
| 2 | Schedule rebuilt in two tracks with honest hours | plan.md section 5; tasks.md |
| 3 | Storyboard moved before verification and approval | D4, US3, FR-006, FR-007 |
| 4 | Beats fixed: intro plus five, beat 5 closes | FR-005 |
| 5 | One clean keyframe per shot; comic uses six | D10, US4, FR-009 |
| 6 | Narration, comic caption and dialogue fields with word cap | FR-016, FR-010 |
| 7 | Guards built before the first paid pipeline call | FR-012, FR-014; tasks.md T007 |
| 8 | Ledger facts carry verbatim spans matched by code | US2, FR-003, SC-3 |
| 9 | Real-person names checked by code | FR-005, FR-006 |
| 10 | Verifier checks causation; loop limit and edit path defined | FR-006, FR-007 |
| 11 | Planted-error test | SC-4; tasks.md T019 |
| 12 | Reuters and AP feeds removed | Open question 2 |
| 13 | Safety classifier, pool of 40, hidden count | US1, FR-001, FR-015 |
| 14 | Extraction fallback chain | FR-002 |
| 15 | Fixed cast and town as project assets, four views | D8, FR-008 |
| 16 | Parallel generation required; spike criteria widened | FR-010, section 7; tasks.md T004 |
| 17 | Budget from measured unit prices; project budget | FR-012 |
| 18 | Fallback always rendered, pan and zoom only; TTS fallback | D6, US7, FR-017 |
| 19 | "Failed shot" defined; vision check optional | FR-017, section 10 |
| 20 | Persistent "AI-generated fiction" mark | D2, FR-013 |
| 21 | Framework questions and fallbacks | FR-014; plan.md section 2 |
| 22 | Hybrid demo defined | D7; plan.md section 7 |
| 23 | Success criteria tightened and extended | Section 8 |

Revision 3 (2026-10-11) adds Tavily for article text.

| Change | Where |
|--------|-------|
| RSS feeds stay the source of the candidate list; Tavily news search is an optional second source, decided in the spike | FR-001; plan.md section 3; tasks.md T003, T008 |
| Article text comes from Tavily Extract, with per-article fallbacks | FR-002; tasks.md T010 |
| Tavily credits logged; Tavily API added to the host allowlist | FR-012, FR-014 |
| SC-3 is checked against the original article pages | Section 8 |

Revision 4 (2026-10-13) records the JSON2Video evaluation and the pre-T034 quality
upgrade. JSON2Video was evaluated as the "true video model" and set aside: it is a
deterministic FFmpeg compositor (motion graphics + transitions + built-in TTS), not a
generative image-to-video model, its free tier is watermarked, and it has no server-side
dry-run/estimate endpoint — so the model-backed image-to-video path stays T043. Fish
Audio narration (free model) is now wired into the assembled videos (T044), and the
fallback pan/zoom honors the per-shot character focal point and alternates zoom
direction (T045). Findings are in `docs/api-notes.md`; provider decision in
`docs/provider-notes.md`.

| Change | Where |
|--------|-------|
| JSON2Video set aside (compositor, not generative); model-backed video stays T043 | Open question 4; FR-010; tasks.md T043 |
| Fish Audio narration wired into the assembled video/fallback (T044) | FR-010, FR-017; tasks.md |
| Fallback pan/zoom uses the focal point and alternates direction (T045) | FR-017, D6; tasks.md |
| Risk row for Tavily | Section 9 |

Revision 5 (2026-10-14) polishes the two remaining Gate 3 quality gaps: the assembler
now ducks the music bed under narration (T046) and the generated video is genuinely
animated (T047). D6 is clarified: its "pan and zoom only" constraint binds the
fallback renderer only — the generated video may animate (easing, parallax, poses) as
part of FR-010's image-to-video deliverable.

| Change | Where |
|--------|-------|
| Music bed sidechain-ducks under narration (T046) | FR-017; tasks.md |
| Generated video animates poses, parallax and dolly (T047) | FR-010; tasks.md |
| D6 clarified: fallback-only; generated video may animate | Section 5, D6 |

Revision 6 (2026-10-19) adds the LLM curation step (Step 3). The five featured
stories are now ranked and picked by an LLM on the existing DeepSeek provider
(`LLM_API_KEY`), replacing the deterministic coverage/recency ranking as the default
pick. The human pick-5 gate stays available (and the interactive UI may still
override), and the approve gate stays human.

| Change | Where |
|--------|-------|
| LLM curation ranks and picks the 5 stories, writing `curation.json` (T048) | FR-001, FR-007; tasks.md |
| Pipeline S2 auto-curates when no human ids are supplied | FR-007; tasks.md |
