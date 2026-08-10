# Math Animation Generator

Upload a PPTX of K–8 math example problems, pick the problems you want, choose a visualization for each from ranked compatible options, and play or download short Manim-rendered MP4 clips. A FastAPI backend discovers candidate problems, classifies each selected problem into compatible visual templates (number line, array grid, fraction bar, balance scale, or text card), validates the teacher's choice, and renders it — falling back to an honest, labeled text card when extraction or rendering cannot satisfy the chosen template. A React + Vite frontend drives the upload → select problems → choose visualizations → render flow.

The LLM never computes arithmetic: it proposes structurally compatible templates, infers a grade, and extracts template parameters. Every running total and equality is recomputed and validated in Python.

## Repository layout

```
backend/    FastAPI app, pipeline, Manim templates, tests
frontend/   React + Vite single-page app
```

## Prerequisites

- **Python 3.11+** (developed on 3.14)
- **Node 18+** and npm (developed on Node 26 / npm 11)
- **ffmpeg** — video encoding
- **Cairo + Pango + pkg-config** — Manim native rendering deps
- **LaTeX** (`latex` + `dvisvgm`) — number-line labels use MathTeX
- **AWS credentials with Amazon Bedrock access** — required for `/upload` (problem discovery), `/options` (ranked classification), and `/render` (parameter extraction)

### macOS (Homebrew)

```bash
brew install ffmpeg cairo pango pkg-config
brew install --cask basictex     # LaTeX; then: sudo tlmgr install standalone preview doublestroke dvisvgm
```

Homebrew binaries and LaTeX must be on `PATH` when rendering:

```bash
export PATH="/Library/TeX/texbin:/opt/homebrew/bin:$PATH"
```

## Backend

### 1. Create the virtualenv and install

```bash
cd backend
python3 -m venv ../.venv
../.venv/bin/pip install -e ".[dev]"
```

### 2. Configure AWS / Bedrock

Either use your standard AWS credential chain (env vars / `~/.aws`), or create `backend/.env`:

```dotenv
aws_region=us-east-1
bedrock_model_id=global.anthropic.claude-sonnet-4-6
aws_access_key_id=YOUR_KEY
aws_secret_access_key=YOUR_SECRET
# aws_session_token=...   # only if using temporary credentials
```

Defaults: region `us-east-1`, model `global.anthropic.claude-sonnet-4-6`.

### 3. Run

```bash
cd backend
PATH="/Library/TeX/texbin:/opt/homebrew/bin:$PATH" ../.venv/bin/uvicorn app.main:app --port 8000 --reload
```

Backend serves on `http://localhost:8000` (CORS allows the Vite dev origin `http://localhost:5173`).

#### Deployment: single process only

Session state (uploads, candidates, clips, thumbnails) is an in-memory
`OrderedDict` in the backend process. Do **not** run with `uvicorn --workers
N` (N > 1) or behind a load balancer across multiple backend instances: each
worker/instance keeps its own session universe, so a request routed to a
process that never saw the upload returns 400. Stay on one worker per
instance until session state moves to a durable store (Redis / Postgres /
etc.).

## Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend serves on `http://localhost:5173`. Its dev server proxies `/upload`, `/options`, `/render`, and `/clips` to the backend on `:8000`, so the browser talks to a single origin and the session cookie flows without cross-origin friction.

**Start the backend first**, then the frontend. Open `http://localhost:5173`, upload a small PPTX with a math problem, select one or more candidates, click **Get options.**, choose a visualization for each problem, and click **Render.** — a playable, downloadable clip (or a labeled fallback reason) appears.

Production build:

```bash
cd frontend
npm run build      # emits frontend/dist/
```

## Meta-template demo (dev only)

The meta-template system can learn a bounded, reviewable animation template
from a concrete problem that falls back to `text_card`, then reuse the
published template for structurally similar problems.

Generation produces a **semantic teaching plan**, not animation code: one
learning objective, one primary semantic visual, a closed explanation strategy,
and three to five ordered teaching beats ending in an explicit conclusion. A
deterministic compiler lowers that plan into a parameterized scene program, and
every preview and render resolves the program against the current field values
(measure → lay out → resolve anchors → bind the timeline → render). Static and
rendered quality gates run privately before a draft becomes reviewable, so a
reviewer only ever sees candidates whose pacing, anchors and rendered frames
already pass.

The demo publishes two lessons from the bundled deck — a rectangle perimeter
(`boundary_trace`) and a median of seven (`pair_elimination`) — and reuses the
perimeter template on a second problem. For setup, the live presentation
sequence, expected checkpoints, reset steps, and troubleshooting, follow the
canonical [meta-template demo runbook](docs/meta-template-demo.md).

The v3 teaching-plan schema replaces the earlier generated-animation-document
format outright: **v1/v2 drafts and published versions are intentionally not
supported**. After migrating to the v3 schema, reset the disposable demo
database as the runbook describes rather than trying to reuse older drafts.

Keep all meta-template flags disabled in production until the operational
rollout work is complete.

## Testing

```bash
cd backend
PATH="/Library/TeX/texbin:/opt/homebrew/bin:$PATH" ../.venv/bin/python -m pytest
```

The render smoke tests invoke real Manim + ffmpeg (a few minutes; the `PATH` prefix is required). Pipeline and route tests mock Bedrock, so no AWS credentials are needed to run the suite.

The frontend has no test framework in this scope; it is verified via `npm run build`.

## API

| Method | Path           | Purpose                                                                 |
|--------|----------------|-------------------------------------------------------------------------|
| POST   | `/upload`      | Multipart PPTX (`.pptx` only, ≤50 slides, ≤50 MB) → discovered candidates + httponly session cookie |
| POST   | `/options`     | JSON `{ "candidate_ids": [...] }` → ranked compatible templates + rationale per selected candidate |
| POST   | `/render`      | JSON `{ "picks": [{ "candidate_id": "...", "template": "number_line" }] }` → rendered clips with status / clip URL / fallback reason |
| GET    | `/clips/{id}`  | Download a rendered MP4 by server-issued clip id                        |

State is in-memory only (no database); it does not survive a restart.
