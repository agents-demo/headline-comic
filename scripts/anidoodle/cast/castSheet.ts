// Headline Comic cast sheet film (T022). Four one-frame shots — courier, mayor,
// pigeon, town — so `still.mjs castSheet` emits one PNG per sheet. Each character
// sheet lays its four views out in a 2x2 grid (top-left front, top-right
// three-quarter, bottom-left side, bottom-right back) with no text in the art.
import type { Ctx, Env } from "./core";
import type { Film } from "./film";
import {
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
  drawTown,
} from "./cast";

const W = 1280;
const H = 720;
const SHEET_BG = "#f6f1e5";

type View = (ctx: Ctx) => void;

function sheet(ctx: Ctx, views: [View, View, View, View]) {
  ctx.fillStyle = SHEET_BG;
  ctx.fillRect(0, 0, W, H);
  const centers: [number, number][] = [
    [320, 180],
    [960, 180],
    [320, 540],
    [960, 540],
  ];
  const scale = 2.0;
  views.forEach((view, i) => {
    ctx.save();
    ctx.translate(centers[i][0], centers[i][1]);
    ctx.scale(scale, scale);
    view(ctx);
    ctx.restore();
  });
}

const drawCourierSheet = (ctx: Ctx, _local: number, env: Env) => {
  ctx.setTransform(env.scale, 0, 0, env.scale, 0, 0);
  sheet(ctx, [drawCourierFront, drawCourierThreeQuarter, drawCourierSide, drawCourierBack]);
};
const drawMayorSheet = (ctx: Ctx, _local: number, env: Env) => {
  ctx.setTransform(env.scale, 0, 0, env.scale, 0, 0);
  sheet(ctx, [drawMayorFront, drawMayorThreeQuarter, drawMayorSide, drawMayorBack]);
};
const drawPigeonSheet = (ctx: Ctx, _local: number, env: Env) => {
  ctx.setTransform(env.scale, 0, 0, env.scale, 0, 0);
  sheet(ctx, [drawPigeonFront, drawPigeonThreeQuarter, drawPigeonSide, drawPigeonBack]);
};
const drawTownRef = (ctx: Ctx, _local: number, env: Env) => {
  ctx.setTransform(env.scale, 0, 0, env.scale, 0, 0);
  drawTown(ctx);
};

export const castSheet: Film = {
  // One shot per beat (24 frames at 24 fps / 60 bpm) so every shot sits on the
  // beat grid; each draw is static and still.mjs renders only its first frame.
  meta: { title: "Headline Comic cast sheets", W, H, fps: 24, bpm: 60, durationFrames: 96 },
  assets: { images: {} },
  shots: [
    { id: "courier", start: 0, end: 24, draw: drawCourierSheet },
    { id: "mayor", start: 24, end: 48, draw: drawMayorSheet },
    { id: "pigeon", start: 48, end: 72, draw: drawPigeonSheet },
    { id: "town", start: 72, end: 96, draw: drawTownRef },
  ],
};
