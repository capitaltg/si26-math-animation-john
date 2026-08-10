---
name: Bright Board
description: Warm paper ground, Cuisenaire rod colour bound to value, plastic-on-paper depth, and one dark inset reserved for video.
colors:
  paper: "#fffdf8"
  paper-warm: "#fffaf0"
  board: "#f4e8ce"
  board-hover: "#f7edd6"
  board-quiet: "#faf3e4"
  board-deep: "#e9d6ab"
  slate: "#16181d"
  ink: "#1a1c21"
  ink-soft: "#454c57"
  ink-on-slate: "#f6f1e6"
  ink-on-slate-soft: "#c4bdae"
  on-action: "#ffffff"
  line: "#dccfb4"
  line-strong: "#bfae8b"
  rod-1: "#f0e8d4"
  rod-2: "#d8382b"
  rod-3: "#7fb32e"
  rod-4: "#7a4aa5"
  rod-5: "#f2b705"
  rod-6: "#1e7a4b"
  rod-7: "#23262b"
  rod-8: "#8a5a3c"
  rod-9: "#2d6bd4"
  rod-10: "#f07c24"
  masthead-ink: "#4a3a06"
  masthead-rule: "#d9a300"
  action: "#24409b"
  action-deep: "#1a2f74"
  action-field: "#e6ebfa"
  action-field-soft: "#f2f5fd"
  ok: "#145c39"
  ok-field: "#e4f1e9"
  ok-line: "#8fbfa5"
  danger: "#9e241c"
  danger-field: "#fceceb"
  danger-line: "#dd9b95"
  fallback: "#6f462b"
  fallback-field: "#f8eee4"
  fallback-line: "#d3b394"
  teach-ink: "#1c3573"
  teach-field: "#eaf0fc"
  teach-line: "#b3c6ee"
  decor-warm: "#f6c76a"
  decor-cool: "#a8c6f0"
typography:
  display:
    fontFamily: "Baloo 2, system-ui, sans-serif"
    fontSize: "clamp(2.1rem, 5vw, 3.4rem)"
    fontWeight: 800
    lineHeight: 1.05
    letterSpacing: "-0.02em"
  headline:
    fontFamily: "Baloo 2, system-ui, sans-serif"
    fontSize: "clamp(1.45rem, 2.6vw, 1.9rem)"
    fontWeight: 800
    lineHeight: 1.05
    letterSpacing: "-0.02em"
  title:
    fontFamily: "Baloo 2, system-ui, sans-serif"
    fontSize: "1.4rem"
    fontWeight: 800
    lineHeight: 1.15
    letterSpacing: "-0.02em"
  subtitle:
    fontFamily: "Baloo 2, system-ui, sans-serif"
    fontSize: "1.2rem"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  body:
    fontFamily: "Rubik, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "Rubik, system-ui, sans-serif"
    fontSize: "0.85rem"
    fontWeight: 500
    lineHeight: 1.55
  numeral:
    fontFamily: "Baloo 2, system-ui, sans-serif"
    fontSize: "0.93rem"
    fontWeight: 800
    fontFeature: "tabular-nums"
rounded:
  xs: "4px"
  sm: "8px"
  md: "14px"
  lg: "20px"
  pill: "999px"
spacing:
  hair: "0.3rem"
  snug: "0.5rem"
  control: "0.6rem"
  row: "0.9rem"
  block: "1.25rem"
  card: "1.5rem"
  section: "2.25rem"
components:
  masthead:
    backgroundColor: "{colors.rod-5}"
    textColor: "{colors.ink}"
    typography: "{typography.display}"
    padding: "2.5rem 1.5rem 2.25rem"
  band:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    padding: "{spacing.card}"
  scene-approved:
    backgroundColor: "{colors.ok-field}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "{spacing.block}"
  scene-rejected:
    backgroundColor: "{colors.danger-field}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "{spacing.block}"
  button-primary:
    backgroundColor: "{colors.action}"
    textColor: "{colors.on-action}"
    rounded: "{rounded.pill}"
    padding: "0.72rem 1.5rem"
  button-primary-hover:
    backgroundColor: "{colors.action-deep}"
    textColor: "{colors.on-action}"
  button-default:
    backgroundColor: "{colors.board-deep}"
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    padding: "0.6rem 1.1rem"
  button-ok:
    backgroundColor: "{colors.ok}"
    textColor: "{colors.on-action}"
    rounded: "{rounded.pill}"
    padding: "0.6rem 1.1rem"
  button-danger:
    backgroundColor: "transparent"
    textColor: "{colors.danger}"
    rounded: "{rounded.pill}"
    padding: "0.6rem 1.1rem"
  button-danger-hover:
    backgroundColor: "{colors.danger-field}"
    textColor: "{colors.danger}"
  button-quiet:
    backgroundColor: "transparent"
    textColor: "{colors.ink-soft}"
    rounded: "{rounded.pill}"
    padding: "0.6rem 1.1rem"
  button-tiny:
    padding: "0.3rem 0.7rem"
    typography: "{typography.label}"
  drop:
    backgroundColor: "{colors.board}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    padding: "2.25rem 1.5rem"
  drop-hover:
    backgroundColor: "{colors.board-hover}"
    textColor: "{colors.ink}"
  rail-step-active:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.action}"
    rounded: "{rounded.md}"
    padding: "0.6rem 0.75rem 0.7rem"
  rail-step-done:
    backgroundColor: "{colors.ok-field}"
    textColor: "{colors.ok}"
    rounded: "{rounded.md}"
    padding: "0.6rem 0.75rem 0.7rem"
  rail-step-todo:
    backgroundColor: "{colors.board-quiet}"
    textColor: "{colors.ink-soft}"
    rounded: "{rounded.md}"
    padding: "0.6rem 0.75rem 0.7rem"
  pick:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "0.95rem 1.1rem"
  pick-hover:
    backgroundColor: "{colors.paper-warm}"
    textColor: "{colors.ink}"
  pick-selected:
    backgroundColor: "{colors.action-field-soft}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "0.95rem 1.1rem"
  chip:
    backgroundColor: "{colors.board-deep}"
    textColor: "{colors.ink}"
    typography: "{typography.numeral}"
    rounded: "{rounded.sm}"
    padding: "0.18rem 0.6rem 0.22rem"
  slide-tag:
    backgroundColor: "{colors.board-deep}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "0.05rem 0.45rem"
  icon-chip:
    backgroundColor: "{colors.action-field}"
    textColor: "{colors.action}"
    rounded: "{rounded.sm}"
    padding: "0.45rem"
  input-text:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "0.45rem 0.6rem"
    width: "100%"
  rod-bar:
    textColor: "{colors.on-action}"
    typography: "{typography.numeral}"
    rounded: "{rounded.xs}"
    height: "1.5rem"
    padding: "0 0.35rem 0 0"
  rod-bar-pale:
    textColor: "{colors.ink}"
    typography: "{typography.numeral}"
    rounded: "{rounded.xs}"
    height: "1.5rem"
  notice-fallback:
    backgroundColor: "{colors.fallback-field}"
    textColor: "{colors.fallback}"
    rounded: "{rounded.md}"
    padding: "0.8rem 1rem"
  notice-danger:
    backgroundColor: "{colors.danger-field}"
    textColor: "{colors.danger}"
    rounded: "{rounded.md}"
    padding: "0.8rem 1rem"
  notice-teach:
    backgroundColor: "{colors.teach-field}"
    textColor: "{colors.teach-ink}"
    rounded: "{rounded.md}"
    padding: "0.8rem 1rem"
  notice-empty:
    backgroundColor: "{colors.board}"
    textColor: "{colors.ink-soft}"
    rounded: "{rounded.md}"
    padding: "0.8rem 1rem"
  errors-block:
    backgroundColor: "{colors.danger-field}"
    textColor: "{colors.danger}"
    rounded: "{rounded.sm}"
    padding: "0.6rem 0.8rem"
  inset:
    backgroundColor: "{colors.slate}"
    textColor: "{colors.ink-on-slate-soft}"
    rounded: "{rounded.md}"
    padding: "0.6rem"
  dock:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    padding: "0.8rem 1.5rem 1rem"
    width: "100%"
---

# Design System: Bright Board

## Overview

**Creative North Star: "The Bright Board"**

This is the warm butcher-paper wall of a K-8 classroom, not a dashboard. The
ground is off-white stock with real tooth in it; colour arrives as hard-edged
fields that own whole regions rather than as tints sprinkled on cards. The
system's central claim is that colour here is a *working code* — the Cuisenaire
rod set every K-8 maths teacher already owns — so a colour is never chosen to set
a mood or to distinguish a category. It is chosen because a number is 7.

Density is generous and single-column. Depth is plastic sitting on paper: a low
offset riser plus a real blur, the way a moulded block casts a soft shadow on a
sheet, never the flat zero-blur slab of a neobrutalist poster. Type is one
friendly rounded display face carrying every heading, with a clean geometric UI
face for everything a teacher reads or types; there is no third voice.

The world refuses two things by name. It refuses the pastel edtech dashboard —
rounded lavender cards, mint chips, colour as reassurance — because pastel cannot
carry a rod law. And it refuses the dark video-editor opposite: dark exists here
in exactly one place, as a local inset behind a thumbnail or clip so the rendered
video is the brightest thing on screen. Dark is a material for showing video, not
a theme.

The system is fully tokenized: all 62 custom properties are declared on `:root`,
and no rule outside `:root` carries a literal hex colour, a literal
`border-radius`, or an off-ramp `font-size`. Three deliberate exceptions are named
in the sections below. A literal in a rule is a bug in this system, not a
shortcut.

**Key Characteristics:**

- Colour encodes value 1–10, never category or mood
- Warm paper ground with real SVG-noise tooth on every stock surface
- One card level; nested grouping is a tinted block with a hairline rule
- Depth is offset plus real blur; zero-blur block shadows are banned
- Baloo 2 at 800 over Rubik, self-hosted variable woff2, preloaded
- One six-step type ramp; no font-size literals in rules
- Progress is discrete and countable; percentages are forbidden
- Dark is a local inset for video only

## Colors

A warm off-white stock and warm board tans carry almost every surface; saturated
colour is spent on the ten rods, five semantic families, and two decorative
blobs — and on nothing else. Each semantic family that needs an outline owns its
own `-line` token, so a border is never an ad-hoc darkening of its fill.

### Primary

- **Working Blue** (`action`): the single action colour. Solid on the primary
  button, as the 2px border and index colour on the active pipeline step, on the
  form-focus border, on the download link's hover underline, on every field
  `accent-color`, and as the global focus ring. **Working Blue Deep**
  (`action-deep`) is the primary-button hover only.
- **Action Field** (`action-field`) and **Action Field Soft**
  (`action-field-soft`): the two pale tints of that blue — the stronger one
  behind an informational icon, the softer one filling a selected pick row.
- **On Action** (`on-action`): the one white ink used on any saturated fill —
  the primary button, the approve button, and the light numerals on rods. The
  name under-describes that third job; it is still the only white in the system,
  and new saturated fills should use it rather than a fresh `#fff`.

### Secondary

The rod scale is the system's second voice, and it is not a palette — it is a
lookup table from value to hue, canonical Cuisenaire:

- **Rod 1, Cream** (`rod-1`) — deliberately a warm off-white rather than pure
  white, so a 1 still registers against the paper ground
- **Rod 2, Signal Red** (`rod-2`); **Rod 3, Leaf** (`rod-3`); **Rod 4, Grape**
  (`rod-4`); **Rod 5, Chalk Yellow** (`rod-5`); **Rod 6, Bottle Green**
  (`rod-6`); **Rod 7, Near-Black** (`rod-7`); **Rod 8, Cocoa** (`rod-8`);
  **Rod 9, Rod Blue** (`rod-9`); **Rod 10, Orange** (`rod-10`)

Rod 5 does double duty as the masthead field — the one place a rod hue is used
architecturally rather than numerically, and it works because the masthead
carries no number. That field owns two tokens of its own: `masthead-ink` for the
sub-line (6.1:1 on Rod 5) and `masthead-rule` for the darkened 3px bottom edge.

### Tertiary

- **Blob Warm** (`decor-warm`) and **Blob Cool** (`decor-cool`): the two large
  soft shapes in the decorative layer behind content, at 0.9–0.95 opacity, plus
  a marker squiggle drawn in Rod 10. Decoration lives in the shell layer and is
  `aria-hidden`; it never sits over a validated number.

### Neutral

- **Paper** (`paper`) with **Paper Warm** (`paper-warm`): body ground, the band
  card, the dock, inputs, the active rail step — and the barely-warmer hover on a
  pick row
- **Board** (`board`), **Board Hover** (`board-hover`), **Board Quiet**
  (`board-quiet`), **Board Deep** (`board-deep`): the warm-tan family for the
  drop zone and its hover, the resting rail step, default buttons, chips and
  slide tags — the "already-written-on" surfaces
- **Slate** (`slate`) with **Ink on Slate** / **Ink on Slate Soft**: the dark
  inset and its captions, video only
- **Ink** and **Ink Soft** (`ink`, `ink-soft`): primary text and secondary prose
  (8.5:1 on paper — secondary, never faint)
- **Line** and **Line Strong** (`line`, `line-strong`): the 2px hairline on
  cards and the heavier rule on dashed drop zones, dock top edge, and inputs

### Semantic

Five families. Four carry a saturated ink plus a pale field, three of those add a
border line: `ok` / `ok-field` / `ok-line` (approved scenes, done rail steps),
`danger` / `danger-field` / `danger-line` (rejected scenes, alerts, the error
block), `fallback` / `fallback-field` / `fallback-line` (the text-card fallback
and the unsaved-edits flag), and `teach` — `teach-ink` / `teach-field` /
`teach-line` — used by exactly one component, the notice that explains the
meta-template learning loop. Action is the fifth and needs no line token: where it
outlines something, it outlines in full-strength Working Blue.

### Named Rules

**The Rod Law.** Colour binds to a *value*, 1 through 10, and never to a
category. A 7 is near-black wherever it appears. Integers outside 1–10 have no
rod in the physical set, so they get no colour here either — `rodFor()` returns
null and the value renders without a bar. Rod width encodes magnitude on the
same axis (`value × 9%`, so a 10 spans 90%), which means a rod is legible as
quantity even in greyscale.

**The Neutral Category Rule.** Anything that names a *kind* stays board-neutral.
Template chips carry a `data-template` attribute and there is deliberately no CSS
that reads it — the hook exists so the neutrality is visible as a choice rather
than an omission. If a category ever borrowed a rod hue, the rod law would stop
being readable.

**The Pale-Rod Ink Rule.** Rods 1, 3, 5 and 10 take dark numerals; every other
rod takes `on-action` white. This is a fixed set (`ROD_DARK_INK`), not a computed
guess.

**The Role-Separation Rule.** Semantic colour and rod colour are separated by
*role*, not by hue — and the stylesheet's own header now says so. A semantic hue
never becomes a bar, never carries a numeral, and never appears inside the rod
list; a rod hue never reports a state. Each semantic ink is in fact a darker,
lower-chroma sibling of its nearest rod (`ok` sits ~2° from Rod 6, `danger` ~1°
from Rod 2, `fallback` <1° from Rod 8, `action` ~8° from Rod 9), separated by
8–14 points of lightness. Never "fix" this by moving a semantic hue — the
semantics are readable because they are always darker and always in a different
job.

**The Local Dark Rule.** Dark is a material, not a theme. `slate` appears only
as the inset behind a thumbnail, a clip, or a preview-unavailable message, so
rendered video reads as the brightest object on the page. Never a dark shell,
never a dark card, never a dark band.

**The Named Tint Rule.** Every fill, hover, border tint and ink belongs to a
named family before it is used. The pale blues are the worked example: the build
once spelled them three ways as literals, and they resolved not into one ramp but
into an action *pair* (`action-field` behind an icon, `action-field-soft` under a
selected row) plus a reassignment of the third to a different family entirely
(`teach-field`). Naming a tint is what reveals which family it belongs to.

One deliberate literal remains in a rule: the rod bar's 2px edge is
`rgba(26, 28, 33, 0.28)` — Ink at 28% alpha, so the edge darkens whatever rod hue
sits under it instead of fighting ten different fills. An alpha of an existing
token is the only acceptable inline colour.

## Typography

**Display Font:** Baloo 2 (with system-ui, sans-serif) — self-hosted variable
woff2, weight axis 400–800, `font-display: swap`, preloaded in `<head>`
**Body Font:** Rubik (with system-ui, sans-serif) — self-hosted variable woff2,
weight axis 300–900, same loading treatment

**Character:** Baloo 2 at 800 with −0.02em tracking is round, heavy and
school-poster friendly — it does the shouting. Rubik underneath is geometric and
undramatic, so extracted values, source excerpts and error text read as records
rather than as marketing. The pairing is warm without being childish because only
one of the two faces is expressive.

### Hierarchy

One ramp of six steps carries everything except the two fluid display sizes:
`--t-xs .85` / `--t-sm .93` / `--t-base 1` / `--t-lg 1.06` / `--t-xl 1.2` /
`--t-2xl 1.4` (rem).

- **Display** (Baloo 2 800, `clamp(2.1rem, 5vw, 3.4rem)`, 1.05, −0.02em, capped
  at 22ch): the masthead H1 only, once per page
- **Headline** (Baloo 2 800, `clamp(1.45rem, 2.6vw, 1.9rem)`, 1.05): the H2 that
  opens each band — the stage's name
- **Title** (Baloo 2 800, `--t-2xl`, 1.15): a scene's detected summary and the
  drop-zone title
- **Subtitle** (Baloo 2, `--t-xl`): a candidate's one-line summary (700) and a
  fieldset legend (800)
- **Body** (Rubik 400, `--t-base`, 1.55): all prose. Secondary prose drops to
  `--t-sm` in Ink Soft. `--t-lg` is the step just above body, used where a UI
  string must carry a little more weight: the masthead sub-line, a rail step's
  name, a fact term, a sub-form legend, the dock title, a clip title, the primary
  button
- **Label** (Rubik 500, `--t-xs`, sentence case): field labels, the elapsed
  clock, clip ids, rod roles. Never uppercase, never letter-spaced
- **Numeral** (Baloo 2 800, `--t-sm`, tabular): the number inside a rod bar; the
  same tabular treatment carries to file names, slide tags, ids, grades and the
  clock

### Named Rules

**The One Ramp Rule.** There is one type ramp of six steps and no `font-size`
literal in any rule. The two exceptions are structural, not stylistic: the root
`body` size (16px) that the rem ramp is measured against, and the two fluid
display `clamp()` values, which exist because a masthead and a band heading must
scale with the viewport and a fixed step cannot. Everything else — including the
sizes that used to be 1.12rem and 1.35rem one-offs — sits on a step. A new UI
size is a bug, not a decision.

**The Tabular Numeral Rule.** Any number a teacher might compare against their
own deck gets `font-variant-numeric: tabular-nums`. Numbers must not reflow
horizontally as they change.

**The One Expressive Voice Rule.** Baloo 2 sets headings, legends, rod numerals,
chips and stage names. It never sets body prose, error text, or a source
excerpt — the moment it does, the extracted values start looking illustrated.

## Layout

One centred column, `max-width: 1080px`, with a 1.5rem gutter that holds at
every width; the masthead field and the dock use the same 1080px inner measure
so all three edges align. Vertical rhythm is card-based: a `1.5rem` band, then
`1.5rem` of air, then the next band. The page bottom carries `5rem` of slack,
raised to `12rem` while the render dock is fixed to the bottom so the dock can
never cover the last clip.

Spacing is expressed as rem literals rather than tokens — the one token class the
build has not absorbed — but it is not arbitrary: the reused steps are `0.3`
(hairline pairs), `0.5`/`0.6` (control and icon gaps — by far the most common),
`0.9` (list rows), `1.25` (block rhythm), `1.5` (card padding and page gutter)
and `2.25` (rail to first band). Stay on those steps.

Three real breakpoints, each fixing one specific two-column grid rather than a
global reflow: **760px** collapses a scene's preview/form split (340px + fluid);
**900px** collapses the upload grid (1.15fr + 1fr) to one column; **1100px**
moves the decorative squiggle from the right gutter down to the bottom corner,
because below that width the content column claims the gutter. The stage rail and
the clip grid need no breakpoint — the rail wraps on `flex: 1 1 8rem`, and clips
use `repeat(auto-fill, minmax(min(100%, 22rem), 1fr))`.

### Named Rules

**The Measure Rule.** Every prose block is capped in `ch`, tightening as the text
gets less important: 22ch for the display headline, 42–46ch for hint and
definition text, 62–74ch for notes, excerpts and rationales. No paragraph runs
the full 1080px. Where a label cannot wrap at all — a dock row's
`template · ids` — it is capped in rem and truncated with an ellipsis instead, so
a long template name never reflows the bar.

**The Gutter Decoration Rule.** Decorative shapes live outside the content
column or behind it at `z-index: 0`; content and the masthead sit at
`z-index: 1`. When the column claims the gutter, the decoration moves out of the
way rather than sliding under the text.

## Elevation & Depth

Hybrid, and specific: tonal layering does the structural work (warm tan versus
paper white tells you what kind of surface you are on), and shadow is reserved
for things that are physically *on* the paper — cards, clips, the active rail
step, a hovered button, the dock. Every shadow in the system pairs a low
hard-edged riser with a genuine blur, which is what separates this world from
the neobrutalist look it would otherwise resemble at a glance.

### Shadow Vocabulary

- **Block** (`box-shadow: 0 2px 0 rgba(26,28,33,0.09), 0 10px 20px -8px rgba(26,28,33,0.3)`):
  the default lift. Bands, clip cards, the active rail step, and any hovered
  button.
- **Raised** (`box-shadow: 0 3px 0 rgba(26,28,33,0.12), 0 18px 34px -14px rgba(26,28,33,0.38)`):
  the fixed render dock only — the one element that floats above the page.
- **Inset** (`box-shadow: inset 0 2px 10px rgba(0,0,0,0.55)`): the dark video
  inset, so the slate reads as a recessed well rather than a dark card.

### Named Rules

**The Real-Blur Rule.** A shadow is an offset riser *plus* a real blur. A
zero-blur block shadow is banned outright: it is the tell of a different world
and this one is paper, not poster board.

**The One Card Level Rule.** `.band` is the card, and it is the only card. A
group inside a band is a tinted block — no border, no radius, no shadow — set
off by a 1px top rule and vertical space (the scene block), or by a legend and a
0.9rem indent (the schema sub-form). A third nesting level does not exist. The
one exception is state: an approved or rejected scene takes the mid radius and
its semantic field colour, because that is a status, not a container.

**The Hover-Lift Rule.** Buttons translate −1px and gain the Block shadow on
hover, then return to 0 on `:active` — press is the absence of lift. Nothing
scales on hover.

## Shapes

A soft-toy radius family in four steps plus a pill, with no outlier: `4px` on the
smallest details (the global focus ring and the rod bar), `8px` on small chrome
(chips, slide tags, inputs, icon chips, the error block, media inside the inset),
`14px` on mid-level surfaces (rail steps, notices, picks, the inset,
status-tinted scenes), `20px` on the largest surfaces (bands, clip cards, the
drop zone), and a full pill (`999px`) on every button and only buttons. The rod
bar sits at the smallest step on purpose: a Cuisenaire rod is a moulded block
with a barely-eased edge, and anything rounder breaks the material.

Borders are structural and always even: 2px is the house weight (card hairlines,
buttons, inputs, rail steps, notices, picks, the rod bar's edge), 3px marks a
boundary you are meant to feel (the dashed drop zone, the masthead's bottom rule
in `masthead-rule`, the dock's top rule, the focus ring), and 1px is reserved for
the one hairline that separates scenes inside a band. Icons are authored at a
single 2px stroke with square caps and mitred joins, echoing the rod-block
geometry.

### Named Rules

**The Tooth Rule.** `--tooth` — an inline feTurbulence SVG at 0.28 opacity — is
the paper material, and it is applied to exactly four surfaces: the shell
overlay (0.5 opacity, `mix-blend-mode: multiply`), the band, the drop zone, and
the rail step. On any toothed surface, state changes **must** use
`background-color`, never the `background` shorthand — the shorthand resets
`background-image` and silently strips the texture.

**The No Side-Tab Rule.** No element carries a coloured left or right accent
border. The build contains no `border-left`/`border-right` declaration at all,
which is the enforcement: state is carried by fill, by a full 2px border, or by
text — never by a stripe down one edge.

## Components

### Buttons

- **Shape:** full pill, 2px border always present — transparent when the button
  is filled, coloured when it is not, so no button changes size between variants
- **Primary:** solid Working Blue with `on-action` text at weight 700, larger
  than the rest (`--t-lg`, `0.72rem 1.5rem`). One per view, ending the stage
- **Default:** Board Deep on paper at weight 500 (`0.6rem 1.1rem`) — Save,
  Retry, Ungroup, Upload-again: the reversible actions
- **Approve:** solid `ok` with `on-action` text at 700. **Reject:** transparent
  with a `danger` border and `danger` text, filling to `danger-field` on hover —
  the destructive action is outlined, never solid
- **Quiet:** transparent with a Line Strong border and Ink Soft text — Dismiss,
  Hide, Back, and the file-picker label
- **Hover / Active:** −1px translate plus the Block shadow; primary also
  darkens to `action-deep`. Active returns to 0
- **Disabled:** `opacity: 0.55` with `cursor: not-allowed` (see Do's and Don'ts)
- **Tiny:** `0.3rem 0.7rem` at `--t-xs`, for Add another / Remove inside a
  sub-form

### Chips

- **Style:** Board Deep fill, Ink text, Baloo 2 700 at `--t-sm`, small radius.
  Deliberately neutral — a chip names a template, and template is a category
- **State:** chips are labels, not controls; there is no selected variant. The
  selected state lives on the enclosing pick row

### Cards / Containers

- **Corner Style:** the largest radius (`20px`)
- **Background:** Paper with the tooth texture over it
- **Shadow Strategy:** Block, always — a band is never flat
- **Border:** 2px Line
- **Internal Padding:** `1.5rem`, with `1.5rem` between bands. Each band opens
  with a baseline-aligned head: H2 on the left, a `--t-sm` Ink Soft note on the
  right, wrapping to a second line under 1080px

### Inputs / Fields

- **Style:** Paper fill, 2px Line Strong border, small radius,
  `0.45rem 0.6rem` padding, capped at `20rem` so a numeric field never stretches
  across the column. Tabular numerals throughout. Label above in Ink Soft
  `--t-xs`
- **Focus:** the border shifts to Working Blue *in addition to* the global 3px
  focus ring — the border shift is never a substitute for the ring
- **Error:** errors are not painted on the field. A `danger-field` block with a
  2px `danger-line` border collects them under the form, led by a plain-language
  line, and each entry names its path in teacher language ("Steps 1 → Amount")
  rather than a Pydantic accessor
- **Checkboxes / radios:** native, sized to 1.15–1.3rem with
  `accent-color: var(--action)`. The file input is the only hidden control, and
  its label is the visible target

### Navigation

There is no nav — the pipeline is the navigation, and it is a status display
rather than a set of links. See Stage Rail.

### Stage Rail (signature)

An ordered list of five equal blocks (`flex: 1 1 8rem`, wrapping) because the
order *is* the information. Each block stacks a Baloo 2 index over a Baloo 2
name. Three states: **todo** (`board-quiet` fill, Line border), **active** (Paper
fill, Working Blue 2px border, Block shadow, and a 0.55s `seat` animation that
drops it 10px into place), **done** (`ok-field` fill, an `ok-line` border, and a
check glyph replacing the number). The active step carries `aria-current="step"`,
and every step carries an sr-only "Step N — done / current step / not started".

### Rod Strip (signature)

The system's thesis made visible. For a scene, up to five numeric params are
collected with a readable role each and drawn as horizontal bars: fill from the
rod law, width `value × 9%`, `min-width: 1.6rem` so a 1 is still a real target,
the smallest radius, a 2px edge of Ink at 28% alpha, and the numeral
right-aligned inside the bar in Baloo 2 800. Pale rods flip to dark ink. A
`--t-xs` caption reads "Validated values, on the rod scale" — the strip reports
checked arithmetic, so it must never be populated with decorative numbers.

### Stamp Column (signature)

Four discrete stages per scene — values extracted, validated in Python, preview
rendered, approved for render — each a row with a 1.15rem authored mark and a
label, coloured by state (Ink Soft todo, Working Blue active, `ok` done, `danger`
failed) at weight 500. Above them, a tabular "N of 4 stages complete". Every
stamp appends an sr-only state word because the marks are `aria-hidden`.

### Render Dock (signature)

A fixed bottom bar (never a modal, never an overlay) on Paper with a 3px Line
Strong top rule and the Raised shadow, at the same 1080px inner measure as the
page; the page adds `12rem` of bottom padding while it is up so it cannot cover
a clip. The head runs icon, a live heading ("Rendering" / "Render finished"), a
tabular elapsed clock, and a Hide button once finished. Below it, one wrapped row
per approved scene labelled `template · ids`, each name capped at `16rem` and
ellipsis-truncated so a long template name cannot reflow the bar. Row state is
carried by the mark's shape plus an sr-only word — deliberately not by colour.
The heading carries `aria-live="polite"`; the clock is `aria-hidden` because it
mutates every second and would talk over everything else.

### Dark Inset (signature)

Slate fill, mid radius, `0.6rem` padding, inner shadow; media inside goes
full-width at the small radius. Its empty state holds a 16:9 box with centred
Ink-on-Slate-Soft `--t-sm` text. This is the only dark surface in the system.

### Notices

One shape — flex row, icon then body, mid radius, 2px border, `0.8rem 1rem`,
`--t-sm` — in four fills, each drawing ink, field and border from one semantic
family: **fallback** (a success), **danger** (with `role="alert"`), **teach**
(the meta-template learning explanation, and the only user of the `teach`
family), **empty** (Board fill, Ink Soft, for "no problems found" — honest and
undesigned by decision). A notice may carry its own `.actions` row for recovery.

## Do's and Don'ts

### Do:

- **Do** bind colour to value through the rod law (`--rod-1`..`--rod-10`) and
  let width carry magnitude (`value × 9%`), so a rod survives greyscale.
- **Do** keep every category label — template chips above all — on Board Deep
  neutral.
- **Do** flip rod numerals to dark ink on rods 1, 3, 5 and 10; every other rod
  takes `--on-action`.
- **Do** name a tint before you use it. Every colour in a rule is a `var()`, and
  a new fill, hover or border tint joins a family (`-field`, `-field-soft`,
  `-line`) rather than appearing as a literal.
- **Do** take every size from the six-step ramp and every corner from the
  four-step radius family.
- **Do** use `background-color` on any surface that carries `--tooth`; the
  `background` shorthand wipes the texture.
- **Do** pair every offset riser with a real blur (`--shadow-block`,
  `--shadow-raised`).
- **Do** report progress as discrete, countable, all-reachable stages, and name
  the honest expectation in words ("This takes minutes, not seconds").
- **Do** append an sr-only state word next to every decorative icon, mark
  decorative SVG `aria-hidden` with `focusable="false"`, and put
  `aria-current="step"` on the active rail step.
- **Do** treat the labeled text-card fallback as a success: `notice--fallback`,
  warm brown, its reason stated.
- **Do** keep the global 3px `--action` focus ring and add to it — a focus
  border shift is an addition, never a swap.
- **Do** author icons at one 2px stroke with square caps and `currentColor`.
- **Do** give a failure a real recovery path in place (a `danger` notice with
  its own actions), and say what was preserved.

### Don't:

- **Don't** show a percentage, a determinate bar, or an ETA for rendering.
  `POST /render` is one blocking batch call with no progress stream, so any
  number would be fabricated. Discrete stamps and an elapsed clock only.
- **Don't** let a rod hue report a state, or a semantic hue become a bar or
  carry a numeral. Role separation is the whole mechanism.
- **Don't** paint a rod for a value outside integer 1–10 — that rod does not
  exist in the physical set.
- **Don't** write a literal hex, `border-radius` or `font-size` in a rule. The
  only sanctioned exceptions are the two fluid display `clamp()` sizes, the root
  16px body size, and an `rgba()` alpha of an existing token (the rod bar's
  edge).
- **Don't** use a zero-blur block shadow.
- **Don't** take the shell dark, or apply `--slate` to anything but a video or
  thumbnail well.
- **Don't** add a coloured left or right accent border. There is no side-tab in
  this system at any width.
- **Don't** add a third container level. Nest by tinted block, hairline rule,
  legend and indent.
- **Don't** convey an inactive or lesser state by lowering the opacity of text —
  it was tried on the todo rail step and dropped the index to 2.8:1 against the
  board. Use a paler *fill* (`--board-quiet`) instead.
- **Don't** style the fallback as an error, and don't use `danger` for anything
  that is not a genuine failure.
- **Don't** let decoration overlap a validated number, an extracted value, or a
  source excerpt; the playful layer stays at `z-index: 0` and
  `pointer-events: none`.
- **Don't** show the platform's own file-input widget; the styled label is the
  control.
- **Don't** uppercase or letter-space UI labels.
- **Don't** announce a ticking value in a live region.

## Runtime

- **Single process only.** Session state (`backend/app/session.py`) is a
  per-process `OrderedDict`; clip and thumbnail registries live in the same
  process memory. Running `uvicorn --workers N` (N > 1) or multiple backend
  instances splits sessions per worker, so any request routed to a peer that
  did not receive the upload returns 400. Keep one worker per instance until
  session state is moved to a durable, versioned store.
