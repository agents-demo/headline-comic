// "Town Hall Steps", a music-box bed for the headline-comic miniature town (T028).
//
// The mood is "curious": C lydian (the wondering mode — its raised 4th, F#, is the lift),
// 12/8 at 112, a bright pluck that asks in bars 1-2 and answers, landing home on the
// tonic, in bars 3-4. The style's sound numbers (musicBox + bell plucks, one early
// reflection, no tail) are the engine's; every note here is written by hand.
//
//   bar 0  question  C        melody rises E5->A5, rests open on the fifth
//   bar 1  question  D        the lydian II (D F# A): F#, the colour note, appears
//   bar 2  leaning   G        climbs D5->G5 the dominant
//   bar 3  answer    C        the climax C6 falls home to the tonic C5
//
// Bass holds the root (C3 D3 G3 C3); the arp cycles each chord in triplet eighths an
// octave under the melody. No sound-pack download: every voice is synthesized in code.
import { line, type Piece } from "../../../anidoodle/skills/anidoodle/engine/src/canvas-core/music/plan";

const mel = (t: number, s: string, v = 0.72) => line(t, s, { role: "melody", v, bpb: 4 });
const arp = (t: number, s: string, v = 0.5) => line(t, s, { role: "accomp", v, bpb: 4 });
const bass = (t: number, s: string, v = 0.62) => line(t, s, { role: "bass", v, bpb: 4 });

export const townHallSteps = (): Piece => {
  const melody = mel(0, [
    "E5:1 G5:1 A5:1 G5:1", //   0 C   rise, rest open on the fifth
    "F#5:1 A5:1 G5:1 F#5:1", // 1 D   the lydian #4 lifts, then steps back
    "D5:1 E5:1 F#5:1 G5:1", //  2 G   climb the dominant
    "C6:1 G5:1 E5:1 C5:1", //   3 C   the hook falls home to the tonic
  ].join(" | "));
  const arpeggio = arp(0, [
    "C4:1/3 E4:1/3 G4:1/3 C4:1/3 E4:1/3 G4:1/3 C4:1/3 E4:1/3 G4:1/3 C4:1/3 E4:1/3 G4:1/3",
    "D4:1/3 F#4:1/3 A4:1/3 D4:1/3 F#4:1/3 A4:1/3 D4:1/3 F#4:1/3 A4:1/3 D4:1/3 F#4:1/3 A4:1/3",
    "B3:1/3 D4:1/3 G4:1/3 B3:1/3 D4:1/3 G4:1/3 B3:1/3 D4:1/3 G4:1/3 B3:1/3 D4:1/3 G4:1/3",
    "C4:1/3 E4:1/3 G4:1/3 C4:1/3 E4:1/3 G4:1/3 C4:1/3 E4:1/3 G4:1/3 C4:1/3 E4:1/3 G4:1/3",
  ].join(" | "));
  const bassLine = bass(0, "C3:4 | D3:4 | G3:4 | C3:4");
  return {
    title: "Town Hall Steps (music-box bed, the 8-second sample)", seed: 2026, tail: 1.6,
    harmony: [
      { t: 0, name: "C" }, { t: 4, name: "D" }, { t: 8, name: "G" }, { t: 12, name: "C" },
    ],
    plan: {
      style: "musicBox", tempo: 112, meter: "12/8",
      sections: [
        { id: "question", bars: 2, mood: "curious", key: "C", mode: "lydian", melody: ["hook", "stepwise"], dyn: [0.6, 0.7] },
        { id: "answer", bars: 2, mood: "curious", key: "C", mode: "lydian", melody: ["hook", "stepwise"], dyn: [0.65, 0.72], ending: "tail" },
      ],
    },
    parts: [
      { id: "melody", inst: "musicBox", role: "melody", notes: melody, opts: { grid: true } },
      { id: "arp", inst: "musicBox", role: "accomp", notes: arpeggio, gainDb: -10, opts: { grid: true } },
      { id: "bass", inst: "musicBox", role: "bass", notes: bassLine, gainDb: -8, opts: { grid: true } },
    ],
  };
};
