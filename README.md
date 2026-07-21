# Math Animation Generator

Upload a PPTX of K–8 math example problems, pick the problems you want, choose a visualization for each from ranked compatible options, and download short Manim-rendered MP4 clips. A FastAPI backend discovers candidate problems, classifies each selected problem into compatible visual templates (number line, array grid, fraction bar, balance scale, or text card), validates the teacher's choice, and renders it — falling back to an honest, labeled text card when extraction or rendering cannot satisfy the chosen template. A React + Vite frontend drives the upload → select problems → choose visualizations → render flow.

The LLM never computes arithmetic: it only selects a template and infers a grade. Every running total and equality is recomputed and validated in Python.

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

## Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend serves on `http://localhost:5173`. Its dev server proxies `/upload`, `/options`, `/render`, and `/clips` to the backend on `:8000`, so the browser talks to a single origin and the session cookie flows without cross-origin friction.

**Start the backend first**, then the frontend. Open `http://localhost:5173`, upload a small PPTX with a math problem, select one or more candidates, click **Get options.**, choose a visualization for each problem, and click **Render.** — a downloadable clip (or a labeled fallback reason) appears.

Production build:

```bash
cd frontend
npm run build      # emits frontend/dist/
```

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
