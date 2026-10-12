# Provider notes

## T003 — RSS feed probe (2026-10-11)

Fetched candidate RSS endpoints over HTTPS; requests were to feed URLs only, not article pages. Five feeds returned HTTP 200 with parseable XML; Al Jazeera timed out at 15 seconds in the sandbox and again at 30 seconds outside it.

| Publisher | Feed | HTTP result | Items in snapshot | Last 24 hours |
|---|---|---:|---:|---:|
| BBC | `https://feeds.bbci.co.uk/news/world/rss.xml` | 200 | 26 | 14 |
| The Guardian | `https://www.theguardian.com/world/rss` | 200 | 45 | 28 |
| NPR | `https://feeds.npr.org/1001/rss.xml` | 200 | 10 | 10 |
| The Times of Israel | `https://www.timesofisrael.com/feed/` | 200 | 13 | 13 |
| Ynet | `https://www.ynet.co.il/Integration/StoryRss3082.xml` | 200 | 30 | 23 |
| Al Jazeera | `https://www.aljazeera.com/xml/rss/all.xml` | timeout | — | — |

From the four feeds selected for activation, selected the ten newest items within 24 hours from each (40 candidates). A lexical title-clustering spike yielded 38 clusters. It found one Pope Leo surgery cluster across BBC/NPR/Ynet (3 items), two candidate merges. This validates some cross-source overlap; the production clustering method remains T008's decision.

The Times of Israel feed works technically, but its content-distribution guidance says article material should not be copied beyond headline/subheadline and link. Since this demo displays generated summaries based on article text, it is not enabled pending a terms review. Ynet is used as the local source; its published RSS conditions permit private, non-commercial use. The active list therefore has four working publishers: BBC, The Guardian, NPR, and Ynet. The feed list is in `config/news_feeds.json`.

## Tavily probe - completed 2026-10-12

The approved basic probe used one text Extract batch and one news Search. Its ten newest last-day RSS URLs were distributed 3 BBC, 3 The Guardian, 2 NPR and 2 Ynet. No article text was saved in the repository.

| Publisher | Basic Extract | Basic text result |
|---|---:|---|
| BBC | 3/3 | 3 usable; 481-2,841 words, title matched in each result |
| The Guardian | 0/3 | 3 failed with `Failed to fetch url` |
| NPR | 2/2 | 2 usable; 1,184-2,423 words, title matched in each result |
| Ynet | 2/2 | 2 thin; 115 and 125 words, title matched |
| Total | 7/10 | 5 usable, 2 thin, 3 failed |

For this probe, usable means a successful result with at least 120 words, at least 800 characters, and at least two title terms found in the first 3,000 characters. A successful result below either volume threshold is thin; failed URLs are unusable. This is a mechanical screen of extraction volume and headline alignment, not a human factual review.

An additional advanced Extract batch retried the two thin Ynet URLs and tested three current Guardian RSS URLs. Both Ynet articles became usable (1,144 and 1,300 words); all three Guardian articles failed again. A final advanced Extract tested a third current Ynet RSS article as a replacement for one failed Guardian URL; it was usable at 821 words. The revised ten-article set (3 BBC, 2 Guardian, 2 NPR, 3 Ynet) therefore has 8 usable results and 2 Guardian failures, meeting Gate 0's 8/10 extraction threshold. Guardian extraction remains unreliable; T010 must keep its per-article description/paste fallback.

The initial Extract response reported 1 credit and 0.77 seconds; basic Search reported 1 credit and 3.95 seconds. The five-URL advanced retry reported 1 credit and 0.10 seconds; the single-URL advanced replacement reported 0 credits and 0.01 seconds. Total reported usage across the probe was 3 credits (USD 0.024 at the listed USD 0.008 pay-as-you-go rate if billed), within the approved limit. Account plan and remaining free credits were not available to inspect. Request IDs: basic Extract `27577d8b-6bad-4808-a0ed-c065575533b6`; Search `72ae1d6f-285c-42a6-b497-4c03401bafe2`; advanced retry `b8f61c5c-c358-48d0-b492-01e96c493a2c`; advanced replacement `a7c065b0-d25b-4b48-96d5-08c1e7faba8b`.

The basic Search query was `top world news today`, with `topic=news`, `time_range=day`, and restricted domains for BBC, The Guardian, NPR and Ynet. It returned 10 results: 8 BBC, 1 NPR, 1 Ynetnews and none from The Guardian. Comparing against the ten newest RSS titles per publisher, 5/10 Search results had a lexical Jaccard title match of at least 0.30; one more result about the energy ceasefire appeared related on manual review. Search surfaced some additional headlines, but its strong BBC skew and missing Guardian results do not improve publisher balance. Keep the four-feed RSS list as the only candidate source; do not add Tavily Search for this MVP. The candidate ranking remains cross-publisher coverage, then recency.

Tavily API references: [Extract](https://docs.tavily.com/documentation/api-reference/endpoint/extract), [Search](https://docs.tavily.com/documentation/api-reference/endpoint/search), [Credits & Pricing](https://docs.tavily.com/documentation/api-credits), [Pricing](https://www.tavily.com/pricing). Checked 2026-10-12.

## T010 — Tavily Extract adapter + article_text skill (2026-10-12)

The Extract adapter is confirmed against Tavily's Extract docs (checked 2026-10-12): `POST https://api.tavily.com/extract` with bearer auth, a batch of up to 20 URLs; response `results[]` `{url, raw_content}`, `failed_results[]` `{url, error}`, `response_time`, `request_id`, and `usage {credits}` only when `include_usage=true`. Basic depth bills 1 credit per 5 successful extractions (failed URLs are free); `format=text` returns plain text in `raw_content`.

A live validation ran one basic Extract batch over the top-5 RSS candidates (3 Ynet, 1 BBC, 1 NPR). All five succeeded and the response reported `usage.credits = 1.0`, within the approved 1-credit limit. Word counts were 97, 203, 464, 1,243 and 1,253; `raw_content` includes page boilerplate/navigation, which the T011 ledger extraction must tolerate. The per-article fallback chain (Extract → feed description → pasted text) and text-source recording live in `src/skills/article_text.py`, with the adapter in `src/providers/tavily.py`. The feed path is live-validated; the pasted-URL and pasted-text paths are unit-tested only. The run is saved under `runs/t010-live/`.

## T011 — DeepSeek chat adapter + article ledger (2026-10-12)

The first real LLM provider is DeepSeek, exposed through its OpenAI-compatible chat completions endpoint. The adapter (`src/providers/llm.py`) reads `LLM_API_KEY`, `LLM_BASE_URL` and `LLM_MODEL` from `.env` via the encoding-tolerant loader in `src/env.py` (the `.env` is UTF-16 on Windows, which python-dotenv cannot parse; see `docs/api-notes.md`). Defaults are `https://api.deepseek.com` and `deepseek-chat`. Requests use `urllib` only and the host derived from `LLM_BASE_URL` is allowlisted per FR-014. `response_format: {"type": "json_object"}` is sent for JSON extraction calls.

A live validation ran the `article_ledger` skill over the five cached T010 articles (no new Tavily spend): five parallel DeepSeek calls produced facts/quotes/people with verbatim support spans, every proposed span matched the article text after whitespace normalisation (0 dropped), and the resulting `ledger.json` validates against `schemas/ledger.schema.json`. Fact counts ranged 8-35 and quotes 0-6 per story; the model over-extracts on longer articles, which the deterministic span check tolerates and later stages will trim by citation. The run is saved under `runs/t011-live/`.

## T012 — summariser + citation checker (2026-10-12)

The `summarise` skill reuses the DeepSeek adapter for two neutral sentences per story, grounded only in the verified ledger facts. A live run over the T011 ledger produced five schema-valid summaries with 0 citation errors (every sentence cited a real fact id). The deterministic `check_citations` rejects uncited sentences and unknown ids. Outputs are `summaries.json` (schema-valid) and `summaries.md` (FR-011). Saved under `runs/t012-live/`.

## T013 — Writer (2026-10-12)

The `story` skill (`src/skills/story.py`) makes a single DeepSeek call that turns the five summaries into one fictional story. The model proposes only a title and six beat texts; code injects `schema_version`, the fiction label, the fixed cast (`courier`, `mayor`, `pigeon`), `beat_index`, `source_ref` and the closing `ending` flag, then validates the result against `schemas/story.schema.json`. The prompt forbids real names and forbids implying one real news story caused another (FR-005).

A live run over the cached T012 summaries produced a schema-valid six-beat story with no validation errors. The model kept the fixed cast, avoided real names, and mapped beats 1-5 to sources 1-5 in order. One note for the T016 Verifier: because the source news included a school-related incident, the model's fiction set two beats at a school (a "guitar case popper" prank); nothing is graphic, but the school setting is something the Verifier and the final pick-5 safety screen should keep an eye on. The run is saved under `runs/t013-live/`.

## AniDoodle video spike - complete (2026-10-12)

AniDoodle is selected as the immediate local, code-drawn video path. Its direct per-still/frame price and per-video price are both USD 0 because rendering is local and does not call a paid generation provider. Local CPU time, storage, and engineering time are not included in those unit prices. Audio is disabled; no TTS or music request has been made. Full integration notes and the runnable proof script are in `docs/anidoodle.md` and `scripts/anidoodle/render_gate0.mjs`.

The script rendered an 8-second, 1280x720, 24 fps silent H.264 MP4 (192 frames) plus two PNG frames of the same code-drawn courier pigeon. AniDoodle source commit: `06f8be2bef0faa94e7eb6009ef23b36a0ae7b8a8`. FFmpeg 9.0.1 Essentials binaries were hash-verified and extracted under ignored `runs/_tools/` after Winget's portable installation hit an access-denied error. The AniDoodle renderer reported 4.7 seconds for 192 frames (41.2 fps end to end, including build, browser launch, rendering and encode); draw median 4 ms, p95 11 ms, max 26 ms. It reported 6/6 determinism probes identical across page/order changes. ffprobe confirmed 1280x720, 24 fps, 192 frames, 8 seconds, and no audio stream.

Visual review of `runs/anidoodle-gate0/pip-frame-a.png` and `pip-frame-b.png` confirms the same pigeon character and palette at distinct positions in the scene. Quality is sufficient for the Gate 0 consistency/render proof. The art is clean flat vector geometry and does not yet match the planned clay/miniature style; the proof scene is not mapped from production storyboard input. Local direct provider price remains USD 0 per image/frame and USD 0 per video. This excludes local compute, storage, and authoring time. AniDoodle uses code-authored scenes and this proof did not use reference images or first/last-frame inputs; local renderer concurrency was set to two pages.

Artifacts and manifest are under ignored `runs/anidoodle-gate0/`: `anidoodle-pip.mp4`, `pip-frame-a.png`, `pip-frame-b.png`, and `manifest.json`. The render command and setup notes are in `docs/anidoodle.md`.

The upstream README documents Node 20+, the scaffold/render tools, Playwright Chromium, and FFmpeg for motion output. The renderer includes an MP4 path that omits the audio track when the scene supplies no audio. Current upstream reference: [AniDoodle README](https://github.com/alexgreensh/anidoodle), [scaffold tool](https://github.com/alexgreensh/anidoodle/blob/main/skills/anidoodle/engine/tools/scaffold.mjs), [render tool](https://github.com/alexgreensh/anidoodle/blob/main/skills/anidoodle/engine/tools/render.mjs). The run manifest records the checked-out commit.
