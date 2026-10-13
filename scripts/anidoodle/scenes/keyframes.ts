// Headline Comic keyframe renderer (T023). A film with one shot per scene spec:
// `still.mjs keyframes` emits one clean 16:9 keyframe per shot. The scene data
// lives in ./scenes.ts (generated per run by src/providers/anidoodle_image.py
// from the deterministic storyboard -> scene mapping in src/skills/image_gen.py);
// all the drawing recipes come from ./cast (the fixed cast + town).
// No text is ever drawn here: captions/bubbles/markers are composited later.
import type { Ctx, Env } from "./core";
import type { Film } from "./film";
import { scenes } from "./scenes";
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
const BEAT = 24; // one beat per shot at 60 bpm

type View = (ctx: Ctx) => void;
type Spec = {
  shot_id: string;
  camera: { mode: "zoom"; scale: number; fx: number; fy: number } | { mode: "overhead" };
  characters: { name: string; view: string; x: number; y: number; scale: number }[];
  props: string[];
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

function drawOverhead(ctx: Ctx, spec: Spec) {
  ctx.fillStyle = "#f6f1e5";
  ctx.fillRect(0, 0, W, H);
  ctx.save();
  ctx.translate(W / 2, H / 2);
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

function drawScene(ctx: Ctx, spec: Spec) {
  if (spec.camera.mode === "overhead") {
    drawOverhead(ctx, spec);
    return;
  }
  const { scale, fx, fy } = spec.camera;
  ctx.save();
  ctx.translate(W / 2, H / 2);
  ctx.scale(scale, scale);
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

const shots = scenes.map((spec, i) => ({
  id: spec.shot_id,
  start: i * BEAT,
  end: (i + 1) * BEAT,
  draw: (ctx: Ctx, _local: number, env: Env) => {
    ctx.setTransform(env.scale, 0, 0, env.scale, 0, 0);
    drawScene(ctx, spec);
  },
}));

export const keyframes: Film = {
  meta: {
    title: "Headline Comic keyframes",
    W,
    H,
    fps: FPS,
    bpm: 60,
    durationFrames: scenes.length * BEAT,
  },
  assets: { images: {} },
  shots,
};
