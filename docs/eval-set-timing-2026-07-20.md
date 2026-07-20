# Eval-Set Processing Time

On 2026-07-20, the current `main` pipeline processed all six eval-set decks sequentially using model `global.anthropic.claude-sonnet-4-6`.

| Deck | Candidates | Processing time |
| --- | ---: | ---: |
| g1 fractions.pptx | 0 | 1.41 seconds |
| g2 composing and decomposing.pptx | 10 | 12.78 seconds |
| g3 fractions on number line.pptx | 19 | 24.54 seconds |
| g6 u5 l1.pptx | 4 | 11.83 seconds |
| g6 u5 l7.pptx | 11 | 14.62 seconds |
| g7 u2 l2.pptx | 4 | 7.27 seconds |

- Total processing time: **72.45 seconds**
- Average processing time: **12.08 seconds per deck**

Each deck timer wraps the complete `run_fixture(path)` call: PPTX text extraction, live Bedrock discovery, response validation, and local ordered-token grounding. The decks ran without mocks or concurrency. Live Bedrock candidate counts and latency can vary between runs.

## To reproduce

Run from the repository root:

```bash
backend/.venv/bin/python -c 'import json, time; from pathlib import Path; from eval.run_eval import run_fixture; from app.config import get_settings; paths=sorted(Path("eval set").glob("*.pptx")); started=time.perf_counter(); rows=[]; [(lambda deck_started, path: rows.append({"fixture": (report := run_fixture(path))["fixture"], "candidate_count": report["candidate_count"], "elapsed_seconds": time.perf_counter() - deck_started}))(time.perf_counter(), path) for path in paths]; total=time.perf_counter()-started; print(json.dumps({"model": get_settings().bedrock_model_id, "deck_count": len(rows), "total_seconds": total, "average_seconds": total / len(rows), "decks": rows}, indent=2))'
```
