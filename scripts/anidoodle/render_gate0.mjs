#!/usr/bin/env node
// Render one deterministic, silent AniDoodle proof clip and two sampled frames.
// Requires an upstream AniDoodle checkout in ANIDOODLE_HOME, Node 20+, ffmpeg,
// and ffprobe. All generated files stay in runs/<run-id>/.

import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const runId = process.argv[2] ?? "anidoodle-gate0";
if (!/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/.test(runId)) {
  throw new Error("run id may contain only letters, digits, _ and -");
}

const anidoodleRoot = process.env.ANIDOODLE_HOME;
if (!anidoodleRoot) throw new Error("Set ANIDOODLE_HOME to an AniDoodle checkout");
const anidoodle = resolve(anidoodleRoot);
const anidoodleCommit = capture("git", ["-C", anidoodle, "rev-parse", "HEAD"]);
const scaffold = join(anidoodle, "skills", "anidoodle", "engine", "tools", "scaffold.mjs");
const renderer = join(anidoodle, "skills", "anidoodle", "engine", "tools", "render.mjs");
if (!existsSync(scaffold) || !existsSync(renderer)) {
  throw new Error(`AniDoodle scaffold/render tools not found under ${anidoodle}`);
}

const runDir = resolve(repo, "runs", runId);
if (!runDir.startsWith(resolve(repo, "runs") + sep)) {
  throw new Error("output must stay below runs/");
}
const filmDir = join(runDir, "anidoodle");
const resumable = existsSync(join(filmDir, "package.json")) && existsSync(join(filmDir, "tools", "render.mjs"));
if (existsSync(runDir) && !resumable) throw new Error(`Refusing to overwrite existing run: ${runDir}`);

function run(command, args, cwd = repo) {
  const result = spawnSync(command, args, { cwd, encoding: "utf8", stdio: "inherit" });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`${command} exited with ${result.status}`);
}

function capture(command, args, cwd = repo) {
  const result = spawnSync(command, args, { cwd, encoding: "utf8" });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`${command} exited with ${result.status}: ${result.stderr}`);
  return result.stdout.trim();
}

function sha256(path) {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

const ffmpeg = process.platform === "win32" ? "ffmpeg.exe" : "ffmpeg";
const ffprobe = process.platform === "win32" ? "ffprobe.exe" : "ffprobe";
capture(ffmpeg, ["-version"]);
capture(ffprobe, ["-version"]);
mkdirSync(runDir, { recursive: true });
if (!resumable) run("node", [scaffold, filmDir, "--film", "headlineComic", "--size", "1280x720", "--duration", "8", "--fps", "24"]);

const filmSource = join(filmDir, "src", "canvas-core", "headlineComic.ts");
const source = `import type { Ctx, Env } from "./core";
import type { Film } from "./film";

const FPS = 24;
const DURATION = 8 * FPS;

// Pip uses one shape recipe and palette in every frame. Motion is a pure
// function of the frame number, so renders do not depend on wall-clock time.
function drawPip(ctx: Ctx, x: number, y: number, s: number, wing: number) {
  ctx.save();
  ctx.translate(x, y);
  ctx.scale(s, s);
  ctx.fillStyle = "#33475b";
  ctx.beginPath(); ctx.ellipse(0, 8, 54, 68, -0.08, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = "#d8e5e8";
  ctx.beginPath(); ctx.ellipse(-5, 24, 31, 43, -0.12, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = "#33475b";
  ctx.beginPath(); ctx.ellipse(7, -49, 39, 36, 0, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = "#f4c95d";
  ctx.beginPath(); ctx.moveTo(39, -49); ctx.lineTo(76, -39); ctx.lineTo(39, -29); ctx.closePath(); ctx.fill();
  ctx.fillStyle = "#fffaf0";
  ctx.beginPath(); ctx.arc(20, -58, 10, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = "#17212b";
  ctx.beginPath(); ctx.arc(23, -58, 4, 0, Math.PI * 2); ctx.fill();
  ctx.save(); ctx.translate(-23, 0); ctx.rotate(wing);
  ctx.fillStyle = "#526b7e";
  ctx.beginPath(); ctx.ellipse(-16, 0, 37, 16, -0.45, 0, Math.PI * 2); ctx.fill();
  ctx.restore();
  ctx.fillStyle = "#f4c95d";
  ctx.fillRect(-23, 72, 8, 28); ctx.fillRect(9, 72, 8, 28);
  ctx.restore();
}

const draw = (ctx: Ctx, local: number, env: Env) => {
  const W = env.W * env.scale, H = env.H * env.scale;
  const t = local / DURATION;
  const seconds = local / FPS;
  const sky = ctx.createLinearGradient(0, 0, 0, H);
  sky.addColorStop(0, "#8ec9dc"); sky.addColorStop(1, "#f6e7bd");
  ctx.fillStyle = sky; ctx.fillRect(0, 0, W, H);
  ctx.fillStyle = "#668a69"; ctx.fillRect(0, H * 0.78, W, H * 0.22);
  // Repeated town shapes establish a shared backdrop without generated assets.
  for (let i = 0; i < 6; i++) {
    const bx = W * (0.05 + i * 0.18);
    const bh = H * (0.14 + (i % 3) * 0.035);
    ctx.fillStyle = i % 2 ? "#d1a56f" : "#c98b72";
    ctx.fillRect(bx, H * 0.78 - bh, W * 0.12, bh);
    ctx.fillStyle = "#f4d88f";
    for (let wx = 0; wx < 2; wx++) for (let wy = 0; wy < 2; wy++) {
      ctx.fillRect(bx + W * (0.025 + wx * 0.05), H * 0.78 - bh + H * (0.04 + wy * 0.05), W * 0.018, H * 0.024);
    }
  }
  const flight = Math.max(0, Math.min(1, (t - 0.16) / 0.68));
  const eased = flight * flight * (3 - 2 * flight);
  const x = W * (0.2 + 0.58 * eased);
  const y = H * (0.61 - 0.20 * Math.sin(Math.PI * flight) + 0.018 * Math.sin(seconds * 5));
  const wing = Math.sin(seconds * 12) * 0.65;
  drawPip(ctx, x, y, Math.min(W, H) / 720, wing);
  // The envelope is the returning story token and stays with the same character.
  ctx.save(); ctx.translate(x + W * 0.06, y + H * 0.03); ctx.rotate(-0.16);
  ctx.fillStyle = "#fff8e8"; ctx.fillRect(0, 0, W * 0.055, H * 0.038);
  ctx.strokeStyle = "#d07858"; ctx.lineWidth = 3 * env.scale;
  ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(W * 0.027, H * 0.021); ctx.lineTo(W * 0.055, 0); ctx.stroke();
  ctx.restore();
};

export const headlineComic: Film = {
  meta: { title: "Pip Delivers the Headline", W: 1280, H: 720, fps: FPS, bpm: 60, durationFrames: DURATION },
  assets: { images: {} },
  shots: [{ id: "pip-delivery", start: 0, end: DURATION, draw }],
};
`;
writeFileSync(filmSource, source, "utf8");

const nodeModulesBin = join(dirname(process.execPath), "node_modules", "npm", "bin");
const npmCli = join(nodeModulesBin, "npm-cli.js");
const npxCli = join(nodeModulesBin, "npx-cli.js");
const playwrightPackage = join(filmDir, "node_modules", "playwright-core", "package.json");
const typescriptPackage = join(filmDir, "node_modules", "typescript", "package.json");
if (process.env.ANIDOODLE_SKIP_SETUP === "1") {
  if (!existsSync(playwrightPackage) || !existsSync(typescriptPackage)) throw new Error("ANIDOODLE_SKIP_SETUP=1 requires npm dependencies already installed in the run directory");
} else {
  if (!existsSync(npmCli) || !existsSync(npxCli)) {
    throw new Error(`npm CLI scripts not found beside Node at ${nodeModulesBin}`);
  }
  if (!existsSync(playwrightPackage) || !existsSync(typescriptPackage)) run("node", [npmCli, "ci", "--no-audit", "--no-fund"], filmDir);
  run("node", [npxCli, "playwright-core", "install", "chromium"], filmDir);
}
const video = join(runDir, "anidoodle-pip.mp4");
run("node", [join(filmDir, "tools", "render.mjs"), "headlineComic", "--out", video, "--workers", "2"], filmDir);

const duration = Number(capture(ffprobe, ["-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", video]));
if (!Number.isFinite(duration) || duration >= 60) throw new Error(`Video duration must be below 60 seconds, got ${duration}`);
const frameA = join(runDir, "pip-frame-a.png");
const frameB = join(runDir, "pip-frame-b.png");
run(ffmpeg, ["-y", "-ss", "2", "-i", video, "-frames:v", "1", "-update", "1", frameA]);
run(ffmpeg, ["-y", "-ss", "6", "-i", video, "-frames:v", "1", "-update", "1", frameB]);

const manifest = {
  provider: "AniDoodle (local deterministic render)",
  source: "https://github.com/alexgreensh/anidoodle",
  sourceCommit: anidoodleCommit,
  localProviderPriceUsd: 0,
  localComputeCost: "not monetized; depends on the host machine",
  video,
  sha256: {
    video: sha256(video),
    frameA: sha256(frameA),
    frameB: sha256(frameB),
  },
  durationSeconds: duration,
  audio: "none",
  frames: [frameA, frameB],
  character: "Pip the courier pigeon; shared drawing function and palette",
};
writeFileSync(join(runDir, "manifest.json"), `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
console.log(JSON.stringify(manifest, null, 2));
