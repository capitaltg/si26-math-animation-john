# Chain Feature Fixture Design

## Goal

Add a generated PowerPoint fixture that exercises post-hoc chaining with three
independently discovered storyboard scenes sharing the `number_line` template.

## Fixture

`eval/fixtures/chain_test_deck.pptx` contains three slides, one problem per
slide:

1. Start at 3 and move forward 4, producing 7.
2. Start at 7 and move back 5, producing 2.
3. Start at 2 and move forward 6, producing 8.

The result of each problem is the starting value of the next problem. Each
slide remains a complete standalone prompt so candidate discovery and parameter
extraction can build three separate `pending_review` scenes before the user
combines them.

## Implementation

- Keep `build_chain_test_deck` in `eval/generate_fixtures.py`.
- Generate `chain_test_deck.pptx` from `main()` alongside the existing fixture
  decks.
- Update the fixture-builder test to include the new builder and verify the
  generated deck contains the expected three-slide arithmetic chain.

## Verification

- Run the fixture-builder test.
- Generate the fixture deck.
- Extract and compare slide text against the three expected prompts.
- Render all slides and inspect them for clipping, overflow, or unintended
  overlap.
