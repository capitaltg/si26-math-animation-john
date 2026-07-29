# Math Animation Generator

Upload a PPTX of K–8 math example problems, pick the problems you want, choose a visualization for each from ranked compatible options, and download short Manim-rendered MP4 clips. A FastAPI backend discovers candidate problems, classifies each selected problem into compatible visual templates (number line, array grid, fraction bar, balance scale, or text card), validates the teacher's choice, and renders it — falling back to an honest, labeled text card when extraction or rendering cannot satisfy the chosen template. A React + Vite frontend drives the upload → select problems → choose visualizations → render flow.

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

## Meta-template demo (dev only)

The meta-template system learns from concrete solvable problems that fall back
to `text_card` because no structural template fits. It generates a declarative
draft in a separate worker, validates and previews that draft, requires a human
review, and publishes an immutable dynamic template version for later matching
problems.

This workflow is intended for a local developer demo. Keep all meta-template
flags disabled in production until the operational rollout work is complete.

### 1. Prepare the backend

Make sure the virtualenv includes the current project dependencies, then create
or upgrade the durable SQLite schema:

```bash
cd backend
../.venv/bin/pip install -e ".[dev]"
../.venv/bin/alembic upgrade head
cd ..
```

Add these values to `backend/.env`. Use a disposable local reviewer token:

```dotenv
META_TEMPLATES_ENABLED=true
META_CODEGEN_ENABLED=true
META_APPROVAL_ENABLED=true
META_DYNAMIC_CLASSIFIER_ENABLED=true
META_REVIEWER_TOKEN=local-meta-demo
FINGERPRINT_OBSERVATION_THRESHOLD=1
```

The threshold is lowered from five observations to one only to keep the demo
short. The backend and worker both read this file; restart them after changing
it.

### 2. Start the three local processes

Use a separate terminal for each command:

```bash
./scripts/run-backend.sh
```

```bash
./scripts/run-frontend.sh
```

```bash
cd backend
PATH="/Library/TeX/texbin:/opt/homebrew/bin:$PATH" \
  ../.venv/bin/python -m scripts.meta_worker
```

The worker checks the durable queue every two seconds. Leave it running for the
whole demo; Ctrl-C stops it cleanly.

### 3. Trigger template generation

Open `http://localhost:5173` and upload a small PPTX containing a concrete
problem outside the built-in structural contracts, for example:

> A rectangle is 8 cm long and 3 cm wide. What is its perimeter?

Select the detected problem, click **Get options**, choose `text_card`, and
build the storyboard. For the fallback to become a learning observation,
`text_card` must be the only compatible option—not a manual choice in place of
an offered structural template.

The worker should log a generated draft ID after Bedrock proposes the bounded
DSL documents and Manim completes deterministic validation and preview
rendering.

### 4. Review and publish

Open `http://localhost:5173/?meta-review`, enter the reviewer token
(`local-meta-demo` in the example), and click **Load drafts**.

For the generated draft:

1. Inspect its classifier description, preview, fixture results, and predicate
   coverage.
2. For the positive fixture tied to the real problem, enter its correct
   expected answer (for the example above, `{"answer": 22}`) and click
   **Save fixture**. Saving re-runs validation and preview generation.
3. If validation still fails, use **Reject and request refinement** with
   specific feedback, then review the new revision.
4. Enter a unique lowercase template name such as `rectangle_perimeter`.
5. Check the mathematical-semantics confirmation and click
   **Approve and publish**.

Approval remains disabled until validation passes, every guard predicate has a
negative witness, the configured number of real fixtures is confirmed, the
template name is valid, and the reviewer explicitly confirms the mathematics.

### 5. Exercise the published template

Return to the main interface and upload a structurally similar problem, such
as:

> A rectangle is 10 cm long and 4 cm wide. What is its perimeter?

Click **Get options**. The approved dynamic template is now part of the
classifier's point-in-time template list. Select it if offered, build and
approve the storyboard scene, then render the MP4 through the normal flow.

Bedrock classification is probabilistic. Keeping the second problem close in
structure and wording to the first makes a live demonstration more reliable.

### Troubleshooting

- **No worker draft appears:** confirm the worker and backend were restarted
  after enabling the flags. Also confirm `text_card` was the only compatible
  option; a manual text-card selection is intentionally not learned.
- **The worker stays idle:** the observation may not have reached the threshold,
  or a job/version for that fingerprint may already exist in `backend/var/meta.db`.
- **The draft says `failed_validation`:** open it in the review panel, inspect
  the fixture details, and reject with targeted refinement feedback. Failed
  drafts are deliberately visible.
- **Bedrock errors:** verify the AWS credential chain, region, and model access
  used by the backend shell are also available to the worker shell.
- **Preview/render errors:** verify Manim, Cairo, Pango, ffmpeg, LaTeX, and
  `dvisvgm` are installed and present on `PATH`.
- **Review API errors in the browser:** restart Vite so it loads the `/meta`
  proxy configuration, then re-enter the reviewer token and click
  **Load drafts**.

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
