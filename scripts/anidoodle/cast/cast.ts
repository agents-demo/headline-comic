// Headline Comic cast library (T022). Shared drawing recipes for the three
// fixed characters (courier, mayor, pigeon) and the town reference. Every
// function draws a single view centred on (0,0) at unit scale; the caller
// translates and scales. Palette and proportions are fixed in docs/style-bible.md.
// Pure functions only: no clock, no Math.random, no network.
import type { Ctx } from "./core";

// ---- palette (style-bible.md section 2) -------------------------------------
const SKY_TOP = "#8ec9dc";
const SKY_BOTTOM = "#f6e7bd";
const GROUND = "#668a69";
const CLAY_LIGHT = "#d1a56f";
const CLAY_DARK = "#c98b72";
const WINDOW = "#f4d88f";
const ROOF = "#8a5a4a";
const CANOPY = "#2e6f95";
const PATH = "#d9c49a";
const LAMP = "#f4c95d";
const INK = "#17212b";

// pigeon
const P_BODY = "#33475b";
const P_BELLY = "#d8e5e8";
const P_BEAK = "#f4c95d";
const P_WING = "#526b7e";
const P_EYE_W = "#fffaf0";

// courier
const C_CAP = "#2e6f95";
const C_BAND = "#f4c95d";
const C_TUNIC = "#3f6f8f";
const C_SKIN = "#e6b48a";
const C_BAG = "#8a5a2b";
const C_TROUSER = "#5a6472";
const C_SHOE = "#2f3640";
const C_LETTER = "#fff8e8";
const C_FLAP = "#d07858";

// mayor
const M_HAIR = "#6b4a2b";
const M_SKIN = "#e6b48a";
const M_SHIRT = "#f2e3c6";
const M_SASH = "#c0392b";
const M_GOLD = "#f4c95d";
const M_JACKET = "#3f6f8f";
const M_TROUSER = "#5a6472";
const M_SHOE = "#2f3640";

// ---- tiny drawing helpers (canvas 2D primitives only) -----------------------
function ell(ctx: Ctx, x: number, y: number, rx: number, ry: number, color: string, rot = 0) {
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.ellipse(x, y, rx, ry, rot, 0, Math.PI * 2);
  ctx.fill();
}
function dot(ctx: Ctx, x: number, y: number, r: number, color: string) {
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.fill();
}
function rect(ctx: Ctx, x: number, y: number, w: number, h: number, color: string) {
  ctx.fillStyle = color;
  ctx.fillRect(x, y, w, h);
}
function tri(ctx: Ctx, a: [number, number], b: [number, number], c: [number, number], color: string) {
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.moveTo(a[0], a[1]);
  ctx.lineTo(b[0], b[1]);
  ctx.lineTo(c[0], c[1]);
  ctx.closePath();
  ctx.fill();
}
function smile(ctx: Ctx, x: number, y: number, r: number) {
  ctx.strokeStyle = INK;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.arc(x, y, r, 0.15 * Math.PI, 0.85 * Math.PI);
  ctx.stroke();
}
// A limb as a thick rounded line from (x1,y1) to (x2,y2).
function limb(ctx: Ctx, x1: number, y1: number, x2: number, y2: number, w: number, color: string) {
  ctx.strokeStyle = color;
  ctx.lineWidth = w;
  ctx.lineCap = "round";
  ctx.beginPath();
  ctx.moveTo(x1, y1);
  ctx.lineTo(x2, y2);
  ctx.stroke();
}

// ===========================================================================
// THE COURIER — blue cap + yellow band, blue tunic, brown satchel, cream letter
// ===========================================================================

function courierHeadFront(ctx: Ctx) {
  ell(ctx, 0, -42, 21, 19, C_SKIN);
  ell(ctx, 0, -53, 23, 17, C_CAP);
  ell(ctx, 0, -45, 24, 5, C_BAND);
  ell(ctx, 0, -43, 25, 4, C_CAP); // brim
  dot(ctx, -8, -43, 2.6, INK);
  dot(ctx, 8, -43, 2.6, INK);
  smile(ctx, 0, -38, 5);
}
function courierHeadThreeQuarter(ctx: Ctx) {
  ell(ctx, 0, -42, 21, 19, C_SKIN);
  ell(ctx, -2, -53, 23, 17, C_CAP);
  ell(ctx, -2, -45, 24, 5, C_BAND);
  ell(ctx, 2, -43, 26, 4, C_CAP);
  dot(ctx, -3, -43, 2.6, INK);
  dot(ctx, 9, -43, 2.4, INK);
  smile(ctx, 2, -38, 4);
}
function courierHeadSide(ctx: Ctx) {
  ell(ctx, 0, -42, 21, 19, C_SKIN);
  ell(ctx, -4, -53, 23, 17, C_CAP);
  ell(ctx, -4, -45, 24, 5, C_BAND);
  ell(ctx, 2, -43, 26, 4, C_CAP);
  tri(ctx, [14, -46], [30, -42], [14, -38], C_SKIN); // nose
  dot(ctx, 7, -44, 2.6, INK);
  smile(ctx, 6, -37, 3);
}
function courierHeadBack(ctx: Ctx) {
  ell(ctx, 0, -45, 23, 20, C_SKIN);
  ell(ctx, 0, -53, 24, 18, C_CAP);
  ell(ctx, 0, -47, 25, 5, C_BAND);
  ell(ctx, 0, -43, 26, 4, C_CAP);
}

function courierBodyFront(ctx: Ctx) {
  ell(ctx, 0, 2, 24, 30, C_TUNIC);
  // satchel strap, left shoulder to right hip
  limb(ctx, -16, -22, 16, 20, 6, C_BAG);
  ell(ctx, 20, 8, 12, 15, C_BAG);
  // arms
  limb(ctx, -25, -10, -28, 14, 9, C_TUNIC);
  dot(ctx, -28, 18, 5.5, C_SKIN);
  limb(ctx, 25, -10, 28, 12, 9, C_TUNIC);
  dot(ctx, 28, 16, 5.5, C_SKIN);
  // letter in the right hand
  rect(ctx, 24, 12, 16, 12, C_LETTER);
  tri(ctx, [24, 12], [32, 18], [24, 24], C_FLAP);
  // legs
  rect(ctx, -15, 30, 12, 36, C_TROUSER);
  rect(ctx, 3, 30, 12, 36, C_TROUSER);
  rect(ctx, -17, 64, 19, 8, C_SHOE);
  rect(ctx, 1, 64, 19, 8, C_SHOE);
}
function courierBodyThreeQuarter(ctx: Ctx) {
  ell(ctx, 0, 2, 23, 30, C_TUNIC);
  limb(ctx, -18, -22, 14, 20, 6, C_BAG);
  ell(ctx, 19, 6, 11, 15, C_BAG);
  limb(ctx, -26, -10, -30, 13, 9, C_TUNIC);
  dot(ctx, -30, 17, 5.5, C_SKIN);
  limb(ctx, 24, -10, 29, 12, 9, C_TUNIC);
  dot(ctx, 29, 16, 5.5, C_SKIN);
  rect(ctx, 23, 12, 16, 12, C_LETTER);
  tri(ctx, [23, 12], [31, 18], [23, 24], C_FLAP);
  rect(ctx, -14, 30, 12, 36, C_TROUSER);
  rect(ctx, 4, 30, 12, 36, C_TROUSER);
  rect(ctx, -16, 64, 19, 8, C_SHOE);
  rect(ctx, 2, 64, 19, 8, C_SHOE);
}
function courierBodySide(ctx: Ctx) {
  ell(ctx, 0, 2, 22, 30, C_TUNIC);
  limb(ctx, -14, -22, 18, 18, 6, C_BAG); // satchel strap, one shoulder
  ell(ctx, 18, 4, 11, 15, C_BAG);
  limb(ctx, -24, -10, -30, 12, 9, C_TUNIC); // far arm
  limb(ctx, 22, -8, 27, 12, 9, C_TUNIC); // near arm
  dot(ctx, 27, 16, 5.5, C_SKIN);
  rect(ctx, 24, 12, 16, 12, C_LETTER);
  tri(ctx, [24, 12], [32, 18], [24, 24], C_FLAP);
  rect(ctx, -12, 30, 12, 36, C_TROUSER);
  rect(ctx, 3, 30, 12, 36, C_TROUSER);
  rect(ctx, -14, 64, 18, 8, C_SHOE);
  rect(ctx, 1, 64, 18, 8, C_SHOE);
}
function courierBodyBack(ctx: Ctx) {
  ell(ctx, 0, 2, 24, 30, C_TUNIC);
  limb(ctx, -18, -22, 14, 18, 6, C_BAG);
  ell(ctx, -20, 8, 12, 15, C_BAG);
  limb(ctx, -25, -10, -28, 14, 9, C_TUNIC);
  dot(ctx, -28, 18, 5.5, C_SKIN);
  limb(ctx, 25, -10, 28, 12, 9, C_TUNIC);
  dot(ctx, 28, 16, 5.5, C_SKIN);
  rect(ctx, -15, 30, 12, 36, C_TROUSER);
  rect(ctx, 3, 30, 12, 36, C_TROUSER);
  rect(ctx, -17, 64, 19, 8, C_SHOE);
  rect(ctx, 1, 64, 19, 8, C_SHOE);
}

export function drawCourierFront(ctx: Ctx) {
  courierHeadFront(ctx);
  courierBodyFront(ctx);
}
export function drawCourierThreeQuarter(ctx: Ctx) {
  courierHeadThreeQuarter(ctx);
  courierBodyThreeQuarter(ctx);
}
export function drawCourierSide(ctx: Ctx) {
  courierHeadSide(ctx);
  courierBodySide(ctx);
}
export function drawCourierBack(ctx: Ctx) {
  courierHeadBack(ctx);
  courierBodyBack(ctx);
}

// ===========================================================================
// THE MAYOR — brown hair, cream shirt, red sash, yellow medal
// ===========================================================================

function mayorHeadFront(ctx: Ctx) {
  ell(ctx, 0, -42, 21, 19, M_SKIN);
  ell(ctx, 0, -56, 22, 13, M_HAIR);
  dot(ctx, -8, -43, 2.6, INK);
  dot(ctx, 8, -43, 2.6, INK);
  smile(ctx, 0, -38, 5);
}
function mayorHeadThreeQuarter(ctx: Ctx) {
  ell(ctx, 0, -42, 21, 19, M_SKIN);
  ell(ctx, -3, -56, 22, 13, M_HAIR);
  dot(ctx, -3, -43, 2.6, INK);
  dot(ctx, 9, -43, 2.4, INK);
  smile(ctx, 2, -38, 4);
}
function mayorHeadSide(ctx: Ctx) {
  ell(ctx, 0, -42, 21, 19, M_SKIN);
  ell(ctx, -4, -56, 22, 13, M_HAIR);
  tri(ctx, [14, -46], [30, -42], [14, -38], M_SKIN); // nose
  dot(ctx, 7, -44, 2.6, INK);
  smile(ctx, 6, -37, 3);
}
function mayorHeadBack(ctx: Ctx) {
  ell(ctx, 0, -45, 22, 20, M_SKIN);
  ell(ctx, 0, -53, 23, 17, M_HAIR);
}

function mayorBodyFront(ctx: Ctx) {
  ell(ctx, 0, 2, 25, 31, M_SHIRT);
  // red sash across the chest, left shoulder to right hip
  limb(ctx, -18, -20, 16, 22, 11, M_SASH);
  dot(ctx, 2, 6, 5, M_GOLD); // medal at the sash centre
  limb(ctx, -26, -10, -29, 14, 9, M_JACKET);
  dot(ctx, -29, 18, 5.5, M_SKIN);
  limb(ctx, 26, -10, 29, 12, 9, M_JACKET);
  dot(ctx, 29, 16, 5.5, M_SKIN);
  rect(ctx, -15, 31, 12, 36, M_TROUSER);
  rect(ctx, 3, 31, 12, 36, M_TROUSER);
  rect(ctx, -17, 65, 19, 8, M_SHOE);
  rect(ctx, 1, 65, 19, 8, M_SHOE);
}
function mayorBodyThreeQuarter(ctx: Ctx) {
  ell(ctx, 0, 2, 24, 31, M_SHIRT);
  limb(ctx, -19, -20, 14, 22, 11, M_SASH);
  dot(ctx, 0, 5, 5, M_GOLD);
  limb(ctx, -27, -10, -31, 13, 9, M_JACKET);
  dot(ctx, -31, 17, 5.5, M_SKIN);
  limb(ctx, 25, -10, 30, 12, 9, M_JACKET);
  dot(ctx, 30, 16, 5.5, M_SKIN);
  rect(ctx, -14, 31, 12, 36, M_TROUSER);
  rect(ctx, 4, 31, 12, 36, M_TROUSER);
  rect(ctx, -16, 65, 19, 8, M_SHOE);
  rect(ctx, 2, 65, 19, 8, M_SHOE);
}
function mayorBodySide(ctx: Ctx) {
  ell(ctx, 0, 2, 23, 31, M_SHIRT);
  limb(ctx, -16, -20, 16, 22, 11, M_SASH);
  dot(ctx, 1, 6, 5, M_GOLD);
  limb(ctx, -25, -10, -31, 12, 9, M_JACKET);
  limb(ctx, 23, -8, 28, 12, 9, M_JACKET);
  dot(ctx, 28, 16, 5.5, M_SKIN);
  rect(ctx, -12, 31, 12, 36, M_TROUSER);
  rect(ctx, 3, 31, 12, 36, M_TROUSER);
  rect(ctx, -14, 65, 18, 8, M_SHOE);
  rect(ctx, 1, 65, 18, 8, M_SHOE);
}
function mayorBodyBack(ctx: Ctx) {
  ell(ctx, 0, 2, 25, 31, M_JACKET);
  limb(ctx, -18, -20, 16, 20, 11, M_SASH);
  limb(ctx, -26, -10, -29, 14, 9, M_JACKET);
  dot(ctx, -29, 18, 5.5, M_SKIN);
  limb(ctx, 26, -10, 29, 12, 9, M_JACKET);
  dot(ctx, 29, 16, 5.5, M_SKIN);
  rect(ctx, -15, 31, 12, 36, M_TROUSER);
  rect(ctx, 3, 31, 12, 36, M_TROUSER);
  rect(ctx, -17, 65, 19, 8, M_SHOE);
  rect(ctx, 1, 65, 19, 8, M_SHOE);
}

export function drawMayorFront(ctx: Ctx) {
  mayorHeadFront(ctx);
  mayorBodyFront(ctx);
}
export function drawMayorThreeQuarter(ctx: Ctx) {
  mayorHeadThreeQuarter(ctx);
  mayorBodyThreeQuarter(ctx);
}
export function drawMayorSide(ctx: Ctx) {
  mayorHeadSide(ctx);
  mayorBodySide(ctx);
}
export function drawMayorBack(ctx: Ctx) {
  mayorHeadBack(ctx);
  mayorBodyBack(ctx);
}

// ===========================================================================
// PIGEON (Pip) — grey-blue body, pale belly, yellow beak/legs, swept wing
// ===========================================================================

// Front: facing the viewer.
export function drawPigeonFront(ctx: Ctx) {
  ell(ctx, 0, 4, 40, 48, P_BODY);
  ell(ctx, 0, 16, 24, 32, P_BELLY);
  ell(ctx, 0, -46, 25, 23, P_BODY);
  tri(ctx, [-7, -40], [7, -40], [0, -28], P_BEAK); // beak points toward viewer
  dot(ctx, -9, -50, 3.4, P_EYE_W);
  dot(ctx, -8, -50, 1.8, INK);
  dot(ctx, 9, -50, 3.4, P_EYE_W);
  dot(ctx, 10, -50, 1.8, INK);
  ell(ctx, -37, 4, 12, 32, P_WING); // wings
  ell(ctx, 37, 4, 12, 32, P_WING);
  rect(ctx, -11, 52, 6, 24, P_BEAK); // legs
  rect(ctx, 5, 52, 6, 24, P_BEAK);
}

// Three-quarter: the Gate 0 proof pose, cleaned up and static.
export function drawPigeonThreeQuarter(ctx: Ctx) {
  ell(ctx, 0, 8, 48, 60, P_BODY, -0.08);
  ell(ctx, -5, 24, 28, 40, P_BELLY, -0.12);
  ell(ctx, 7, -49, 34, 32, P_BODY);
  tri(ctx, [39, -49], [70, -40], [39, -31], P_BEAK);
  dot(ctx, 20, -57, 9, P_EYE_W);
  dot(ctx, 23, -57, 3.6, INK);
  ell(ctx, -20, 0, 32, 15, P_WING, -0.45);
  rect(ctx, -20, 66, 7, 24, P_BEAK);
  rect(ctx, 8, 66, 7, 24, P_BEAK);
}

// Side: profile facing right.
export function drawPigeonSide(ctx: Ctx) {
  ell(ctx, 0, 6, 46, 56, P_BODY, -0.05);
  ell(ctx, -6, 22, 26, 38, P_BELLY, -0.1);
  ell(ctx, 8, -48, 32, 30, P_BODY);
  tri(ctx, [38, -48], [70, -39], [38, -30], P_BEAK);
  dot(ctx, 22, -56, 8, P_EYE_W);
  dot(ctx, 25, -56, 3.2, INK);
  ell(ctx, -16, 2, 30, 14, P_WING, -0.4);
  tri(ctx, [-44, 34], [-66, 44], [-40, 52], P_WING); // tail
  rect(ctx, -14, 62, 6, 22, P_BEAK);
  rect(ctx, 10, 62, 6, 22, P_BEAK);
}

// Back: seen from behind, folded wings, no face.
export function drawPigeonBack(ctx: Ctx) {
  ell(ctx, 0, 4, 40, 48, P_BODY);
  ell(ctx, 0, -46, 25, 23, P_BODY);
  tri(ctx, [-6, -66], [6, -66], [0, -78], P_BODY); // back of the head tuft
  ell(ctx, -36, 4, 14, 34, P_WING);
  ell(ctx, 36, 4, 14, 34, P_WING);
  tri(ctx, [-14, 40], [14, 40], [0, 62], P_WING); // tail
  rect(ctx, -11, 52, 6, 24, P_BEAK);
  rect(ctx, 5, 52, 6, 24, P_BEAK);
}

// ===========================================================================
// TOWN reference — sky, ground, six clay buildings, path
// ===========================================================================

export function drawTown(ctx: Ctx) {
  // drawn in logical 1280x720; the caller sets the transform
  const W = 1280;
  const H = 720;
  const sky = ctx.createLinearGradient(0, 0, 0, H);
  sky.addColorStop(0, SKY_TOP);
  sky.addColorStop(1, SKY_BOTTOM);
  ctx.fillStyle = sky;
  ctx.fillRect(0, 0, W, H);
  ctx.fillStyle = GROUND;
  ctx.fillRect(0, H * 0.78, W, H * 0.22);
  for (let i = 0; i < 6; i++) {
    const bx = W * (0.05 + i * 0.16);
    const bh = H * (0.16 + (i % 3) * 0.04);
    ctx.fillStyle = i % 2 ? CLAY_LIGHT : CLAY_DARK;
    ctx.fillRect(bx, H * 0.78 - bh, W * 0.11, bh);
    ctx.fillStyle = ROOF;
    ctx.fillRect(bx - 4, H * 0.78 - bh - 10, W * 0.11 + 8, 10);
    ctx.fillStyle = WINDOW;
    for (let wx = 0; wx < 2; wx++) {
      for (let wy = 0; wy < 2; wy++) {
        ctx.fillRect(bx + W * (0.02 + wx * 0.05), H * 0.78 - bh + H * (0.04 + wy * 0.05), W * 0.016, H * 0.02);
      }
    }
  }
  // harbour path winding through the middle ground
  ctx.fillStyle = PATH;
  ctx.beginPath();
  ctx.moveTo(0, H * 0.88);
  ctx.quadraticCurveTo(W * 0.3, H * 0.72, W * 0.55, H * 0.8);
  ctx.quadraticCurveTo(W * 0.8, H * 0.88, W, H * 0.78);
  ctx.lineTo(W, H);
  ctx.lineTo(0, H);
  ctx.closePath();
  ctx.fill();
}
