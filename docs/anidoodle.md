# AniDoodle video path

Checked 2026-10-12 against the upstream README and engine tools.

## Decision

Use AniDoodle for the immediate deterministic, code-drawn video path. The Gate 0 proof script is `scripts/anidoodle/render_gate0.mjs`. It scaffolds an 8-second, 1280x720, 24 fps film, draws the same named courier pigeon in every frame, renders a silent MP4, and extracts two PNG frames from that clip. All generated artifacts go under `runs/<run-id>/`.

This is a local renderer, not an image-to-video API. The scene source is authored code; the AniDoodle renderer executes it frame by frame. The currently authored proof scene is deliberately small and is not yet wired to production storyboard input.

## Setup and run

Requirements: Node 20 or newer, FFmpeg and ffprobe on `PATH`, and an AniDoodle checkout with its engine at `skills/anidoodle/engine/`. The renderer also needs npm dependencies and a Playwright Chromium installation. AniDoodle was cloned at commit `06f8be2bef0faa94e7eb6009ef23b36a0ae7b8a8`. The script performs `npm ci` if dependencies are missing and installs Chromium.

```powershell
$env:ANIDOODLE_HOME = (Resolve-Path anidoodle).Path
$env:PATH = (Resolve-Path runs\_tools\ffmpeg\ffmpeg-9.0.1-essentials_build\bin).Path + ';' + $env:PATH
node scripts/anidoodle/render_gate0.mjs anidoodle-gate0
```

The script refuses to overwrite an unrelated run directory and validates that its output remains inside `runs/`. It can resume its own scaffold after a setup failure. It checks the exported duration is below 60 seconds. It writes `manifest.json`, `anidoodle-pip.mp4`, and `pip-frame-a.png` / `pip-frame-b.png`.

For a new scaffold, install npm dependencies and Chromium once before rendering:

```powershell
Push-Location runs\anidoodle-gate0\anidoodle
npm ci --no-audit --no-fund
npx playwright-core install chromium
Pop-Location
```

The initial dependency/browser setup took about two minutes for npm packages and downloaded Chromium and its headless shell. Once installed, reruns can set `ANIDOODLE_SKIP_SETUP=1` to skip package and browser setup. The runner itself is resumable after a setup failure.

AniDoodle's scaffold is a starter generator, not a storyboard converter. The T005 adapter in `src/providers/anidoodle.py` runs and validates the fixed, authored Gate 0 scene through the provider-neutral `VideoProvider` contract. It accepts a safe run ID and duration cap; it does not accept source code from run data. T027 will add the bounded mapping from validated storyboard fields to authored scenes.

## Price and audio

| Output | Provider price per output | Other cost |
|---|---:|---|
| AniDoodle still/frame | $0 | Local CPU/GPU time and storage |
| AniDoodle video render | $0 | Local CPU/GPU time and storage |
| TTS/audio | Deferred | No provider selected or request made |

The $0 values mean there is no per-image or per-video provider charge; they do not price engineering time, electricity, or machine capacity. The proof scene defines no score, so the MP4 is silent. Music, TTS, and model-generated video remain future work.

## External model backlog

Once video/audio approval is ready, add a dedicated model-backed video adapter alongside AniDoodle and compare it on the same storyboard fixture. Keep the project-level `VideoProvider` interface stable, require T007 approval and budget checks before paid calls, and keep any returned model audio discarded unless the separate audio path is approved.

Upstream references: [AniDoodle](https://github.com/alexgreensh/anidoodle), [scaffold tool](https://github.com/alexgreensh/anidoodle/blob/main/skills/anidoodle/engine/tools/scaffold.mjs), [render tool](https://github.com/alexgreensh/anidoodle/blob/main/skills/anidoodle/engine/tools/render.mjs). The run manifest records the checked-out commit so outputs can be traced to this exact source revision.

## T027 — production storyboard-to-video path (2026-10-13)

Confirmed against the engine source at commit `06f8be2bef0faa94e7eb6009ef23b36a0ae7b8a8`:

- `scaffold.mjs <dir> --film <name> --size WxH --duration s --fps N` writes `src/canvas-core/<name>.ts` (`export const <name>: Film`) and `src/hosts/page-<name>.ts`, and **refuses to overwrite** an existing film module (`die(...refusing to overwrite a film module)`). It also copies the whole engine `src`/`tools`/`package.json`/`tsconfig.json`, so a second scaffold for a *different* film name in an already-scaffolded dir is safe (it re-copies the engine and adds the new film files). `render_video.mjs` therefore guards with `if (!existsSync(src/canvas-core/video.ts))` before scaffolding `--film video`.
- `render.mjs <film> --out <path> --workers 2` resolves `src/hosts/page-<name>.ts` (via `buildPage`) and `src/canvas-core/<name>.ts` (via `requireFilm`), so the film's export name, the canvas-core file name and the host page name must all match. It renders frames through Playwright and encodes the MP4 with ffmpeg; the MP4 is always the film's own size.
- **`validate(film)` (in `canvas-core/film.ts`) runs in `hosts/page.ts:48` before frame 0 and throws `"timeline: ..."` on problems.** Its rules that shaped `scenes/video.ts`: shots must tile `[0, durationFrames)` exactly (`start === previous end`, final `end === durationFrames`); and `bpm` must give a whole-frame beat (`Number.isInteger(60/bpm * fps)`) **and every shot start must be a multiple of that beat**. With the default `bpm: 60`/`fps: 24` that forces shot boundaries onto whole seconds; `video.ts` instead sets `bpm = 60 * fps` (beat = 1 frame) so a fractional storyboard duration (e.g. 5.5 s) maps to its exact `Math.round(duration_s * fps)` frame count.
- `renderFrame` calls `shot.draw(ctx, frame - shot.start, env)`, so the `local` argument to `draw` is **shot-relative** (0 .. length-1). `video.ts` computes its camera progress as `local / (frames - 1)`.
- `render.mjs` accepts `--workers 2` (default is CPU-derived); the run is verified in-tool (determinism probe: forward-vs-reversed hash-identical frames) and prints a per-shot frame-cost budget report.
- The render needs ffmpeg/ffprobe on `PATH` (`render_video.mjs` checks both with `-version`). `AniDoodleVideoProvider._ffmpeg_bin_dir` discovers the vendored ffmpeg under `runs/_tools/ffmpeg/*/bin` and prepends it to `PATH`, so the adapter runs without manual PATH setup when the vendored copy is present.

A real fixture smoke render (`t023-fixture`, 8 shots, 44.0 s) produced `shots.mp4` at 1280x720/24 fps/1056 frames with 20/20 determinism, duration `44` from ffprobe, and `manifest.json` with `audio: "none"`.

## T028 — music-box narration bed (2026-10-13)

The narration bed is an original hand-written `musicBox` piece, `scripts/anidoodle/music/bed.ts` (`townHallSteps`): C lydian, 12/8 at 112, a four-bar melody over a triplet-eighth arp and a root bass, with a 1.6 s tail. It passes all hard `music.mjs check` gates (key/mode, ghost/reverb/masking, stems, novelty vs 17 shipped pieces) and renders deterministically to a 10.57 s, -16 LUFS, -5.72 dBTP WAV (`runs/music-sample/town-hall-steps.wav`).

The presenter listened to the 8-second sample and approved it; they describe the felt mood as "happy relax sleepy". The score's declared section mood stays `curious` (C lydian's raised 4th) — the listener's words win on how the piece *feels* and are recorded here rather than relabelling the score, because the style's mood vocabulary is fixed and the notes are approved as-is. Fitting this approved bed to the ~44 s film length is the remaining music step (`music.mjs render --fit --seconds N`).

## T047 — engine camera/easing formulas reused in the animated video (2026-10-14)

Confirmed against `canvas-core/camera.ts` at commit `06f8be2bef0faa94e7eb6009ef23b36a0ae7b8a8`; `scenes/video.ts` and `cast/motion.ts` reimplement these as pure functions (no `Math.random`/`Date`) so the determinism probe still passes:

- **Ease** (`EASE.inout`, easeInOutCubic): `u < 0.5 ? 4u³ : 1 - (-2u+2)³/2`. This is the engine's camera-default curve; `motion.ts` re-exports it as `easeInOutCubic`.
- **Plane scale** (`planeScale(c, z=0)`): `1 / (1/c.zoom + z)` — screen pixels per world unit on a depth plane at `z`. Positive `z` recedes during a push-in; negative `z` crosses the lens (foreground).
- **Zoom dolly**: the engine interpolates zoom in **log₂** so the push is uniform in apparent size; `video.ts`'s `dollyZoom` does the same over the existing `[scale, scale*1.07]` range.
- **Depth re-normalisation**: `video.ts` uses `depthScale(zoom, z, base) = base * planeScale(zoom,z)/planeScale(base,z)` so every plane draws byte-identical to the flat composition at progress 0 and only separates as the camera pushes — this preserves the locked style-bible frame instead of adopting the engine's 3D skeletal rig (a different art style than D5's flat-vector cast).
