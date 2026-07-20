# Ordered-Token Candidate Grounding Design

**Status:** Approved on 2026-07-20.

## Problem

Candidate discovery currently accepts a Bedrock excerpt only when the entire
whitespace-normalized, case-folded excerpt is a contiguous substring of the
reported slide text. This correctly rejects fabricated excerpts and invalid
slide indexes, but it also rejects faithful excerpts when Bedrock omits
intervening headers or reformats a table.

The Grade 7 proportional-relationships evaluation deck reproduced the defect.
Bedrock returned four candidates grounded in slides 2–5, but all four were
dropped because the excerpts combined relevant slide-body and speaker-note
content or rendered table rows with presentation-only separators.

## Goals

- Accept source excerpts that omit intervening slide text while preserving the
  order of the quoted content.
- Tolerate whitespace, capitalization, and presentation-only table formatting.
- Continue rejecting wrong-slide excerpts, invented words, changed numbers or
  operators, reordered content, and empty excerpts.
- Keep grounding deterministic, local, and independent of another LLM call.

## Non-Goals

- Fuzzy or semantic similarity matching.
- Template classification or new fraction, ratio, or decimal templates.
- Changes to the candidate model, Bedrock client, or public discovery API.
- OCR for text embedded in images.

## Design

### Tokenization

Replace whole-string substring comparison with a shared tokenizer for the
Bedrock excerpt and the exact reported slide text. The tokenizer will:

1. Apply Unicode-aware case folding.
2. Remove literal table placeholders such as `[blank]`; this exception is
   limited to the bracketed placeholder rather than every occurrence of the
   word `blank`.
3. Preserve words, integers, decimals, fractions, and arithmetic operators as
   ordered tokens.
4. Treat whitespace and presentation punctuation such as table pipes, colons,
   and line breaks as separators.

Fractions and decimals remain atomic tokens, so `1/4` cannot ground `1/8` and
`3.25` cannot ground `3.15`. Arithmetic operators are retained so an addition
excerpt cannot ground subtraction text containing the same operands.

### Grounding rule

The existing chunk-range check remains the first gate. After resolving the
reported slide, the candidate is accepted only when:

- the excerpt produces at least one meaningful token; and
- every excerpt token appears in the slide-token stream in the same order.

The tokens need not be adjacent. This permits Bedrock to omit headers,
instructions, source annotations, and other intervening slide material. It
does not permit Bedrock to add or reorder semantic content.

The ordered-subsequence check is linear in the combined token counts and
requires no threshold tuning. Each invalid candidate continues to be dropped
independently so one bad item does not discard valid items from the same
Bedrock response.

### Prompt contract

Candidate discovery will continue asking Bedrock for a source excerpt and will
explicitly request verbatim slide wording. Token grounding remains the trust
boundary; prompt compliance alone is never treated as proof of provenance.

## Error Handling and Safety

- Out-of-chunk slide indexes fail before any text comparison.
- Empty or placeholder-only excerpts fail grounding.
- Any invented word, number, fraction, decimal, or operator fails grounding.
- Reordered tokens fail grounding even if each token appears somewhere on the
  slide.
- Grounding does not raise for one malformed candidate; it filters that item
  and continues processing the response.

Ordered-token grounding intentionally allows a model to select noncontiguous
content from one slide. The discovery prompt still determines whether that
content represents one concrete problem; grounding proves provenance rather
than independently reclassifying mathematical meaning.

## Testing

Automated tests will cover:

- the reproduced Grade 7 body-plus-notes/table-formatting case;
- normalized capitalization and whitespace;
- out-of-chunk slide indexes;
- fabricated text;
- changed numeric values and arithmetic operators;
- reordered real slide content; and
- empty or placeholder-only excerpts.

The focused discovery tests must demonstrate red before the implementation
change and green afterward. The full backend suite, compilation, and dependency
checks must remain clean. After automated verification, rerun the six approved
PPTX decks through live Bedrock discovery and confirm that the Grade 7 problems
are no longer filtered solely because of formatting or omitted intervening
text.
