# Week 1 Discovery Eval

The programmatic fixture generator and evaluation runner are implemented at:

- `eval/generate_fixtures.py`
- `eval/run_eval.py`

The three fixture decks were generated successfully:

- `zero_candidate_deck.pptx`
- `distractor_heavy_deck.pptx`
- `ambiguous_phrasing_deck.pptx`

The real Bedrock evaluation completed on 2026-07-20:

| Fixture | Candidates | Judgment |
|---|---:|---|
| `zero_candidate_deck.pptx` | 0 | Correct: no concrete math problem. |
| `distractor_heavy_deck.pptx` | 1 | Correct: found the apples problem and excluded the date, standard, and page number. |
| `ambiguous_phrasing_deck.pptx` | 0 | Reasonable: did not promote an under-specified “how many in all?” prompt. |

The distractor candidate summary reports the operation without stating a
computed final answer, as required.

After Bedrock model access is granted, rerun:

```bash
cd eval
../.venv/bin/python run_eval.py
```
