#!/usr/bin/env node
// Render the fixed cast (three characters, four views each) and the town
// reference as AniDoodle stills, then store the four PNGs in assets/cast/.
// The scene code is committed under scripts/anidoodle/cast/ and copied into the
// scaffolded film project; the renderer only needs a browser (no ffmpeg).
// Requirements: an upstream AniDoodle checkout in ANIDOODLE_HOME, Node 20+.

import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { copyFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const runId = process.argv[2] ?? "anidoodle-cast";
if (!/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/.test(runId)) {
  throw new Error("run id may contain only letters, digits, _ and -");
}

const anidoodleRoot = process.env.ANIDOODLE_HOME;
if (!anidoodleRoot) throw new Error("Set ANIDOODLE_HOME to an AniDoodle checkout");
const anidoodle = resolve(anidoodleRoot);
const anidoodleCommit = capture("git", ["-C", anidoodle, "rev-parse", "HEAD"]);
const scaffold = join(anidoodle, "skills", "anidoodle", "engine", "tools", "scaffold.mjs");
const stiller = join(anidoodle, "skills", "anidoodle", "engine", "tools", "still.mjs");
if (!existsSync(scaffold) || !existsSync(stiller)) {
  throw new Error(`AniDoodle scaffold/still tools not found under ${anidoodle}`);
}

const runDir = resolve(repo, "runs", runId);
if (!runDir.startsWith(resolve(repo, "runs") + sep)) {
  throw new Error("output must stay below runs/");
}
const filmDir = join(runDir, "anidoodle");
const resumable = existsSync(join(filmDir, "package.json")) && existsSync(join(filmDir, "tools", "still.mjs"));
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

mkdirSync(runDir, { recursive: true });
if (!resumable) run("node", [scaffold, filmDir, "--film", "castSheet", "--size", "1280x720", "--duration", "1", "--fps", "24"]);

// Copy the committed scene + library over the scaffold's stub film module.
const coreDir = join(filmDir, "src", "canvas-core");
copyFileSync(join(repo, "scripts", "anidoodle", "cast", "cast.ts"), join(coreDir, "cast.ts"));
copyFileSync(join(repo, "scripts", "anidoodle", "cast", "castSheet.ts"), join(coreDir, "castSheet.ts"));

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

run("node", [join(filmDir, "tools", "still.mjs"), "castSheet"], filmDir);

const sheets = ["courier", "mayor", "pigeon", "town"];
const assetsDir = join(repo, "assets", "cast");
mkdirSync(assetsDir, { recursive: true });
const frames = {};
const hashes = {};
for (const name of sheets) {
  const src = join(filmDir, "out", `still-castSheet-${name}.png`);
  if (!existsSync(src)) throw new Error(`still.mjs did not produce ${src}`);
  const dest = join(assetsDir, `${name}.png`);
  copyFileSync(src, dest);
  hashes[name] = sha256(dest);
  frames[name] = dest;
}

const manifest = {
  provider: "AniDoodle (local deterministic render)",
  source: "https://github.com/alexgreensh/anidoodle",
  sourceCommit: anidoodleCommit,
  localProviderPriceUsd: 0,
  localComputeCost: "not monetized; depends on the host machine",
  sheets: frames,
  sha256: hashes,
  viewOrder: "2x2 grid, top-left front, top-right three-quarter, bottom-left side, bottom-right back",
  note: "Authored once and chosen by hand (deterministic renderer produces one candidate, not a random batch).",
};
writeFileSync(join(runDir, "manifest.json"), `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
console.log(JSON.stringify(manifest, null, 2));
