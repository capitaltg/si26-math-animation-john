# Week 1 Latency Benchmark

The benchmark script is implemented at `backend/scripts/benchmark_latency.py`.
It completed successfully on 2026-07-20 using the configured global Claude
Sonnet 4.6 inference profile.

| Scene | Extraction | Render | Total |
|---|---:|---:|---:|
| Start at 4 apples, add 3, give away 1 | 1.68s | 1.85s | 3.53s |
| Start at 10 stickers, give away 4, receive 2 | 1.42s | 1.66s | 3.08s |
| Start at 7 points, add 5, subtract 2 | 1.39s | 1.83s | 3.22s |

The roughly 3-second end-to-end duration is compatible with the planned
synchronous request plus spinner UX.

After Bedrock model access is granted, rerun:

```bash
cd backend
../.venv/bin/python scripts/benchmark_latency.py
```
