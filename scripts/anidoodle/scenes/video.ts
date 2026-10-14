// Headline Comic video renderer (T027). One animated shot per scene spec, held
// for its storyboard duration. A camera push-in animates zoom shots; a pan drifts
// across the overhead map. Scene data lives in ./videoScenes.ts (generated per
// run by src/skills/video_gen.py); the drawing recipes come from ./cast. No text,
// captions or audio are added here — those are T028/T029 work on top of this
// silent render.
//
// Since T047 the zoom shots are no longer near-stills: the camera dollies on an
// ease-in-out-cubic curve in log2 zoom (the engine's dolly technique), the town,
// props and characters sit on separate depth planes that separate into parallax
// during the push (the engine's planeScale, re-normalised so the base composition
// is unchanged), and each character is animated from its normalized action via
// poseFor() — a walk swings and drifts, a point raises an arm, a pigeon flaps.
// Everything stays pure: poseFor is a function of the shot-relative frame only.
//
// bpm is set to 60 * FPS so the beat grid is one frame: shot boundaries land on
// any frame, which lets a fractional storyboard duration (e.g. 5.5 s) map to its
// exact frame count instead of snapping to whole beats.
import type { Ctx, Env } from "./core";
import type { Film } from "./film";
import type { Pose } from "./cast";
import { videoScenes } from "./videoScenes";
import { easeInOutCubic, poseFor } from "./motion";
import {
  drawTown,
  drawLamp,
  drawCanopy,
  drawFence,
  drawClock,
  drawMap,
  drawCourierFront,
  drawCourierThreeQuarter,
  drawCourierSide,
  drawCourierBack,
  drawMayorFront,
  drawMayorThreeQuarter,
  drawMayorSide,
  drawMayorBack,
  drawPigeonFront,
  drawPigeonThreeQuarter,
  drawPigeonSide,
  drawPigeonBack,
} from "./cast";

const W = 1280;
const H = 720;
const FPS = 24;
const BPM = FPS * 60; // beat = 1 frame (see module comment)

type View = (ctx: Ctx, pose?: Pose) => void;
type CharacterSpec = {
  name: string;
  view: string;
  x: number;
  y: number;
  scale: number;
  action: string;
};
type Spec = {
  shot_id: string;
  camera: { mode: "zoom"; scale: number; fx: number; fy: number } | { mode: "overhead" };
  characters: CharacterSpec[];
  props: string[];
  duration_s: number;
};

const CAST: Record<string, Record<string, View>> = {
  courier: {
    front: drawCourierFront,
    threeQuarter: drawCourierThreeQuarter,
    side: drawCourierSide,
    back: drawCourierBack,
  },
  mayor: {
    front: drawMayorFront,
    threeQuarter: drawMayorThreeQuarter,
    side: drawMayorSide,
    back: drawMayorBack,
  },
  pigeon: {
    front: drawPigeonFront,
    threeQuarter: drawPigeonThreeQuarter,
    side: drawPigeonSide,
    back: drawPigeonBack,
  },
};

// Fixed world-space positions for each story prop (drawn inside the camera zoom).
const PROP_PLACEMENT: Record<string, { draw: View; x: number; y: number; s: number }> = {
  lamp: { draw: drawLamp, x: W * 0.3, y: H * 0.62, s: 1.0 },
  canopy: { draw: drawCanopy, x: W * 0.5, y: H * 0.66, s: 1.05 },
  fence: { draw: drawFence, x: W * 0.5, y: H * 0.6, s: 1.0 },
  clock: { draw: drawClock, x: W * 0.74, y: H * 0.52, s: 0.9 },
};

const MARKER: Record<string, string> = { courier: "#2e6f95", mayor: "#c0392b", pigeon: "#33475b" };

// Camera + depth constants (see module comment for the engine rationale).
const ZOOM_PUSH = 1.07; // total dolly factor, matching the prior 7% push
const TOWN_DEPTH = 0.35; // background: positive z recedes during the push
const PROP_DEPTH = 0; // hero plane
const CHAR_DEPTH = -0.2; // foreground: negative z crosses the lens
const WALK_TRAVEL = 40; // px of horizontal drift across a walking character's shot

// The engine's planeScale: screen px per world unit on a plane at depth z.
function planeScale(zoom: number, z: number): number {
  return 1 / (1 / zoom + z);
}

// Relative depth scale: `base` at the shot's base zoom, re-normalised so every
// plane draws byte-identically to the flat composition at p=0 and only separates
// as the camera pushes. This preserves the locked style-bible frame.
function depthScale(zoom: number, z: number, base: number): number {
  return base * (planeScale(zoom, z) / planeScale(base, z));
}

// Dolly the zoom in log2 with ease-in-out-cubic, staying inside the original
// [scale, scale*ZOOM_PUSH] range. Interpolating in log2 keeps the push uniform in
// apparent size (the engine's technique).
function dollyZoom(base: number, p: number): number {
  const lo = Math.log2(base);
  const hi = Math.log2(base * ZOOM_PUSH);
  return Math.pow(2, lo + (hi - lo) * easeInOutCubic(p));
}

// Horizontal drift for a character across the shot; walkers cross the scene,
// everyone else holds position.
function travelX(action: string, p: number): number {
  return action === "walk" ? WALK_TRAVEL * (p - 0.5) : 0;
}

function drawOverhead(ctx: Ctx, spec: Spec, p: number) {
  ctx.fillStyle = "#f6f1e5";
  ctx.fillRect(0, 0, W, H);
  ctx.save();
  // Pan the map left-to-right across the shot so the scene reads as moving even
  // though the character markers (the story anchors) stay put.
  ctx.translate(W / 2 + 40 * (2 * p - 1), H / 2);
  ctx.scale(2.5, 2.5);
  drawMap(ctx);
  ctx.restore();
  spec.characters.forEach((c, i) => {
    const x = W * (0.4 + 0.2 * i);
    const y = H * 0.5;
    // A gentle bob (and drift for walkers) keeps the markers alive.
    const pose = poseFor(c.action, p);
    const mx = x + travelX(c.action, p);
    const my = y - pose.bob;
    ctx.fillStyle = MARKER[c.name] || "#33475b";
    ctx.beginPath();
    ctx.arc(mx, my, 26, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#e6b48a";
    ctx.beginPath();
    ctx.arc(mx, my - 4, 10, 0, Math.PI * 2);
    ctx.fill();
  });
}

// Draw everything on one depth plane, centred on the focal point (fx, fy) at the
// plane's relative zoom. `fn` draws in world space.
function drawPlane(
  ctx: Ctx,
  fx: number,
  fy: number,
  base: number,
  zoom: number,
  z: number,
  fn: () => void,
) {
  const k = depthScale(zoom, z, base);
  ctx.save();
  ctx.translate(W / 2, H / 2);
  ctx.scale(k, k);
  ctx.translate(-fx, -fy);
  fn();
  ctx.restore();
}

function drawScene(ctx: Ctx, spec: Spec, p: number) {
  if (spec.camera.mode === "overhead") {
    drawOverhead(ctx, spec, p);
    return;
  }
  const { scale: base, fx, fy } = spec.camera;
  const zoom = dollyZoom(base, p);

  // Background: town (and the sky it paints) on the receding plane.
  drawPlane(ctx, fx, fy, base, zoom, TOWN_DEPTH, () => drawTown(ctx));

  // Hero plane: story props.
  for (const name of spec.props) {
    const place = PROP_PLACEMENT[name];
    if (!place) continue;
    drawPlane(ctx, fx, fy, base, zoom, PROP_DEPTH, () => {
      ctx.save();
      ctx.translate(place.x, place.y);
      ctx.scale(place.s, place.s);
      place.draw(ctx);
      ctx.restore();
    });
  }

  // Foreground plane: characters, animated from their normalized action.
  for (const c of spec.characters) {
    const draw = CAST[c.name]?.[c.view];
    if (!draw) continue;
    const pose = poseFor(c.action, p);
    drawPlane(ctx, fx, fy, base, zoom, CHAR_DEPTH, () => {
      ctx.save();
      ctx.translate(c.x + travelX(c.action, p), c.y);
      ctx.scale(c.scale, c.scale);
      draw(ctx, pose);
      ctx.restore();
    });
  }
}

let cursor = 0;
const shots = videoScenes.map((spec) => {
  const frames = Math.max(1, Math.round(spec.duration_s * FPS));
  const start = cursor;
  const end = cursor + frames;
  cursor = end;
  return {
    id: spec.shot_id,
    start,
    end,
    draw: (ctx: Ctx, local: number, env: Env) => {
      ctx.setTransform(env.scale, 0, 0, env.scale, 0, 0);
      const p = frames <= 1 ? 0 : local / (frames - 1);
      drawScene(ctx, spec, Math.min(1, p));
    },
  };
});

export const video: Film = {
  meta: {
    title: "Headline Comic video",
    W,
    H,
    fps: FPS,
    bpm: BPM,
    durationFrames: cursor,
  },
  assets: { images: {} },
  shots,
};
