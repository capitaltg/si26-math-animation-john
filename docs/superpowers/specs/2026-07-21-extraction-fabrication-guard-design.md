# Extraction Fabrication Guard Design

**Status:** Approved on 2026-07-21. Addresses issue #11.

## Problem

`extract_params()` (`backend/app/pipeline/extraction.py`) never raises when the
source problem does not actually match the chosen template's structure. The
Bedrock call forces a tool call (`toolChoice: {"tool": {...}}` in
`bedrock_client.py`), so the model cannot decline — it must return something that
satisfies the schema. When the problem does not fit, the model fabricates
schema-valid-but-wrong params and the scene renders with `status="approved"`.

Two reproduced cases (issue #11):

- **Repro 1 — truncation.** `array_grid` chosen for `(2.4) · (1.3)`. `rows`/`cols`
  are `int`, so the model silently truncates `2.4 -> 2`, `1.3 -> 1` and returns
  `rows=2, cols=2`. A 2x2 grid for a 2.4x1.3 problem.
- **Repro 2 — invented operation.** `number_line` chosen for a fraction-equivalence
  proof (`1/2, 3/6, 4/8, 2/4`) that contains no add/subtract sequence. The model
  invents `start=1, subtract 1` to satisfy the required `steps` list.

The existing safety net in `process_scene.py` only catches `pydantic.ValidationError`
and re-routes to a `text_card` fallback. Both cases above pass Pydantic validation
(schema-valid, just semantically unrelated to the input), so the net never fires.

## Goals

- Give the model an explicit way to decline extraction instead of fabricating.
- Add a deterministic post-extraction check that rejects params whose numbers are
  not grounded in the source text.
- Route both failure modes through the existing honest `text_card` fallback.
- Keep grounding deterministic, local, and free of an extra LLM call. Reuse the
  existing atomic-number tokenizer already used for candidate grounding.

## Non-Goals

- Tightening classifier structural contracts (issue #11 suggestion 3). Not pursued;
  the two defenses below cover the reproduced cases at the extraction layer.
- Fuzzy or semantic matching. Grounding is exact atomic-token / value matching.
- New templates or changes to template guards.

## Design

Two defenses stack at the extraction layer and funnel into one new exception,
`TemplateMismatchError`, which `process_scene` treats like `ValidationError`.

### 1. Escape hatch (model-driven)

`call_with_tool` is generalized to offer more than one tool and let the model pick.

- **`bedrock_client.call_with_tool`** accepts a list of tool specs and uses
  `toolChoice: {"any": {}}` (the model must call exactly one of the offered tools).
  It returns `(tool_name, tool_input)` so the caller knows which tool fired.
  The existing single-tool signature is preserved as the common case: callers pass
  their tool(s); classification passes its one tool and reads the returned input.
- **`extraction.py`** offers two tools:
  - `report_params` — the template's params schema (as today).
  - `decline_extraction` — `{ "reason": str }`.
  The system prompt gains an escape clause instructing the model to call
  `decline_extraction` when the problem has no structure matching the schema
  (for example: no add/subtract sequence for a step-based template, or non-whole
  operands for a whole-number template) rather than forcing a fit.
- If `decline_extraction` fires, `extract_params` raises `TemplateMismatchError`
  with the model's reason.

This is defense-in-depth for genuinely structureless problems (for example a word
problem with no usable operands) that the deterministic check below cannot judge.

### 2. Grounding check (deterministic backstop)

After `report_params` validates against the params schema, `extract_params` runs a
grounding check and raises `TemplateMismatchError` if any extracted number is not
grounded in the source text.

**Source tokenization.** Reuse the existing atomic-number tokenizer from candidate
grounding (`_GROUNDING_TOKEN_RE` / `_tokenize_for_grounding` in `discovery.py`).
It keeps numbers atomic: `"2.4"`, `"3/6"`, `"12"` are each a single token and are
never split into digits or components. This is promoted to a shared location
(a `grounding` helper module) so both discovery and extraction import it; discovery
behavior is unchanged.

**Params representation.** Each params class exposes the number tokens that must be
grounded, via a small hook:

- **Default** (shared helper): recursively walk the params object's numeric leaves
  (`int`/`float`) and stringify each (`str(2)` -> `"2"`, `str(2.4)` -> `"2.4"`).
  Covers `number_line`, `balance_scale`, `array_grid`.
- **`fraction_bar` override**: emit fraction strings (`f"{numerator}/{denominator}"`)
  for the start fraction and each step, because it stores fractions as separate
  integer fields that would otherwise never match an atomic `"3/6"` token.

**Grounding rule.** Let `source` be the set of source number tokens. A params number
token is grounded when:

- it appears in `source`; or
- (derived-total allowance) its numeric value equals the sum of the numeric values
  of the params numbers that are grounded by the first rule.

The derived-total allowance covers `balance_scale.right_total` (for example
`3 + 4 = ?`, where `7` is computed and absent from the source). The template guard
already re-verifies `sum(left_terms) == right_total`, so this allowance cannot admit
an arbitrary total. If any params number remains ungrounded, extraction raises
`TemplateMismatchError`.

**Why this catches both repros.** With atomic tokens:

- Repro 1: `rows=2` -> token `"2"`; source tokens are `"2.4"`, `"1.3"`, ... -> no
  `"2"`, and no grounded base to sum -> mismatch.
- Repro 2: `start=1` -> token `"1"`; source tokens are `"1/2"`, `"3/6"`, ... -> no
  bare `"1"` -> mismatch.

Legitimate `fraction_bar` (for example `3/6 + 1/6`) grounds because its override
emits `"3/6"`, `"1/6"`, which match the atomic source tokens.

### 3. Routing in `process_scene`

`process_scene` catches `TemplateMismatchError` alongside `ValidationError` and routes
to the existing `_fallback_scene(..., TEMPLATE_MISMATCH_REASON, ...)`. A structural
mismatch will not change on retry, so mismatches skip the extraction retry loop
(the retry remains for transient technical failures only).

## Error Handling and Safety

- `decline_extraction` fired -> `TemplateMismatchError` -> honest `text_card` fallback.
- Ungrounded params number -> `TemplateMismatchError` -> `text_card` fallback.
- Transient Bedrock/render errors -> unchanged: retry once, then technical-failure
  fallback.
- Grounding is deterministic and adds no LLM call.

**Known limitation.** The derived-total allowance permits a params number equal to
the sum of grounded params numbers. This is intentional for `balance_scale` totals
and is bounded by that template's guard. Future templates whose derived value is a
non-sum (for example a product total that is not itself a stated operand) would need
their own representation override; current templates do not.

## Testing

Mocked-Bedrock unit tests, matching the existing test style:

- **`bedrock_client`**: offers multiple tools with `toolChoice: {"any": {}}`; returns
  the fired tool's name and input.
- **`extraction`**:
  - `decline_extraction` fired -> raises `TemplateMismatchError`.
  - grounding rejects repro 1 (`array_grid` `rows=2,cols=2` vs `2.4 x 1.3` source).
  - grounding rejects repro 2 (`number_line` `start=1, subtract 1` vs fraction source).
  - grounding accepts a clean `number_line` extraction.
  - grounding accepts `balance_scale` with a derived `right_total` absent from source.
  - grounding accepts a legitimate `fraction_bar` extraction via its override.
- **`process_scene`**: `TemplateMismatchError` from extraction -> `status="fallback"`,
  `fallback_reason == TEMPLATE_MISMATCH_REASON`, and no retry.
- Existing classification tests updated for the new `call_with_tool` return shape.

Focused tests must show red before implementation and green after. The full backend
suite must remain clean. After automated verification, rerun the reproduced cases
against live Bedrock to confirm both now route to the `text_card` fallback.
