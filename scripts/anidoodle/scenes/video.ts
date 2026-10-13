// Headline Comic video renderer (T027). One animated shot per scene spec, held
// for its storyboard duration. A camera push-in animates zoom shots; a pan drifts
// across the overhead map. Scene data lives in ./videoScenes.ts (generated per
// run by src/skills/video_gen.py); the drawing recipes come from ./cast. No text,
// captions or audio are added here — those are T028/T029 work on top of this
// silent render.
//
// bpm is set to 60 * FPS so the beat grid is one frame: shot boundaries land on
// any frame, which lets a fractional storyboard duration (e.g. 5.5 s) map to its
// exact frame count instead of snapping to whole beats.
import type { Ctx, Env } from "./core";
import type { Film } from "./film";
import { videoScenes } from "./videoScenes";
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

type View = (ctx: Ctx) => void;
type Spec = {
  shot_id: string;
  camera: { mode: "zoom"; scale: number; fx: number; fy: number } | { mode: "overhead" };
  characters: { name: string; view: string; x: number; y: number; scale: number }[];
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

// Smoothstep easing so the camera eases into and out of its push-in instead of a
// constant drift.
function easeInOut(t: number): number {
  return t * t * (3 - 2 * t);
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
    ctx.fillStyle = MARKER[c.name] || "#33475b";
    ctx.beginPath();
    ctx.arc(x, y, 26, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#e6b48a";
    ctx.beginPath();
    ctx.arc(x, y - 4, 10, 0, Math.PI * 2);
    ctx.fill();
  });
}

function drawScene(ctx: Ctx, spec: Spec, p: number) {
  if (spec.camera.mode === "overhead") {
    drawOverhead(ctx, spec, p);
    return;
  }
  const { scale, fx, fy } = spec.camera;
  const zoom = scale * (1 + 0.07 * easeInOut(p)); // a gentle push-in
  ctx.save();
  ctx.translate(W / 2, H / 2);
  ctx.scale(zoom, zoom);
  ctx.translate(-fx, -fy);
  drawTown(ctx);
  for (const name of spec.props) {
    const place = PROP_PLACEMENT[name];
    if (!place) continue;
    ctx.save();
    ctx.translate(place.x, place.y);
    ctx.scale(place.s, place.s);
    place.draw(ctx);
    ctx.restore();
  }
  for (const c of spec.characters) {
    const draw = CAST[c.name]?.[c.view];
    if (!draw) continue;
    ctx.save();
    ctx.translate(c.x, c.y);
    ctx.scale(c.scale, c.scale);
    draw(ctx);
    ctx.restore();
  }
  ctx.restore();
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
