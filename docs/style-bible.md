# Headline Comic — style bible

Updated: 2026-10-12. Authoritative for all Track B visual work (T022 cast sheets,
T023 keyframes, T024 comic page, T027 video).

## 1. Look and feel

A small, friendly, **original miniature town** seen in flat, rounded vector art
(the AniDoodle renderer draws with canvas primitives, so the result is clean
flat geometry, not a photographed clay set). The intended *feel* is clay:

- **Chunky, rounded forms.** Bodies, heads, roofs and props are soft ellipses and
  rounded rectangles. No sharp 90° corners, no hard outlines everywhere.
- **A single warm, muted palette** (section 2) with soft sky-to-horizon gradients
  and one flat shadow under every standing form.
- **No text anywhere in the art.** Captions, bubbles and source markers are
  composited later by code on copies (FR-009).
- **Original and clearly miniature.** This is the town from the story — never a
  real place, never a licensed property. No LEGO studs, no brick-pattern texture,
  no minifig proportions (D1: not LEGO).
- **Deterministic.** Every scene is a pure function of the frame index; the same
  source draws the same pixels every render (AniDoodle's reproducibility gate).

The flat-vector caveat is recorded in `docs/provider-notes.md` (T004): AniDoodle
is code-drawn and cannot produce real clay shading. We keep the clay *palette and
chunky silhouette* and accept flat fill as the renderer's honest output.

## 2. Palette

All colours below are the canonical hex values. Scene code must use these
constants, not ad-hoc lookalikes, so the cast stays consistent across sheets,
keyframes and the final video.

| Role | Hex | Use |
|---|---|---|
| `sky-top` | `#8ec9dc` | sky gradient start |
| `sky-bottom` | `#f6e7bd` | sky gradient end (warm horizon) |
| `ground` | `#668a69` | grass / ground plane |
| `clay-light` | `#d1a56f` | building body A (light clay) |
| `clay-dark` | `#c98b72` | building body B (red clay) |
| `window` | `#f4d88f` | lit windows / door |
| `roof` | `#8a5a4a` | roof / shadow trim |
| `canopy` | `#2e6f95` | market canopy blue |
| `path` | `#d9c49a` | harbour path / walkway |
| `lamp` | `#f4c95d` | lamp glow, beak, accents |
| `ink` | `#17212b` | eyes, dark details |

### Pip the pigeon

| Part | Hex |
|---|---|
| body | `#33475b` |
| belly | `#d8e5e8` |
| head | `#33475b` |
| beak / legs | `#f4c95d` |
| wing | `#526b7e` |
| eye white | `#fffaf0` |
| eye pupil | `#17212b` |

### The courier

| Part | Hex |
|---|---|
| cap | `#2e6f95` |
| cap band | `#f4c95d` |
| coat / tunic | `#3f6f8f` |
| skin | `#e6b48a` |
| satchel / bag | `#8a5a2b` |
| trousers | `#5a6472` |
| shoes | `#2f3640` |
| letter in hand | `#fff8e8` / flap `#d07858` |

### The mayor

| Part | Hex |
|---|---|
| hair | `#6b4a2b` |
| skin | `#e6b48a` |
| shirt | `#f2e3c6` |
| sash | `#c0392b` |
| medal / chain | `#f4c95d` |
| jacket | `#3f6f8f` |
| trousers | `#5a6472` |
| shoes | `#2f3640` |

## 3. Cast (FR-008, D8)

Three recurring characters. Each has **one sheet image showing four views**
(front, three-quarter, side, back) and is drawn from a single shared recipe so
every appearance matches. At most two characters appear per shot (FR-016).

### 3.1 Pip, the courier pigeon

A plump grey-blue pigeon who carries the town's letters. Round body, pale belly,
bright yellow beak and legs, one strong swept wing. The single fastest-recognised
character: yellow beak + grey body + pale belly is enough on its own. Pip already
appears in the Gate 0 proof (`scripts/anidoodle/render_gate0.mjs`); the cast sheet
canonicalises the same recipe in four views.

### 3.2 The courier

The town's friendly delivery person. Blue cap with a yellow band, blue tunic,
brown satchel over one shoulder, a cream letter in hand. Chunky silhouette with
no face detail beyond two dot eyes — readability survives small comic panels.
Identified by: blue cap + yellow band + brown satchel.

### 3.3 The mayor

A kind, round town mayor. Short brown hair, cream shirt, a red sash across the
chest with a small yellow medal. No crown, no staff — the sash alone is the mark
of office. Identified by: red sash + cream shirt + yellow medal.

## 4. Town set

One original miniature town, reused in every run. The canonical backdrop (drawn
top-to-bottom, then props over it):

1. **Sky** — vertical `sky-top` → `sky-bottom` gradient.
2. **Ground** — a flat `ground` band in the lower fifth.
3. **Buildings** — six chunky `clay-light` / `clay-dark` blocks with `window`
   squares, spaced along the horizon (exactly the rhythm from the Gate 0 proof).
4. **Path** — a curved `path` walkway through the middle ground.

Story props (drawn only when a shot's action needs them; each is its own small
drawing function so it can be reused):

- **Harbour lamps** — a dark post with a `lamp`-glow head (beat 1).
- **Market canopy** — a `canopy`-blue awning on two posts (beat 3).
- **Garden gate / fence** — a low fence with a gate (beat 4).
- **Clock workshop** — a building with a round clock face (beat 5).
- **Letter / seed packet** — the courier's recurring prop.

## 5. Scene-authoring templates

Because AniDoodle scenes are code (not text-to-image prompts), the "prompt
template" is a **drawing template**. Every character and every shot follows the
same shape, so the cast stays fixed and scenes stay deterministic.

### 5.1 Character recipe (the shared library)

Every character ships as functions in one shared module (`scripts/anidoodle/cast/cast.ts`)
with this signature convention:

```ts
// one view, centred on (0,0) at scale 1; the caller translates/scales.
export function drawCourierFront(ctx: Ctx, s: number): void
export function drawCourierThreeQuarter(ctx: Ctx, s: number): void
export function drawCourierSide(ctx: Ctx, s: number): void
export function drawCourierBack(ctx: Ctx, s: number): void
```

Rules the library enforces:

- One recipe per character, all four views built from the same palette constants
  and the same body proportions (head/body/limb ratios).
- A view draws the character only; backgrounds, shadows and props are the caller's.
- No wall-clock time, no `Math.random`, no network — a pure function of inputs.

### 5.2 Keyframe template (T023)

A clean 16:9 keyframe is composed in this fixed order:

1. sky → 2. ground → 3. town buildings → 4. path → 5. props → 6. characters.

The storyboard's free-text `camera` and `action` are **mapped deterministically
by code** to a small bounded set of presets (the full mapping is T023's
`image_gen`; the vocabulary is fixed here so art and code agree):

| Camera keywords | Preset | Layout |
|---|---|---|
| `wide`, `establishing`, `closing` | `wide` | full town, characters small and centred |
| `pan`, `tracking`, `side-follow`, `push-in` | `medium` | mid shot, one or two characters, some town |
| `close`, `detail`, `seed`, `map` | `close` | prop or single character fills the frame |
| `overhead` | `overhead` | town seen from above, characters as tops |

| Action keywords | Pose |
|---|---|
| `point`, `points`, `invitation` | arm raised, finger extended |
| `walk`, `follow`, `leads`, `stroll` | legs apart, slight lean forward |
| `flutter`, `hop`, `flutters` | wings out, body lifted |
| `wave`, `waves`, `welcome`, `greet` | arm up, open palm |
| `trace`, `tie`, `mark`, `map` | hands down working with a prop |
| `gather`, `gathers`, `finish` | two characters side by side |

Anything not in the vocabulary falls back to `medium` / a neutral standing pose,
and the choice is logged so the presenter can spot unbounded inputs.

### 5.3 Text rules

Keyframes and cast sheets contain **no text**. The comic page adds, by code, on
copies only: panel captions, speech bubbles, `source 1-5` markers, and the
"AI-generated fiction" label (FR-009, FR-013).

## 6. Asset layout (FR-008)

```
assets/cast/
  courier.png      # four views, one image
  mayor.png        # four views, one image
  pigeon.png       # four views, one image
  town.png         # town reference
```

Generated once, chosen by hand, committed. They are never regenerated inside a
run; a run only *reads* them as references.

## 7. Consistency rules (D8, D10, SC-2)

- One storyboard is the single source of truth: **one keyframe per shot**, and the
  six `comic_panel` keyframes are the six comic panels (D10).
- A shot shows at most two of the three characters (FR-016); a generation call
  carries at most three references — two cast sheets and the town (FR-009).
- Keep silhouettes distinct by colour so SC-2 labelling stays above 90% on panels
  and 80% on frames: yellow beak (pigeon), blue cap + yellow band (courier), red
  sash (mayor).
