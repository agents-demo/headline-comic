// Headline Comic motion helpers (T047). Pure, deterministic pose/easing maths —
// no clock, no Math.random. `poseFor` maps a shot's normalized action (the same
// bounded vocabulary from src/skills/image_gen.py) and a shot-relative progress
// t in [0,1] to a set of zero-centred offsets the cast drawings apply to their
// limbs, body, head and (pigeon) wings. Easing mirrors the AniDoodle engine's
// EASE (see docs/anidoodle.md): easeInOutCubic is the camera default.
import type { Pose } from "./cast";

export const easeInOutCubic = (u: number): number =>
  u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2;

export const easeOut = (u: number): number => 1 - Math.pow(1 - u, 3);

const TAU = Math.PI * 2;
const clamp01 = (u: number): number => (u < 0 ? 0 : u > 1 ? 1 : u);

// Positive armL/armR raises the left/right arm (see the arm() helper in cast.ts);
// positive legL/legR swings a leg forward; bob is unit px (up is positive); flap
// is radians of wing rotation. All zero is the neutral, static pose.
export function poseFor(action: string, t: number): Pose {
  const p = clamp01(t);
  switch (action) {
    case "walk": {
      const ph = p * 2 * TAU; // two gait cycles over the shot
      const s = Math.sin(ph);
      return {
        armL: 0.5 * s,
        armR: -0.5 * s,
        legL: -0.55 * s,
        legR: 0.55 * s,
        lean: 0.09,
        head: 0,
        bob: 2.5 * Math.sin(ph),
        flap: 0,
      };
    }
    case "point": {
      const e = easeInOutCubic(p); // the arm raises over the shot and settles
      return {
        armL: 1.4 * e,
        armR: 0,
        legL: 0,
        legR: 0,
        lean: 0.06 * e,
        head: 0.05 * e,
        bob: 0,
        flap: 0,
      };
    }
    case "wave": {
      const e = easeInOutCubic(p);
      const rock = Math.sin(p * 3 * TAU); // the forearm rocks while raised
      return {
        armL: 1.1 * e + 0.22 * rock * e,
        armR: 0,
        legL: 0,
        legR: 0,
        lean: 0,
        head: 0.03,
        bob: 0,
        flap: 0,
      };
    }
    case "flutter": {
      const flap = Math.sin(p * 6 * TAU); // six wing beats
      return {
        armL: 0,
        armR: 0,
        legL: 0,
        legR: 0,
        lean: 0,
        head: 0,
        bob: 5 * Math.sin(p * 2 * TAU),
        flap: 0.6 * flap,
      };
    }
    case "work":
    case "gather": {
      const s = Math.sin(p * 2 * TAU);
      return {
        armL: 0.4 * s,
        armR: -0.4 * s,
        legL: 0,
        legR: 0,
        lean: 0.05,
        head: 0,
        bob: 2 * s,
        flap: 0,
      };
    }
    case "stand":
    default: {
      // a subtle idle bob so even a "still" shot keeps breathing
      return {
        armL: 0,
        armR: 0,
        legL: 0,
        legR: 0,
        lean: 0,
        head: 0,
        bob: 1.5 * Math.sin(p * 2 * TAU),
        flap: 0,
      };
    }
  }
}
