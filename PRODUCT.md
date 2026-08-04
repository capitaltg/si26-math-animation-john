# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary: K–8 math teachers preparing slide-based lessons. They arrive with a
PPTX they already wrote, want a short animated visual aid for specific example
problems in it, and are working under prep-time pressure — this is a side task
between other obligations, not a tool they will study.

Secondary, near-term and material: internship mentors and reviewers evaluating
the product live in a demo or pitch setting. The demo is the immediate gate;
the teacher path is the destination. Design must serve both — legible when
presented, efficient on the tenth repeat use.

## Product Purpose

Turn example problems already written in a teacher's slide deck into short,
downloadable MP4 animation clips the teacher inserts into their own slideshow
manually.

The teacher uploads a PPTX, the system discovers candidate problems in it, the
teacher selects which to visualize and picks a visualization per problem,
reviews the extracted values in a storyboard step, and renders. Success is a
teacher getting a clip they trust for the problem they actually teach, without
re-typing the problem into a tool.

## Positioning

Animations are never AI-generated at request time. The animation library is
hand-authored in advance as parameterized Manim templates; the LLM only locates
problems, classifies them into a compatible template, infers a grade, and
extracts template parameters. **All arithmetic, running totals, and equalities
are recomputed and validated in Python — the model never computes them.**

That split is the claim a neighboring product cannot truthfully copy: generic
AI video tools produce mathematically unreliable output because nothing
constrains them to represent an operation correctly; static clip-art libraries
never match the teacher's actual problem. This sits between the two —
guaranteed-correct representation, teacher-specific content.

Correctness is the product. When extraction or rendering cannot honestly
satisfy the chosen template, the system falls back to a labeled text card and
shows the reason. A visible honest failure outranks a plausible wrong answer.

## Operating Context

- The teacher's source material is a PPTX they authored; the tool never writes
  back into it. Output is a standalone MP4 per approved scene, inserted by hand
  via PowerPoint's Insert > Video.
- Rendering is synchronous and genuinely slow (real Manim + ffmpeg
  subprocesses). Waiting is part of the flow, not an edge case.
- The flow is a staged pipeline with teacher checkpoints: upload → candidate
  selection → visualization choice → storyboard review (edit values, override
  grade, approve/reject/retry per scene) → full render → download.
- Sessions are ephemeral: in-memory state, httponly session cookie, no
  accounts, no saved history. State does not survive a tab close or a server
  restart.
- Rendered clips are eventually watched by children in a classroom, often
  projected.

## Capabilities and Constraints

- Math only, grades K–8. 2D only.
- Input: PPTX only, text-based content, ≤50 slides, ≤50 MB. No OCR; problems
  present only as images or diagrams are not detected. DOCX and PDF are a
  deliberate fast-follow, not built.
- Visualization templates: number line, array grid, fraction bar, balance
  scale, text card (the honest fallback), plus meta-templates learned from a
  concrete fallback problem (e.g. `boundary_trace`, `pair_elimination`).
- Multi-step problems: one starting value plus 2–3 ordered operations from a
  single family (additive or multiplicative). No mixed-family chains, no
  PEMDAS / expression-tree problems — those get a labeled fallback.
- Explicit "no problems found" state when discovery finds nothing usable.
- Meta-template generation produces a semantic teaching plan (objective, one
  primary semantic visual, closed explanation strategy, 3–5 ordered beats
  ending in a conclusion), which a deterministic compiler lowers into a
  parameterized scene program. Quality gates run privately before a draft
  becomes reviewable.
- The v3 teaching-plan schema is authoritative; v1/v2 drafts and published
  versions are intentionally unsupported.
- Meta-template flags stay disabled in production until operational rollout
  work is complete.
- Requires AWS Bedrock credentials for discovery, classification, and
  extraction. Requires ffmpeg, Cairo/Pango, and LaTeX on PATH to render.
- No stitching of clips, no auto-embed, no narrated audio (captions only — the
  presenting teacher narrates live), no persistent accounts, no async
  completion notifications.

### Terminology (use these words in UI copy)

candidate (a discovered potential problem) · scene (one problem committed to a
template) · template (a hand-authored parameterized animation) · storyboard
(the review step before full render) · clip (the rendered MP4) · fallback (the
labeled text card, with its reason).

## Brand Commitments

None. No org branding, logo, palette, or naming lock. "Math Animation
Generator" is provisional and may be changed. Visual identity is fully open.

## Evidence on Hand

Real, in-repo, quotable:

- `eval/` and `eval set/` — the evaluation corpus, including the bundled demo
  deck.
- `docs/eval-results-week1.md`, `docs/latency-benchmark-week1.md`,
  `docs/eval-set-timing-2026-07-20.md` — measured accuracy and latency.
- `docs/meta-template-demo.md` — the canonical demo runbook (setup, live
  sequence, checkpoints, reset, troubleshooting).
- `media/` — rendered clip output.
- `project description.md` — the authoritative scope document.

Do not fabricate: there are no real teacher testimonials, no named school or
district customers, no usage numbers, no pricing, no deployment or uptime
claims. The product has not been used by a teacher in a real classroom.

## Product Principles

1. **Correctness is visible, not assumed.** Every number shown traces to a
   Python-validated value. When the system cannot be right, it says why.
2. **The teacher's material is the input.** Never make them re-type a problem
   the deck already contains. Manual entry exists only as an escape hatch.
3. **Checkpoints earn trust.** Selection, visualization choice, and storyboard
   review exist so the teacher confirms before an expensive irreversible step —
   never remove a checkpoint to look faster.
4. **Honest fallback beats a confident guess.** A labeled text card with a
   stated reason is a success state, not an error state, and should not be
   styled as failure.
5. **Waiting is designed, not apologized for.** Renders take real time;
   progress must be legible and the wait must not feel like a hang.
6. **Demo-legible and repeat-usable.** The same screen has to read from the
   back of a room and stay efficient on the tenth use.

## Accessibility & Inclusion

**WCAG 2.1 AA is a durable requirement** for all surfaces: full keyboard paths
through every pipeline stage, AA contrast, programmatically labeled controls,
and visible focus.

Current state is a known gap, not a met bar: the React app carries two
`aria-*` attributes total across ~1,400 lines of JSX and has no stylesheet —
all styling is inline. Future work closes this rather than preserving it.
