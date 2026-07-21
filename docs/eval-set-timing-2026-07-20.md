# Eval-Set Processing Time

On 2026-07-20, the current `main` pipeline at revision `b31c359bf7c547ea986a0451152978af5de7c4a6` processed all six eval-set decks sequentially in AWS region `us-east-1` using model `global.anthropic.claude-sonnet-4-6`.

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

The `eval set/` directory is local and ignored by Git, so a clean checkout does not contain the fixture files. Before timing, place exactly these six PowerPoint files in `eval set/`:

| Filename | SHA-256 |
| --- | --- |
| g1 fractions.pptx | `e591f9778db7cf23f7f5ca29527b8cc562a876f0a6cb2ca1cebdb384246eb3e4` |
| g2 composing and decomposing.pptx | `df2420ffb9916b90646c3f891c9e968395ce6bfc0e9f627cfe3157c9e533e02d` |
| g3 fractions on number line.pptx | `f7fb07ae952a01ef8d8ac55ce4083ecba036bde581be96f238d7e4a056a83a5f` |
| g6 u5 l1.pptx | `a3e637405b7334d35ef19b6efdc96e9b42764a497835645c2de61a16920d00ef` |
| g6 u5 l7.pptx | `f4e9df780401e3bfd5193ef31774bf1ab3629bf68833239f2c123f942f2f27f1` |
| g7 u2 l2.pptx | `d67bf7e5033a79acc0ae4049c577813ab9cddd6f9a54f1d3606c12a7a8d493ec` |

From the repository root, verify the fixture names, count, and hashes before timing:

```bash
python3 - <<'PY'
from hashlib import sha256
from pathlib import Path

expected = {
    "g1 fractions.pptx": "e591f9778db7cf23f7f5ca29527b8cc562a876f0a6cb2ca1cebdb384246eb3e4",
    "g2 composing and decomposing.pptx": "df2420ffb9916b90646c3f891c9e968395ce6bfc0e9f627cfe3157c9e533e02d",
    "g3 fractions on number line.pptx": "f7fb07ae952a01ef8d8ac55ce4083ecba036bde581be96f238d7e4a056a83a5f",
    "g6 u5 l1.pptx": "a3e637405b7334d35ef19b6efdc96e9b42764a497835645c2de61a16920d00ef",
    "g6 u5 l7.pptx": "f4e9df780401e3bfd5193ef31774bf1ab3629bf68833239f2c123f942f2f27f1",
    "g7 u2 l2.pptx": "d67bf7e5033a79acc0ae4049c577813ab9cddd6f9a54f1d3606c12a7a8d493ec",
}
fixture_dir = Path("eval set")
actual = {path.name for path in fixture_dir.glob("*.pptx")}
assert actual == set(expected), f"expected exactly {sorted(expected)}, found {sorted(actual)}"
for name, expected_digest in expected.items():
    actual_digest = sha256((fixture_dir / name).read_bytes()).hexdigest()
    assert actual_digest == expected_digest, f"SHA-256 mismatch for {name}"
print("Verified exactly six eval-set fixtures and their SHA-256 hashes.")
PY
```

Then run the timing command from the repository root:

```bash
backend/.venv/bin/python -c 'import json, time; from pathlib import Path; from eval.run_eval import run_fixture; from app.config import get_settings; paths=sorted(Path("eval set").glob("*.pptx")); started=time.perf_counter(); rows=[]; [(lambda deck_started, path: rows.append({"fixture": (report := run_fixture(path))["fixture"], "candidate_count": report["candidate_count"], "elapsed_seconds": time.perf_counter() - deck_started}))(time.perf_counter(), path) for path in paths]; total=time.perf_counter()-started; print(json.dumps({"model": get_settings().bedrock_model_id, "deck_count": len(rows), "total_seconds": total, "average_seconds": total / len(rows), "decks": rows}, indent=2))'
```
