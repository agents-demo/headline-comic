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

## T014 — Director (2026-10-12)

The `storyboard` skill (`src/skills/storyboard.py`) makes a single DeepSeek call that turns the six-beat story into a storyboard. The model proposes 8-10 shots; code injects `shot_id` and `source_ref` (always equal to `beat`), clamps each `duration_s` into 4-8 s, keeps at most two cast characters per shot, forces exactly one comic panel per beat, and validates against `schemas/storyboard.schema.json`. The aggregate narration word-rate (≤2 words/s) and 37-51 s duration-sum rules stay in the T015 checks skill.

A live run over the T013 story produced a schema-valid 10-shot storyboard totalling 48 s, with every shot's narration at or under 2 words per second. The school "guitar case" framing from the story carries into shots 3-4 and 7-8; the T016 Verifier and the pick-5 safety screen remain the guard for that. The run is saved under `runs/t014-live/`.

## T015 — checks (2026-10-12)

The `checks` skill (`src/skills/checks.py`) is the code layer of FR-006's two-layer verification. It runs 12 deterministic blocking checks over the ledger, summaries, story and storyboard: four JSON schema validations, six-beat mapping, the storyboard FR-016 constraints (one comic panel per beat, at most two cast characters per shot, narration at most two words per second, shot durations summing to 37-51 s), citation checks, and whole-word full-name/surname checks that no ledger person name appears in the story or storyboard. Each result carries an owning stage (`ledger`, `summary`, `story`, `storyboard`) so a failure can be routed back to the agent that owns it; the output is a schema-valid `checks.json`.

A live run over the cached T011-T014 artifacts passed all 12 checks, confirming the end-to-end text pipeline is internally consistent. The run is saved under `runs/t015-live/`.

## T016 — Verifier (2026-10-12)

The `verifier` skill (`src/skills/verifier.py`) is the independent second opinion in FR-006's two-layer verification. It runs on `deepseek-reasoner` — a different model from the generators' `deepseek-chat` — and sees only the ledger, summaries, story and storyboard. It returns pass/fail plus a reason for five fixed items: `verify-summaries`, `verify-causation`, `verify-real-people`, `verify-graphic`, and `verify-satire`. Code fixes the five ids and their owning stages and fails closed on any missing item; the output is a schema-valid `verifier.json`. The model is overridable with `LLM_VERIFIER_MODEL`. The DeepSeek adapter now accepts `temperature=None` so the reasoner call omits the temperature parameter it does not support.

A live run over the T011-T014 artifacts passed 4/5 and flagged `verify-causation`. That is a correct catch, not a false alarm: the underlying news of 2026-10-12 included a school incident, and the Writer had recast it as a harmless "guitar case popper" prank at a school — a weak/contradictory causal chain that also risks evoking a real tragedy. This is exactly the kind of issue the Verifier exists to flag; the T017/T018 wiring will route it back to the Writer (max two loops, then stop at approval with failures listed). The run is saved under `runs/t016-live/`.

## T017 — HITL gates and approval screen (2026-10-12)

The two human gates live in `src/flow/hitl.py` as pure functions and `src/ui/render.py` renders the approval screen deterministically. One non-obvious detail worth recording: the T016 Verifier emits its checks with `owner` set to the stage the failure routes back to (`summary` for `verify-summaries`, `story` for the rest) — the same `owner` values code checks use — so the approval gate tells a code check from a Verifier check by which document it came from (`checks.json` vs `verifier.json`), never by `owner`. Code-check failures block approval and cannot be overridden; only failing Verifier checks may be overridden, one id at a time, and each override is appended to `run.log`. The approval record (`approval.json`) is what the T007 guard reads back before any paid media call.

## AniDoodle video spike - complete (2026-10-12)

AniDoodle is selected as the immediate local, code-drawn video path. Its direct per-still/frame price and per-video price are both USD 0 because rendering is local and does not call a paid generation provider. Local CPU time, storage, and engineering time are not included in those unit prices. Audio is disabled; no TTS or music request has been made. Full integration notes and the runnable proof script are in `docs/anidoodle.md` and `scripts/anidoodle/render_gate0.mjs`.

The script rendered an 8-second, 1280x720, 24 fps silent H.264 MP4 (192 frames) plus two PNG frames of the same code-drawn courier pigeon. AniDoodle source commit: `06f8be2bef0faa94e7eb6009ef23b36a0ae7b8a8`. FFmpeg 9.0.1 Essentials binaries were hash-verified and extracted under ignored `runs/_tools/` after Winget's portable installation hit an access-denied error. The AniDoodle renderer reported 4.7 seconds for 192 frames (41.2 fps end to end, including build, browser launch, rendering and encode); draw median 4 ms, p95 11 ms, max 26 ms. It reported 6/6 determinism probes identical across page/order changes. ffprobe confirmed 1280x720, 24 fps, 192 frames, 8 seconds, and no audio stream.

Visual review of `runs/anidoodle-gate0/pip-frame-a.png` and `pip-frame-b.png` confirms the same pigeon character and palette at distinct positions in the scene. Quality is sufficient for the Gate 0 consistency/render proof. The art is clean flat vector geometry and does not yet match the planned clay/miniature style; the proof scene is not mapped from production storyboard input. Local direct provider price remains USD 0 per image/frame and USD 0 per video. This excludes local compute, storage, and authoring time. AniDoodle uses code-authored scenes and this proof did not use reference images or first/last-frame inputs; local renderer concurrency was set to two pages.

Artifacts and manifest are under ignored `runs/anidoodle-gate0/`: `anidoodle-pip.mp4`, `pip-frame-a.png`, `pip-frame-b.png`, and `manifest.json`. The render command and setup notes are in `docs/anidoodle.md`.

The upstream README documents Node 20+, the scaffold/render tools, Playwright Chromium, and FFmpeg for motion output. The renderer includes an MP4 path that omits the audio track when the scene supplies no audio. Current upstream reference: [AniDoodle README](https://github.com/alexgreensh/anidoodle), [scaffold tool](https://github.com/alexgreensh/anidoodle/blob/main/skills/anidoodle/engine/tools/scaffold.mjs), [render tool](https://github.com/alexgreensh/anidoodle/blob/main/skills/anidoodle/engine/tools/render.mjs). The run manifest records the checked-out commit.

## T028 — Fish Audio narration adapter + tts_gen skill (2026-10-13)

Fish Audio is the narration provider (free `s2.1-pro-free` model). FreeTTS was tried first but is unreachable from the presenter's corporate network (the secure web gateway resets `freetts.org`), so Fish Audio replaced it. The adapter (`src/providers/fishaudio.py`) is confirmed against Fish Audio's quickstart docs (checked 2026-10-13):

- `POST https://api.fish.audio/v1/tts` with header `Authorization: Bearer <FISH_API_KEY>`.
- The model is selected by an HTTP **header** `model` (default `s2.1-pro-free`), not a body field.
- Body: `text` (required), `format` (default `mp3`), and an optional `reference_id` voice — omit it for the default voice.
- Response `200` is the audio bytes directly (no URL, no base64), written to `<shot_id>.mp3`.
- Errors: 401 invalid/missing key, 402 out of credits, 400 bad `reference_id`/parameters, 429 rate limit. Free-tier numeric limits are not documented in the quickstart.

`FISH_BASE_URL` holds the full POST endpoint; the adapter sends the key only to the hardcoded `api.fish.audio` host (FR-014). Duration is read with ffprobe (vendored under `runs/_tools` when present).

The `tts_gen` skill (`src/skills/tts_gen.py`) maps each storyboard shot's `narration` to one clip cached in `runs/<run-id>/audio/`; a `narration.json` manifest makes reruns read-only and free. The free model bills $0 per 1,000 characters, so the happy path needs no approval record; a shot whose clip cannot be produced after retries degrades to subtitles-only (`spoken=False`, FR-017) instead of failing the run. The `hold_last_frame` overrun (FR-010) is computed as `clip.duration_s - shot.duration_s` when positive. The adapter and skill are unit-tested with mocked HTTP; a live smoke test (`scripts/tts_smoke.py`) must run from a network that can reach `api.fish.audio` (the corporate gateway may block it, as it did `freetts.org`).

The music bed half of T028 is the `music_gen` skill (`src/skills/music_gen.py`). The bed is a committed local asset — `scripts/anidoodle/music/bed.ts` ("Town Hall Steps", a hand-written C-lydian music-box phrase of ~8.6 s) — rendered through the AniDoodle music engine as a **seamless loop** (`node tools/music.mjs render <score>#townHallSteps <out> --loop`) from the run's scaffolded `anidoodle/` film dir (which carries `node_modules`/esbuild and `tools/music.mjs` after T027), then repeated to the film length with ffmpeg (`-stream_loop -1 -i loop.wav -t N`). Important confirmed behaviour: `--fit` only stretches a score (tempo/`refit`) and **pads a short bed with silence** — the original `--seconds N --fit` call produced a 47.5 s `bed.wav` whose music stopped at ~11.7 s — so the bed must be rendered as a loop and repeated, never `--fit`. The engine's `render` command only needs `ffmpeg` on PATH (its `decode` meters the result); `sh`/`ffmpegEbu` are used by its `meter` command, not by `render`. `music_gen.film_duration_s` computes the assembled film length deterministically (shot durations + `hold_last_frame_s` overruns + the 3 s title card + the 5 s closing card, minus the crossfade overlap) and `render_music_bed` verifies the output's duration (ffprobe) and integrated loudness (ffmpeg `ebur128`, parsed from the `Integrated loudness:` summary, not the per-frame lines). The loop is mastered to −16 LUFS by the engine; the skill asserts that within 1 dB. The bed is local and $0, so there is no budget line. One platform gotcha recorded: when Git Bash exports a `PATH` whose first element is `C:/...`, its MSYS2 runtime mangles it (splits on the drive colon and remaps the rest under the Git install), so `music.mjs` reports `spawnSync ffmpeg ENOENT`; the fix is the POSIX form `/c/...` for the PATH export, or (as the skill does) letting Python's `subprocess` pass a native `C:\...;...` PATH directly.

## T029 — ffmpeg assembly (`assemble` skill) (2026-10-13)

`src/skills/assemble.py` turns T027's silent `shots.mp4` into the finished cut. It is local and $0, so there is no budget line. The key deterministic piece is `timeline()`: segments are `title(3 s) + shots(each storyboard `duration_s` + its `hold_last_frame_s` overrun) + closing(5 s)`, with a 0.5 s `xfade=transition=fade` joining every adjacent pair (so the fixture's 8 shots + 2 cards = 10 segments collapse to 47.5 s). `music_gen.film_duration_s` was updated to subtract the same `(n_shots + 1) × 0.5` overlap, so the bed renders to exactly the cut length.

Confirmed ffmpeg mechanics that the skill relies on:
- **Chained xfade offsets** — joining segment *k* into the accumulated stream uses `offset = sum(durations[0..k-1]) - k × 0.5`; each xfade shortens the total by the transition duration.
- **Image → video segment** — `-loop 1 -t N -i card.png -r 24 -vf scale=1280:720,format=yuv420p,setsar=1`.
- **Video shot + hold-last-frame** — `-ss <start> -t <dur> -vf setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration=<hold>` (accurate seek by placing `-ss`/`-t` after `-i`).
- **Narration offsets** — `adelay=<ms>:all=1` per clip, then `amix=inputs=N:normalize=0`; the bed gets `volume=0.4,afade=t=out:st=<total-2>:d=2`, and a final `alimiter=limit=0.98` guards the mix. Music-only when no clip is `spoken`.
- **Subtitle windows** — `overlay=0:0:enable='between(t,<start>,<end>)'` on a transparent 1280×720 PNG; the shot's fully-visible window is `[start_s, start_s + duration_s - 0.5]`.
- **Persistent mark** — `overlay=W-w-16:16` (top-right) with no `enable`, so it covers every frame including both cards.
- **Metadata** — `-metadata title=<story title> -metadata comment=AI-generated fiction -movflags +faststart`.

Output `runs/<run-id>/video.mp4` is ffprobe-verified (duration ≈ `total_s` and < 60 s, 1280×720, audio stream present). A live smoke assembled the t006 fixture to 47.58 s at 1280×720 with title/comment metadata; the subtitles-only fallback (music bed + storyboard-narration subtitles, no TTS) was exercised end-to-end.

## T030 — fallback pan/zoom renderer (`fallback_gen` skill) (2026-10-13)

`src/skills/fallback_gen.py` renders `runs/<run-id>/fallback.mp4` in **every** run (FR-017, D6). It produces the *same* finished cut as the generated video, but the silent footage is a pan/zoom over the still keyframes instead of the AniDoodle render. Per shot, `fallback_filter(duration_s, camera_mode)` builds an ffmpeg `zoompan` chain: a slow centered Ken Burns zoom-in (`z='min(zoom+0.0015,1.4)'`) for every shot except the overhead map, which gets a horizontal pan (`z='1.3'`, `x='(iw-iw/zoom)*on/<frames>'`); a 2× upscale (`scale=2560:1440`) before `zoompan` keeps the sub-pixel motion smooth. `fallback_shots_command` renders all shots in one ffmpeg invocation (one `-i` per keyframe, a per-input `zoompan`, then `concat=n=…:v=1:a=0`) into a silent `cards/fallback-shots.mp4`; `run` then delegates to `assemble.run(..., video_path=<shots>, output_name="fallback.mp4")`, so the fallback reuses the identical holds, crossfades, subtitles, narration mix, music bed, cards and metadata (pan and zoom only — no parallax, sprites or models).

**Naming aligned to spec FR-011** (both `fallback.mp4` and `video.mp4` are named run artifacts, plan.md S12/S14): the silent AniDoodle render is now `shots.mp4` (`render_video.mjs`, `AniDoodleVideoProvider`), and the assembled generated video is `video.mp4` (T029's `assemble.run` gained an `output_name` parameter; its old `final.mp4` name was a spec deviation). The fallback is `fallback.mp4`.

## T031 — per-shot Leader recovery (`video_recovery` skill) (2026-10-13)

`src/skills/video_recovery.py` implements the other half of FR-017: a shot counts as failed on an **API error**, a **timeout**, or an **output that fails a duration or resolution check**; it is retried once and then replaced by its animated still. The module is provider-agnostic — the per-shot video call is injected as `render(shot) -> ShotRenderResult` — so the same code drives a per-shot paid provider in T043; today AniDoodle is a whole-run local render that cannot fail per-shot, so the recovery path is exercised by deterministic tests (fake `render` callables) rather than a live render.

- `classify_failure` is the deterministic taxonomy: an exception is `timeout` (`TimeoutError`/`subprocess.TimeoutExpired`) or `api_error` (anything else); a returned result is `duration` when its length is off the shot's expected duration by more than `DURATION_TOLERANCE_S = 0.25`, or `resolution` when it is not 1280×720. No model is involved.
- `render_shot_with_recovery` calls `render` up to `MAX_ATTEMPTS = 2`, classifies each failure, and returns a `ShotOutcome` — `kind="generated"` with the provider's clip, or `kind="still"` with `attempts`/`reason`.
- The animated still is the fallback's own move: `still_command` reuses `fallback_gen.fallback_filter`, so a still is the same Ken Burns pan/zoom over the shot's keyframe (one clip per shot under `runs/<run-id>/shots/`).
- `recover_shots` runs every shot; `concat_outcomes_command`/`concat_shots` normalize each clip (`format=yuv420p,setsar=1`) and `concat` them into a silent `cards/recovered-shots.mp4`; `run` then logs a `shot_recovery` entry per shot and one `recovery_summary` to `run.log` and assembles `runs/<run-id>/video.mp4` through the shared assembler, so a failed shot degrades to its still without losing the whole generated video (SC-1).

## T044/T045 — narration wired into the run + focal-point fallback motion (2026-10-13)

T044 wires the T028 narration into the finished videos. `scripts/gate3.py` now synthesizes Fish Audio narration (free `s2.1-pro-free` model, `UnitPrice.create("fishaudio", "1000_characters", "0")`) and passes the returned clips into both `assemble_generated` and `assemble_fallback`, so `video.mp4` and `fallback.mp4` carry the spoken track (the assembler already `adelay`-offsets and `amix`es narration under the bed, T029). Without `FISH_API_KEY` the stage degrades to the subtitles-only FR-017 path (`--skip-narration` forces it); clips are cached via `audio/narration.json`. This also fixed two latent cost-record issues that a fresh `--force` run would have hit: the image stage now reserves the run quote with `planned_categories=("image","video","tts")` (one quote covers all three $0 lines), and the video unit price is now `per "shot"` rather than the invalid `"video"` unit. A live smoke confirmed the key authenticates and `api.fish.audio` is reachable; a seeded `gate3-nar` run passed 12/12 with 8/8 narration clips `spoken` and the narrated audio differing from the music-only mix.

T045 makes the fallback motion less flat. `fallback_filter(duration_s, camera_mode, *, fx=None, fy=None, direction="in")` now centres the `zoompan` window on the shot's character focal point `(fx, fy)` from `image_gen.scene_spec` (scaled 2× for the 2560×1440 input) instead of the frame centre, and `direction` selects a zoom-in (`min(1+(0.0015*on),1.4)`) or zoom-out (`max(1.4-(0.0015*on),1)`). `render_fallback_shots` reads each shot's camera spec and alternates in/out by shot index (the overhead map keeps its horizontal pan) — still pan-and-zoom only (D6), no parallax/sprites/models.

**JSON2Video evaluated and set aside** for T043: it is a deterministic FFmpeg compositor (not a generative image-to-video model), its free tier is watermarked and has no server-side dry-run. Findings are recorded in `docs/api-notes.md`.
