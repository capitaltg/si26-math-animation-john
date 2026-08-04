---
version: 1
slug: "frontend-src-app-jsx"
primary_target: "frontend/src/App.jsx"
related_targets: ["frontend/src/SchemaForm.jsx"]
---

## Scope

The whole teacher-facing flow and its shell: upload → candidate selection →
visualization choice → storyboard review → render → download. Visitor mode:
**Operate**. The meta-template review panel (`MetaReviewPanel.jsx`, dev-only,
flags disabled in production) was left out of this pass entirely: it still
carries 27 inline `style={{}}` blocks and no classNames, so it does **not**
inherit the token system. That is a carried defect and the next scoped target,
not a house pattern to copy.

## Audience and job

A K-8 maths teacher at a laptop during a 40-minute prep period or at 9pm, their
own deck open in another window. The job: get a trustworthy animated clip for a
problem their deck already contains, without re-typing it. Tomorrow it projects
to 25 children.

Secondary and near-term: internship reviewers watching this run live. The
surface must read from the back of a room and stay efficient on the tenth use.

## Task and states

Four staged checkpoints, each reversible before the expensive step. States that
must be designed deliberately, not derived:

- **Render in progress** — a per-scene stage checklist (extract → validate →
  thumbnail → render) driven by sequential per-scene requests. Discrete stages
  only. No percentage exists: `full_render.py` is a blocking `subprocess.run`
  with no progress stream, so a determinate bar would be fabricated.
- **Labeled text-card fallback** — a success state, not an error. Carries its
  explicit reason. Must not be styled as failure.
- **Render failed / timed out** — Manim subprocess failure or
  `RENDER_TIMEOUT_SECONDS`. Needs a real recovery path, not a toast.

"No problems found" ships with an honest minimal treatment, not a designed
showcase (user's explicit call).

## Constraints

- Session is ephemeral: no accounts, no history, in-memory server state. Nothing
  may imply saved work.
- Rendering is genuinely slow. The wait is designed, never disguised.
- WCAG 2.1 AA is required, not aspirational.
- UI copy is free to rewrite; `App.test.jsx` and `MetaReviewPanel.test.jsx`
  query by visible text and role, so copy changes carry test updates.
- PRODUCT.md terminology stays exact: candidate, scene, template, storyboard,
  clip, fallback.

## Direction

**Bright Board** — user-pinned, seed key `2a0721d9`. Primaries that encode
rather than decorate: colour is a working K-8 maths code (Cuisenaire rod law),
not a mood. Hard-edged colour fields own whole regions; content inside them
stays surgically crisp. Light warm shell throughout, with a dark inset reserved
for clip preview and thumbnails so rendered video reads brightest — the reason
editors are dark, applied locally instead of globally.

Full playful register is the pinned brief: illustration, marker squiggles, and
blob fields are in. The craft constraint the reference pins themselves hold:
decoration lives in the shell layer; validated numbers, source excerpts, and
extracted values never compete with it.

## Memorable moment

The stage checklist filling in per scene while the teacher keeps working — a
render dock that collapses each scene to a single ticked line as it completes,
so a slow pipeline reads as visible progress on a wall rather than a spinner.

## Unresolved

- Product name is provisional ("Math Animation Generator").
- Whether the render dock persists across stages or docks only on the render
  stage — decide against the built composition.
