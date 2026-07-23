# Storyboard Review UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Insert a storyboard review step between template selection and full render — teachers see a fast thumbnail preview per scene, edit extracted values (re-validated), override grade, and approve / reject / retry before any MP4 is rendered.

**Architecture:** New `POST /storyboard` runs extraction + thumbnail render per pick and caches `Scene` objects in the session. `PATCH`/retry/approve/reject mutate those cached scenes. `POST /render` changes to render only *approved* scenes from their **stored** params (no re-extraction). A schema-driven React form renders editable values for all six templates from each template's pydantic JSON schema.

**Tech Stack:** FastAPI + Pydantic v2 (backend), Manim (render, existing), React 18 + Vite (frontend). Tests: pytest via `backend/.venv/bin/pytest`.

## Global Constraints

- Run backend tests with `backend/.venv/bin/pytest` **from the `backend/` directory** — there is no `python`/`pytest` on PATH. (`test_routes.py` runs green today; `httpx2` + `python-multipart` are already installed.)
- No new frontend dependencies and no CSS framework — keep the existing inline-style approach in `App.jsx`.
- Server is the sole validator. The frontend never re-implements guard logic; it submits values and renders server errors.
- Full render for an approved scene uses its **stored** params — never a fresh extraction.
- No grounding check on teacher edits (grounding guards model fabrication only). Grounding still runs inside extraction.
- Grade range is `0 ≤ grade ≤ 8` (enforced by `Scene.grade_level`).
- Spec: `docs/storyboard-review-ui-design-2026-07-22.md`.

---

### Task 1: Relax the Scene fallback invariant

A teacher can approve a fallback (text-card) scene. That flips `status` to `approved` while the scene keeps its `fallback_reason`. The current validator forbids that combination, so relax it: a fallback scene is identified by having a `fallback_reason`, and may carry that reason through any review status.

**Files:**
- Modify: `backend/app/models/scene.py:32-50`
- Test: `backend/tests/models/test_models.py`

**Interfaces:**
- Produces: `Scene` may have `status in {approved, rejected, pending_review}` while `fallback_reason` is non-null. `status == "fallback"` still requires a non-blank `fallback_reason`.

- [ ] **Step 1: Replace the obsolete invariant test**

In `backend/tests/models/test_models.py`, delete `test_non_fallback_scene_rejects_a_fallback_reason` (line ~74) and add:

```python
def test_fallback_scene_keeps_its_reason():
    scene = Scene(
        scene_id="s8",
        candidate_id="c8",
        template=TemplateName.TEXT_CARD,
        grade_level=2,
        status="fallback",
        fallback_reason="This problem did not fit the chosen visual template.",
    )
    assert scene.status == "fallback"
    assert scene.fallback_reason


def test_fallback_status_still_requires_a_reason():
    import pytest

    with pytest.raises(ValueError):
        Scene(scene_id="s9", candidate_id="c9", grade_level=2, status="fallback")
```

(`test_fallback_scene_requires_a_reason` at line ~69 already covers the second case; keep whichever ends up duplicated — do not leave two identical tests.)

- [ ] **Step 2: Run the tests to verify the new expectation fails**

Run: `backend/.venv/bin/pytest tests/models/test_models.py -v`
Expected: `test_fallback_scene_keeps_its_reason` FAILS (ValueError raised by the current validator).

- [ ] **Step 3: Relax the validator**

In `backend/app/models/scene.py`, replace the fallback block of `_check_workflow_invariants` (the two `if` statements about `fallback_reason`) with:

```python
        has_fallback_reason = bool(
            self.fallback_reason and self.fallback_reason.strip()
        )
        if self.status == "fallback" and not has_fallback_reason:
            raise ValueError("Fallback scenes require a nonblank fallback_reason")
        return self
```

(Drops only the `status != "fallback" and fallback_reason is not None` clause.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `backend/.venv/bin/pytest tests/models/test_models.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/scene.py backend/tests/models/test_models.py
git commit -m "feat: allow approved/rejected fallback scenes to keep their reason"
```

---

### Task 2: Session state for scenes + thumbnail registry

Add per-session storyboard state and a thumbnail registry that mirrors the existing clip registry.

**Files:**
- Modify: `backend/app/session.py`
- Test: `backend/tests/test_session.py`

**Interfaces:**
- Produces:
  - `Session.scenes: dict[str, Scene]` (keyed by `scene_id`)
  - `Session.scene_order: list[str]`
  - `Session.scene_requested_template: dict[str, TemplateName]` (scene_id → the template the teacher picked, so retry re-extracts the intended template even after a fallback)
  - `SessionStore.register_thumbnail(path: Path) -> str`
  - `SessionStore.get_thumbnail(thumb_id: str) -> Path | None`

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/test_session.py`:

```python
def test_session_starts_with_empty_storyboard(tmp_path):
    from app.session import SessionStore

    store = SessionStore(tmp_path)
    session = store.create([])
    assert session.scenes == {}
    assert session.scene_order == []
    assert session.scene_requested_template == {}


def test_register_and_get_thumbnail_round_trips(tmp_path):
    from app.session import SessionStore

    store = SessionStore(tmp_path)
    png = tmp_path / "thumb.png"
    png.write_bytes(b"fake-png")
    thumb_id = store.register_thumbnail(png)
    assert store.get_thumbnail(thumb_id) == png


def test_get_unknown_thumbnail_is_none(tmp_path):
    from app.session import SessionStore

    store = SessionStore(tmp_path)
    assert store.get_thumbnail("nope") is None


def test_thumbnail_registry_evicts_oldest_over_cap(tmp_path):
    from app.session import SessionStore

    store = SessionStore(tmp_path, max_thumbnails=2)
    first = store.register_thumbnail(tmp_path / "a.png")
    store.register_thumbnail(tmp_path / "b.png")
    store.register_thumbnail(tmp_path / "c.png")
    assert store.get_thumbnail(first) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `backend/.venv/bin/pytest tests/test_session.py -v`
Expected: FAIL (`scenes`/`register_thumbnail` not defined).

- [ ] **Step 3: Implement**

In `backend/app/session.py`:

```python
from app.models.scene import Scene, TemplateName
```

Add fields to the `Session` dataclass:

```python
    scenes: dict[str, Scene] = field(default_factory=dict)
    scene_order: list[str] = field(default_factory=list)
    scene_requested_template: dict[str, TemplateName] = field(default_factory=dict)
```

Add a constant near the other defaults:

```python
DEFAULT_MAX_THUMBNAILS = 1000
```

Extend `SessionStore.__init__` signature and body:

```python
    def __init__(
        self,
        root_dir: Path,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
        max_clips: int = DEFAULT_MAX_CLIPS,
        max_thumbnails: int = DEFAULT_MAX_THUMBNAILS,
    ):
        self._root = Path(root_dir)
        self._max_sessions = max_sessions
        self._max_clips = max_clips
        self._max_thumbnails = max_thumbnails
        self._sessions: OrderedDict[str, Session] = OrderedDict()
        self._clips: OrderedDict[str, Path] = OrderedDict()
        self._thumbnails: OrderedDict[str, Path] = OrderedDict()
```

Add methods:

```python
    def register_thumbnail(self, path: Path) -> str:
        thumb_id = str(uuid4())
        self._thumbnails[thumb_id] = Path(path)
        if len(self._thumbnails) > self._max_thumbnails:
            self._thumbnails.popitem(last=False)
        return thumb_id

    def get_thumbnail(self, thumb_id: str) -> Path | None:
        return self._thumbnails.get(thumb_id)
```

- [ ] **Step 4: Run to verify pass**

Run: `backend/.venv/bin/pytest tests/test_session.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/session.py backend/tests/test_session.py
git commit -m "feat: add storyboard scene state and thumbnail registry to session"
```

---

### Task 3: `assemble_scene` — extraction + thumbnail preview

New pipeline function: extract params for a chosen template, render a **thumbnail**, and return a `pending_review` scene — or a text-card fallback (with a thumbnail of the card) on mismatch. Mirrors `process_scene` but for the preview stage.

**Files:**
- Modify: `backend/app/pipeline/process_scene.py`
- Test: `backend/tests/pipeline/test_process_scene.py`

**Interfaces:**
- Consumes: `render_scene_thumbnail` (existing, `app/render/full_render.py`), `extract_params`, `get_template`.
- Produces: `assemble_scene(candidate: Candidate, output_dir: Path, *, template: TemplateName, grade: int) -> Scene`. Success → `status="pending_review"`, `thumbnail_path` set, `params` populated. Mismatch/validation → `status="fallback"`, `template=TEXT_CARD`, `fallback_reason` set, thumbnail of the text card.

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/pipeline/test_process_scene.py`:

```python
def test_assemble_scene_returns_pending_review_with_thumbnail(tmp_path):
    from unittest.mock import patch

    from app.models.candidate import Candidate
    from app.models.scene import TemplateName
    from app.pipeline.process_scene import assemble_scene
    from app.templates.number_line.params import NumberLineParams, NumberLineStep

    candidate = Candidate(
        candidate_id="c1",
        source_excerpt="Sarah has 4 apples and buys 3 more.",
        slide_index=0,
        one_line_summary="Detected: 4 + 3",
    )
    params = NumberLineParams(start=4, steps=[NumberLineStep(operation="add", amount=3)])

    with patch("app.pipeline.process_scene.extract_params", return_value=params), patch(
        "app.pipeline.process_scene.render_scene_thumbnail"
    ) as thumb:
        scene = assemble_scene(
            candidate, tmp_path, template=TemplateName.NUMBER_LINE, grade=1
        )

    assert scene.status == "pending_review"
    assert scene.template == TemplateName.NUMBER_LINE
    assert scene.thumbnail_path is not None
    assert scene.params["start"] == 4
    thumb.assert_called_once()


def test_assemble_scene_falls_back_on_template_mismatch(tmp_path):
    from unittest.mock import patch

    from app.models.candidate import Candidate
    from app.models.scene import TemplateName
    from app.pipeline.extraction import TemplateMismatchError
    from app.pipeline.process_scene import (
        TEMPLATE_MISMATCH_REASON,
        assemble_scene,
    )

    candidate = Candidate(
        candidate_id="c2",
        source_excerpt="A list of 30 spelling words.",
        slide_index=0,
        one_line_summary="Detected: word list",
    )

    with patch(
        "app.pipeline.process_scene.extract_params",
        side_effect=TemplateMismatchError("no add/subtract sequence"),
    ), patch("app.pipeline.process_scene.render_scene_thumbnail"):
        scene = assemble_scene(
            candidate, tmp_path, template=TemplateName.NUMBER_LINE, grade=3
        )

    assert scene.status == "fallback"
    assert scene.template == TemplateName.TEXT_CARD
    assert scene.fallback_reason == TEMPLATE_MISMATCH_REASON
    assert scene.thumbnail_path is not None
```

- [ ] **Step 2: Run to verify failure**

Run: `backend/.venv/bin/pytest tests/pipeline/test_process_scene.py -k assemble_scene -v`
Expected: FAIL (`assemble_scene` not defined).

- [ ] **Step 3: Implement**

In `backend/app/pipeline/process_scene.py`, add the thumbnail import at the top with the other render import:

```python
from app.render.full_render import render_scene_thumbnail, render_scene_to_mp4
```

Add a thumbnail path helper next to `_unique_output_path`:

```python
def _unique_thumbnail_path(candidate: Candidate, output_dir: Path) -> Path:
    return output_dir / f"{candidate.candidate_id}-{uuid4()}.png"
```

Refactor `_fallback_scene` to render either a full clip or a thumbnail (replace its body):

```python
def _fallback_scene(
    candidate: Candidate,
    grade: int,
    reason: str,
    output_dir: Path,
    *,
    thumbnail: bool = False,
) -> Scene:
    lines = [line for line in (candidate.source_excerpt, reason) if line and line.strip()]
    if not lines:
        lines = ["Unable to animate this problem"]
    headline = (candidate.one_line_summary or "").strip() or "Unable to animate this problem"
    params = TextCardParams(headline=headline, lines=lines)

    render_path = None
    thumbnail_path = None
    try:
        if thumbnail:
            out = _unique_thumbnail_path(candidate, output_dir)
            render_scene_thumbnail(TemplateName.TEXT_CARD, params, out)
            thumbnail_path = out
        else:
            out = _unique_output_path(candidate, output_dir)
            render_scene_to_mp4(TemplateName.TEXT_CARD, params, out)
            render_path = out
    except Exception:
        logger.warning(
            "Fallback render failed for candidate %s; returning fallback scene without media",
            candidate.candidate_id,
            exc_info=True,
        )

    return Scene(
        scene_id=str(uuid4()),
        candidate_id=candidate.candidate_id,
        template=TemplateName.TEXT_CARD,
        grade_level=grade,
        params=params.model_dump(mode="json"),
        status="fallback",
        fallback_reason=reason,
        render_path=render_path,
        thumbnail_path=thumbnail_path,
    )
```

Add `assemble_scene` at the end of the module:

```python
def assemble_scene(
    candidate: Candidate,
    output_dir: Path,
    *,
    template: TemplateName,
    grade: int,
) -> Scene:
    _, params_cls = get_template(template)

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            params = extract_params(candidate.source_excerpt, params_cls)
            thumb_path = _unique_thumbnail_path(candidate, output_dir)
            render_scene_thumbnail(template, params, thumb_path)
            return Scene(
                scene_id=str(uuid4()),
                candidate_id=candidate.candidate_id,
                template=template,
                grade_level=grade,
                params=params.model_dump(mode="json"),
                status="pending_review",
                thumbnail_path=thumb_path,
            )
        except TemplateMismatchError as exc:
            last_error = exc
            break
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(BACKOFF_SECONDS)

    if isinstance(last_error, (ValidationError, TemplateMismatchError)):
        return _fallback_scene(
            candidate, grade, TEMPLATE_MISMATCH_REASON, output_dir, thumbnail=True
        )
    return _fallback_scene(
        candidate, grade, TECHNICAL_FAILURE_REASON, output_dir, thumbnail=True
    )
```

- [ ] **Step 4: Run to verify pass (and no regression in process_scene)**

Run: `backend/.venv/bin/pytest tests/pipeline/test_process_scene.py -v`
Expected: PASS (existing `process_scene` tests still pass — `_fallback_scene`'s default `thumbnail=False` preserves old behavior).

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/process_scene.py backend/tests/pipeline/test_process_scene.py
git commit -m "feat: add assemble_scene for thumbnail-preview storyboard stage"
```

---

### Task 4: `POST /storyboard` + `GET /thumbnails/{id}` + SceneOut

Build the storyboard: validate picks against cached options, run `assemble_scene` per pick, store scenes in the session, and return serialized scenes carrying the JSON schema that drives the edit form. Serve thumbnails.

**Files:**
- Modify: `backend/app/routes.py`
- Test: `backend/tests/test_routes.py`

**Interfaces:**
- Consumes: `assemble_scene` (Task 3); `Session.scenes`/`scene_order`/`scene_requested_template`, `register_thumbnail`/`get_thumbnail` (Task 2).
- Produces:
  - `SceneOut` model (fields listed below) — used by Tasks 5, 6.
  - `_scene_out(scene: Scene, candidate: Candidate) -> SceneOut` helper — used by Tasks 5, 6.
  - `POST /storyboard` body `{picks: [{candidate_id, template}]}` → `{scenes: [SceneOut]}`.
  - `GET /thumbnails/{thumb_id}` → `image/png`.

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/test_routes.py` (helpers `_client`, `_upload_candidate`, `_classification`, `_candidate` already exist at the top of the file):

```python
def _options_then(client):
    """Upload one candidate and cache its options; return the client."""
    with patch("app.routes.classify_candidate", return_value=_classification()):
        client.post("/options", json={"candidate_ids": ["c1"]})
    return client


def test_storyboard_builds_scenes_with_schema_and_thumbnail_url(tmp_path):
    from app.models.scene import Scene, TemplateName

    client = _client()
    _upload_candidate(client)
    _options_then(client)

    thumb = tmp_path / "t.png"
    thumb.write_bytes(b"png")
    fake = Scene(
        scene_id="s1",
        candidate_id="c1",
        template=TemplateName.NUMBER_LINE,
        grade_level=1,
        params={"start": 4, "steps": [{"operation": "add", "amount": 3}]},
        status="pending_review",
        thumbnail_path=thumb,
    )

    with patch("app.routes.assemble_scene", return_value=fake):
        resp = client.post(
            "/storyboard",
            json={"picks": [{"candidate_id": "c1", "template": "number_line"}]},
        )

    assert resp.status_code == 200
    scene = resp.json()["scenes"][0]
    assert scene["scene_id"] == "s1"
    assert scene["status"] == "pending_review"
    assert scene["thumbnail_url"].startswith("/thumbnails/")
    assert scene["source_excerpt"]
    assert scene["detected_summary"] == "Detected: 4 + 3"
    assert scene["params_schema"]["properties"]["start"]["type"] == "integer"


def test_thumbnail_endpoint_serves_png(tmp_path):
    from app.routes import store

    client = _client()
    png = tmp_path / "t.png"
    png.write_bytes(b"\x89PNG\r\n")
    thumb_id = store.register_thumbnail(png)

    resp = client.get(f"/thumbnails/{thumb_id}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"


def test_thumbnail_unknown_id_is_404():
    client = _client()
    assert client.get("/thumbnails/nope").status_code == 404


def test_storyboard_rejects_pick_before_options_cached():
    client = _client()
    _upload_candidate(client)
    resp = client.post(
        "/storyboard",
        json={"picks": [{"candidate_id": "c1", "template": "number_line"}]},
    )
    assert resp.status_code == 400


def test_storyboard_without_session_is_400():
    client = _client()
    resp = client.post(
        "/storyboard",
        json={"picks": [{"candidate_id": "c1", "template": "number_line"}]},
    )
    assert resp.status_code == 400
```

- [ ] **Step 2: Run to verify failure**

Run: `backend/.venv/bin/pytest tests/test_routes.py -k "storyboard or thumbnail" -v`
Expected: FAIL (routes not defined).

- [ ] **Step 3: Implement**

In `backend/app/routes.py`, add imports:

```python
from app.pipeline.process_scene import assemble_scene, process_scene
from app.templates.registry import get_template
from app.models.scene import Scene, TemplateName
```

(Keep the existing `process_scene` import — merge into the line above. `Scene` is new.)

Add response models near the other Pydantic models:

```python
class SceneOut(BaseModel):
    scene_id: str
    candidate_id: str | None
    template: str | None
    grade_level: int
    grade_overridden: bool
    params: dict
    params_schema: dict
    status: str
    fallback_reason: str | None = None
    thumbnail_url: str | None = None
    source_excerpt: str
    detected_summary: str


class StoryboardRequest(BaseModel):
    picks: list[RenderPick] = Field(max_length=MAX_BATCH_SIZE)


class StoryboardResponse(BaseModel):
    scenes: list[SceneOut]
```

Add the serialization helper:

```python
def _scene_out(scene: Scene, candidate) -> SceneOut:
    schema: dict = {}
    if scene.template is not None:
        _, params_cls = get_template(scene.template)
        schema = params_cls.model_json_schema()
    thumbnail_url = None
    if scene.thumbnail_path is not None:
        thumb_id = store.register_thumbnail(scene.thumbnail_path)
        thumbnail_url = f"/thumbnails/{thumb_id}"
    return SceneOut(
        scene_id=scene.scene_id,
        candidate_id=scene.candidate_id,
        template=scene.template.value if scene.template else None,
        grade_level=scene.grade_level,
        grade_overridden=scene.grade_overridden,
        params=scene.params,
        params_schema=schema,
        status=scene.status,
        fallback_reason=scene.fallback_reason,
        thumbnail_url=thumbnail_url,
        source_excerpt=candidate.source_excerpt,
        detected_summary=candidate.one_line_summary,
    )
```

Add the endpoints:

```python
@router.post("/storyboard", response_model=StoryboardResponse)
def build_storyboard(request: StoryboardRequest, session_id: str | None = Cookie(default=None)):
    session = store.get(session_id) if session_id else None
    if session is None:
        raise HTTPException(status_code=400, detail="No active session; upload a document first")

    candidate_ids = [pick.candidate_id for pick in request.picks]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise HTTPException(status_code=400, detail="Duplicate candidate ids are not allowed")

    validated = []
    for pick in request.picks:
        candidate = session.candidates.get(pick.candidate_id)
        if candidate is None:
            raise HTTPException(status_code=404, detail=f"Unknown candidate {pick.candidate_id}")
        classification = session.options.get(pick.candidate_id)
        if classification is None:
            raise HTTPException(
                status_code=400,
                detail=f"No options cached for candidate {pick.candidate_id}",
            )
        offered = {option.template.value for option in classification.options}
        if pick.template not in offered:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Template {pick.template} was not offered for "
                    f"candidate {pick.candidate_id}"
                ),
            )
        validated.append((candidate, classification, TemplateName(pick.template)))

    session.scenes.clear()
    session.scene_order.clear()
    session.scene_requested_template.clear()

    scenes_out: list[SceneOut] = []
    for candidate, classification, template in validated:
        scene = assemble_scene(
            candidate,
            session.output_dir,
            template=template,
            grade=classification.grade_level,
        )
        session.scenes[scene.scene_id] = scene
        session.scene_order.append(scene.scene_id)
        session.scene_requested_template[scene.scene_id] = template
        scenes_out.append(_scene_out(scene, candidate))
    return StoryboardResponse(scenes=scenes_out)


@router.get("/thumbnails/{thumb_id}")
def get_thumbnail(thumb_id: str):
    path = store.get_thumbnail(thumb_id)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(path, media_type="image/png", filename=path.name)
```

- [ ] **Step 4: Run to verify pass**

Run: `backend/.venv/bin/pytest tests/test_routes.py -k "storyboard or thumbnail" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes.py backend/tests/test_routes.py
git commit -m "feat: add POST /storyboard and GET /thumbnails endpoints"
```

---

### Task 5: `PATCH /storyboard/{scene_id}` — edit + re-validate + re-thumbnail

Edit params and/or grade. Params re-validate against the template (schema + guard). Valid → re-render thumbnail. Invalid → 422 with field errors, prior thumbnail kept.

**Files:**
- Modify: `backend/app/routes.py`
- Test: `backend/tests/test_routes.py`

**Interfaces:**
- Consumes: `_scene_out`, `SceneOut`, `Session.scenes`, `render_scene_thumbnail`, `get_template`.
- Produces: `PATCH /storyboard/{scene_id}` body `{params?: dict, grade_level?: int}` → `SceneOut` (200) or `{detail: {errors: [{loc, msg}]}}` (422). `_field_errors(exc) -> dict` helper.

- [ ] **Step 1: Write failing tests**

Add a seed helper and tests to `backend/tests/test_routes.py`:

```python
def _seed_scene(client, scene, template=None):
    """Attach `scene` to the client's current session (in the module-level store)."""
    from app.models.scene import TemplateName
    from app.routes import store

    session_id = client.cookies.get("session_id")
    session = store.get(session_id)
    session.scenes[scene.scene_id] = scene
    session.scene_order.append(scene.scene_id)
    if template is not None:
        session.scene_requested_template[scene.scene_id] = TemplateName(template)
    return session


def _number_line_scene(tmp_path):
    from app.models.scene import Scene, TemplateName

    thumb = tmp_path / "t.png"
    thumb.write_bytes(b"png")
    return Scene(
        scene_id="s1",
        candidate_id="c1",
        template=TemplateName.NUMBER_LINE,
        grade_level=1,
        params={"start": 4, "steps": [{"operation": "add", "amount": 3}]},
        status="pending_review",
        thumbnail_path=thumb,
    )


def test_patch_valid_params_re_renders_thumbnail(tmp_path):
    client = _client()
    _upload_candidate(client)
    _seed_scene(client, _number_line_scene(tmp_path))

    with patch("app.routes.render_scene_thumbnail") as thumb:
        resp = client.patch(
            "/storyboard/s1",
            json={"params": {"start": 10, "steps": [{"operation": "subtract", "amount": 2}]}},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["params"]["start"] == 10
    assert body["status"] == "pending_review"
    thumb.assert_called_once()


def test_patch_invalid_params_returns_422_and_keeps_scene(tmp_path):
    client = _client()
    _upload_candidate(client)
    _seed_scene(client, _number_line_scene(tmp_path))

    # start=1 then subtract 5 -> running total goes negative -> guard rejects.
    with patch("app.routes.render_scene_thumbnail") as thumb:
        resp = client.patch(
            "/storyboard/s1",
            json={"params": {"start": 1, "steps": [{"operation": "subtract", "amount": 5}]}},
        )

    assert resp.status_code == 422
    assert resp.json()["detail"]["errors"]
    thumb.assert_not_called()


def test_patch_grade_sets_overridden(tmp_path):
    client = _client()
    _upload_candidate(client)
    _seed_scene(client, _number_line_scene(tmp_path))

    resp = client.patch("/storyboard/s1", json={"grade_level": 5})
    assert resp.status_code == 200
    assert resp.json()["grade_level"] == 5
    assert resp.json()["grade_overridden"] is True


def test_patch_unknown_scene_is_404():
    client = _client()
    _upload_candidate(client)
    resp = client.patch("/storyboard/nope", json={"grade_level": 3})
    assert resp.status_code == 404
```

- [ ] **Step 2: Run to verify failure**

Run: `backend/.venv/bin/pytest tests/test_routes.py -k patch -v`
Expected: FAIL (route not defined).

- [ ] **Step 3: Implement**

In `backend/app/routes.py` add imports and models:

```python
from uuid import uuid4
from pydantic import ValidationError
from app.render.full_render import render_scene_thumbnail
```

```python
class SceneEditRequest(BaseModel):
    params: dict | None = None
    grade_level: int | None = Field(default=None, ge=0, le=8)
```

Add the field-error helper:

```python
def _field_errors(exc: ValidationError) -> dict:
    return {"errors": [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]}
```

Add the endpoint:

```python
@router.patch("/storyboard/{scene_id}", response_model=SceneOut)
def edit_scene(
    scene_id: str,
    request: SceneEditRequest,
    session_id: str | None = Cookie(default=None),
):
    session = store.get(session_id) if session_id else None
    if session is None:
        raise HTTPException(status_code=400, detail="No active session; upload a document first")
    scene = session.scenes.get(scene_id)
    if scene is None:
        raise HTTPException(status_code=404, detail=f"Unknown scene {scene_id}")
    candidate = session.candidates.get(scene.candidate_id)
    if scene.template is None:
        raise HTTPException(status_code=400, detail="Cannot edit a scene without a template")

    new_params = scene.params
    new_thumb = scene.thumbnail_path
    if request.params is not None:
        _, params_cls = get_template(scene.template)
        try:
            params = params_cls.model_validate(request.params)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=_field_errors(exc))
        out = session.output_dir / f"{scene.candidate_id}-{uuid4()}.png"
        try:
            render_scene_thumbnail(scene.template, params, out)
        except Exception as exc:
            raise HTTPException(status_code=500, detail="Thumbnail render failed") from exc
        new_params = params.model_dump(mode="json")
        new_thumb = out

    grade = request.grade_level if request.grade_level is not None else scene.grade_level
    grade_overridden = scene.grade_overridden or request.grade_level is not None

    updated = scene.model_copy(
        update={
            "params": new_params,
            "thumbnail_path": new_thumb,
            "grade_level": grade,
            "grade_overridden": grade_overridden,
        }
    )
    session.scenes[scene_id] = updated
    return _scene_out(updated, candidate)
```

- [ ] **Step 4: Run to verify pass**

Run: `backend/.venv/bin/pytest tests/test_routes.py -k patch -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes.py backend/tests/test_routes.py
git commit -m "feat: add PATCH /storyboard to edit values and grade with re-validation"
```

---

### Task 6: `POST /storyboard/{scene_id}/retry`

Re-extract on the originally-picked template (from `scene_requested_template`), re-render the thumbnail, replace the scene **in place** (same `scene_id`), preserving any grade override.

**Files:**
- Modify: `backend/app/routes.py`
- Test: `backend/tests/test_routes.py`

**Interfaces:**
- Consumes: `assemble_scene`, `_scene_out`, `Session.scene_requested_template`.
- Produces: `POST /storyboard/{scene_id}/retry` → `SceneOut` with the same `scene_id`.

- [ ] **Step 1: Write failing tests**

```python
def test_retry_reextracts_same_template_and_keeps_scene_id(tmp_path):
    from app.models.scene import Scene, TemplateName

    client = _client()
    _upload_candidate(client)
    _seed_scene(client, _number_line_scene(tmp_path), template="number_line")

    fresh = Scene(
        scene_id="ignored-new-id",
        candidate_id="c1",
        template=TemplateName.NUMBER_LINE,
        grade_level=1,
        params={"start": 4, "steps": [{"operation": "add", "amount": 3}]},
        status="pending_review",
        thumbnail_path=(tmp_path / "t.png"),
    )

    with patch("app.routes.assemble_scene", return_value=fresh) as assemble:
        resp = client.post("/storyboard/s1/retry")

    assert resp.status_code == 200
    assert resp.json()["scene_id"] == "s1"  # replaced in place
    # retried on the originally-picked template
    assert assemble.call_args.kwargs["template"] == TemplateName.NUMBER_LINE


def test_retry_unknown_scene_is_404():
    client = _client()
    _upload_candidate(client)
    assert client.post("/storyboard/nope/retry").status_code == 404
```

- [ ] **Step 2: Run to verify failure**

Run: `backend/.venv/bin/pytest tests/test_routes.py -k retry -v`
Expected: FAIL (route not defined).

- [ ] **Step 3: Implement**

```python
@router.post("/storyboard/{scene_id}/retry", response_model=SceneOut)
def retry_scene(scene_id: str, session_id: str | None = Cookie(default=None)):
    session = store.get(session_id) if session_id else None
    if session is None:
        raise HTTPException(status_code=400, detail="No active session; upload a document first")
    scene = session.scenes.get(scene_id)
    if scene is None:
        raise HTTPException(status_code=404, detail=f"Unknown scene {scene_id}")
    candidate = session.candidates.get(scene.candidate_id)
    template = session.scene_requested_template.get(scene_id)
    if template is None:
        raise HTTPException(status_code=400, detail="This scene cannot be retried")

    fresh = assemble_scene(
        candidate,
        session.output_dir,
        template=template,
        grade=scene.grade_level,
    )
    updated = fresh.model_copy(
        update={"scene_id": scene_id, "grade_overridden": scene.grade_overridden}
    )
    session.scenes[scene_id] = updated
    return _scene_out(updated, candidate)
```

- [ ] **Step 4: Run to verify pass**

Run: `backend/.venv/bin/pytest tests/test_routes.py -k retry -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes.py backend/tests/test_routes.py
git commit -m "feat: add POST /storyboard/{id}/retry to re-extract on the picked template"
```

---

### Task 7: `approve` / `reject` endpoints

Set a scene's review status. Approving a fallback scene keeps its `fallback_reason` (Task 1 made this valid).

**Files:**
- Modify: `backend/app/routes.py`
- Test: `backend/tests/test_routes.py`

**Interfaces:**
- Produces: `POST /storyboard/{scene_id}/approve` and `.../reject` → `SceneOut` with updated `status`.

- [ ] **Step 1: Write failing tests**

```python
def test_approve_sets_status(tmp_path):
    client = _client()
    _upload_candidate(client)
    _seed_scene(client, _number_line_scene(tmp_path))
    resp = client.post("/storyboard/s1/approve")
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"


def test_reject_sets_status(tmp_path):
    client = _client()
    _upload_candidate(client)
    _seed_scene(client, _number_line_scene(tmp_path))
    resp = client.post("/storyboard/s1/reject")
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"


def test_approve_fallback_scene_keeps_reason(tmp_path):
    from app.models.scene import Scene, TemplateName

    client = _client()
    _upload_candidate(client)
    fallback = Scene(
        scene_id="s2",
        candidate_id="c1",
        template=TemplateName.TEXT_CARD,
        grade_level=1,
        params={"headline": "x", "lines": ["y"]},
        status="fallback",
        fallback_reason="did not fit the chosen template",
        thumbnail_path=(tmp_path / "t.png"),
    )
    (tmp_path / "t.png").write_bytes(b"png")
    _seed_scene(client, fallback)

    resp = client.post("/storyboard/s2/approve")
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"
    assert resp.json()["fallback_reason"] == "did not fit the chosen template"


def test_approve_unknown_scene_is_404():
    client = _client()
    _upload_candidate(client)
    assert client.post("/storyboard/nope/approve").status_code == 404
```

- [ ] **Step 2: Run to verify failure**

Run: `backend/.venv/bin/pytest tests/test_routes.py -k "approve or reject" -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

```python
def _set_scene_status(session_id: str | None, scene_id: str, status: str) -> SceneOut:
    session = store.get(session_id) if session_id else None
    if session is None:
        raise HTTPException(status_code=400, detail="No active session; upload a document first")
    scene = session.scenes.get(scene_id)
    if scene is None:
        raise HTTPException(status_code=404, detail=f"Unknown scene {scene_id}")
    candidate = session.candidates.get(scene.candidate_id)
    updated = scene.model_copy(update={"status": status})
    session.scenes[scene_id] = updated
    return _scene_out(updated, candidate)


@router.post("/storyboard/{scene_id}/approve", response_model=SceneOut)
def approve_scene(scene_id: str, session_id: str | None = Cookie(default=None)):
    return _set_scene_status(session_id, scene_id, "approved")


@router.post("/storyboard/{scene_id}/reject", response_model=SceneOut)
def reject_scene(scene_id: str, session_id: str | None = Cookie(default=None)):
    return _set_scene_status(session_id, scene_id, "rejected")
```

- [ ] **Step 4: Run to verify pass**

Run: `backend/.venv/bin/pytest tests/test_routes.py -k "approve or reject" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes.py backend/tests/test_routes.py
git commit -m "feat: add approve/reject endpoints for storyboard scenes"
```

---

### Task 8: Rewrite `POST /render` to render approved scenes from stored params

`/render` no longer takes a body or re-extracts. It renders every approved scene in the session using its stored (edited) params. This replaces the old body-driven render path.

**Files:**
- Modify: `backend/app/routes.py`
- Test: `backend/tests/test_routes.py`

**Interfaces:**
- Consumes: `Session.scenes`/`scene_order`, `render_scene_to_mp4`, `get_template`, `store.register_clip`.
- Produces: `POST /render` (no body) → `{clips: [ClipResult]}`. `ClipResult.status` is `"fallback"` when the scene has a `fallback_reason`, `"approved"` on success, `"error"` on render failure.

- [ ] **Step 1: Remove obsolete render tests, write new ones**

Delete the old body-driven `/render` tests in `backend/tests/test_routes.py` (they POST a `picks` body and patch `process_scene`): `test_render_returns_clip_url_for_a_rendered_scene`, `test_render_reports_fallback_reason_without_clip`, `test_render_unknown_candidate_is_404`, `test_render_rejects_template_that_was_not_offered`, `test_render_rejects_pick_before_options_are_cached`, `test_render_rejects_unknown_template_name_as_bad_request`, `test_render_preflights_entire_batch_before_rendering`, `test_render_rejects_duplicate_candidates_before_rendering`, `test_render_rejects_more_than_50_picks_before_rendering`. Keep `test_render_without_session_is_400` and `test_unknown_clip_id_is_404`.

Add:

```python
def test_render_renders_only_approved_from_stored_params(tmp_path):
    client = _client()
    _upload_candidate(client)
    approved = _number_line_scene(tmp_path)
    approved = approved.model_copy(update={"status": "approved"})
    _seed_scene(client, approved)

    def fake_render(template, params, out):
        out.write_bytes(b"mp4")
        return out

    # Bedrock extraction must NOT be called at render time.
    with patch("app.routes.render_scene_to_mp4", side_effect=fake_render), patch(
        "app.pipeline.process_scene.extract_params"
    ) as extract:
        resp = client.post("/render")

    assert resp.status_code == 200
    clips = resp.json()["clips"]
    assert len(clips) == 1
    assert clips[0]["clip_url"].startswith("/clips/")
    extract.assert_not_called()


def test_render_skips_rejected_scenes(tmp_path):
    client = _client()
    _upload_candidate(client)
    rejected = _number_line_scene(tmp_path).model_copy(update={"status": "rejected"})
    _seed_scene(client, rejected)
    resp = client.post("/render")
    assert resp.status_code == 400  # nothing approved


def test_render_one_failure_does_not_sink_batch(tmp_path):
    from app.models.scene import Scene, TemplateName

    client = _client()
    _upload_candidate(client)
    good = _number_line_scene(tmp_path).model_copy(
        update={"scene_id": "sg", "status": "approved"}
    )
    bad = _number_line_scene(tmp_path).model_copy(
        update={"scene_id": "sb", "status": "approved"}
    )
    _seed_scene(client, good)
    _seed_scene(client, bad)

    calls = {"n": 0}

    def render_side_effect(template, params, out):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom")
        out.write_bytes(b"mp4")
        return out

    with patch("app.routes.render_scene_to_mp4", side_effect=render_side_effect):
        resp = client.post("/render")

    assert resp.status_code == 200
    statuses = {c["status"] for c in resp.json()["clips"]}
    assert "error" in statuses
    assert len(resp.json()["clips"]) == 2
```

- [ ] **Step 2: Run to verify failure**

Run: `backend/.venv/bin/pytest tests/test_routes.py -k render -v`
Expected: FAIL (old signature still in place / new tests error).

- [ ] **Step 3: Implement**

In `backend/app/routes.py`:
- Add import: `from app.render.full_render import render_scene_thumbnail, render_scene_to_mp4` (merge with the Task 5 import line).
- Add `import logging` and `logger = logging.getLogger(__name__)` if not present.
- Delete the `RenderRequest` model (no longer used).
- Replace the entire `render` function:

```python
@router.post("/render", response_model=RenderResponse)
def render(session_id: str | None = Cookie(default=None)):
    session = store.get(session_id) if session_id else None
    if session is None:
        raise HTTPException(status_code=400, detail="No active session; upload a document first")

    approved = [
        session.scenes[sid]
        for sid in session.scene_order
        if session.scenes[sid].status == "approved"
    ]
    if not approved:
        raise HTTPException(status_code=400, detail="No approved scenes to render")

    results: list[ClipResult] = []
    for scene in approved:
        _, params_cls = get_template(scene.template)
        params = params_cls.model_validate(scene.params)
        clip_url = None
        try:
            output_path = session.output_dir / f"{scene.candidate_id}-{uuid4()}.mp4"
            render_scene_to_mp4(scene.template, params, output_path)
            clip_id = store.register_clip(output_path)
            clip_url = f"/clips/{clip_id}"
            status = "fallback" if scene.fallback_reason else "approved"
        except Exception:
            logger.exception("Full render failed for scene %s", scene.scene_id)
            status = "error"
        results.append(
            ClipResult(
                candidate_id=scene.candidate_id,
                status=status,
                clip_url=clip_url,
                fallback_reason=scene.fallback_reason,
            )
        )
    return RenderResponse(clips=results)
```

- [ ] **Step 4: Run to verify pass (full route + pipeline suite)**

Run: `backend/.venv/bin/pytest tests/test_routes.py tests/pipeline/test_process_scene.py -v`
Expected: PASS. If any deleted-test references remain, remove them.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes.py backend/tests/test_routes.py
git commit -m "feat: render only approved storyboard scenes from stored params"
```

---

### Task 9: Frontend `<SchemaForm>` — schema-driven editable values

A generic component that renders editable inputs from a template's pydantic JSON schema: numbers, enum dropdowns, and repeatable step rows (array of objects, resolved via `$ref`/`$defs`).

**Files:**
- Create: `frontend/src/SchemaForm.jsx`

**Interfaces:**
- Produces: `export default function SchemaForm({ schema, value, onChange })`. `schema` = a template's `model_json_schema()`; `value` = current params object; `onChange(nextValue)` fires on every edit with the full updated params object.

- [ ] **Step 1: Create the component**

```jsx
// Resolve a { "$ref": "#/$defs/Name" } node against the root schema's $defs.
function resolveRef(node, root) {
  if (node && node.$ref) {
    const name = node.$ref.replace('#/$defs/', '')
    return root.$defs?.[name] ?? {}
  }
  return node
}

function Field({ name, schema, root, value, onChange }) {
  const resolved = resolveRef(schema, root)
  const label = resolved.title || name

  // Enum (Literal) -> dropdown
  if (resolved.enum) {
    return (
      <label style={{ display: 'block', margin: '0.3rem 0' }}>
        {label}:{' '}
        <select value={value ?? ''} onChange={(e) => onChange(e.target.value)}>
          {resolved.enum.map((opt) => (
            <option key={opt} value={opt}>{opt}</option>
          ))}
        </select>
      </label>
    )
  }

  // Number
  if (resolved.type === 'integer' || resolved.type === 'number') {
    return (
      <label style={{ display: 'block', margin: '0.3rem 0' }}>
        {label}:{' '}
        <input
          type="number"
          value={value ?? ''}
          onChange={(e) => {
            const raw = e.target.value
            onChange(raw === '' ? '' : Number(raw))
          }}
        />
      </label>
    )
  }

  // Array of objects -> repeatable rows
  if (resolved.type === 'array') {
    const itemSchema = resolveRef(resolved.items, root)
    const rows = Array.isArray(value) ? value : []
    const minItems = resolved.minItems ?? 0
    const maxItems = resolved.maxItems ?? Infinity

    const blankRow = () =>
      Object.fromEntries(
        Object.entries(itemSchema.properties || {}).map(([k, s]) => {
          const rs = resolveRef(s, root)
          if (rs.enum) return [k, rs.enum[0]]
          if (rs.type === 'integer' || rs.type === 'number') return [k, 0]
          return [k, '']
        }),
      )

    return (
      <fieldset style={{ margin: '0.4rem 0' }}>
        <legend>{label}</legend>
        {rows.map((row, i) => (
          <div key={i} style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
            <SchemaForm
              schema={itemSchema}
              root={root}
              value={row}
              onChange={(nextRow) => {
                const next = rows.slice()
                next[i] = nextRow
                onChange(next)
              }}
            />
            {rows.length > minItems && (
              <button
                type="button"
                onClick={() => onChange(rows.filter((_, j) => j !== i))}
              >
                remove
              </button>
            )}
          </div>
        ))}
        {rows.length < maxItems && (
          <button type="button" onClick={() => onChange([...rows, blankRow()])}>
            add step
          </button>
        )}
      </fieldset>
    )
  }

  // String fallback
  return (
    <label style={{ display: 'block', margin: '0.3rem 0' }}>
      {label}:{' '}
      <input
        type="text"
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  )
}

export default function SchemaForm({ schema, root, value, onChange }) {
  const rootSchema = root || schema
  const properties = schema.properties || {}
  return (
    <div>
      {Object.entries(properties).map(([name, propSchema]) => (
        <Field
          key={name}
          name={name}
          schema={propSchema}
          root={rootSchema}
          value={value?.[name]}
          onChange={(fieldValue) => onChange({ ...value, [name]: fieldValue })}
        />
      ))}
    </div>
  )
}
```

- [ ] **Step 2: Verify it builds**

Run: `cd frontend && npm run build`
Expected: build succeeds (no syntax/import errors). (No test runner in `frontend/`; correctness is verified end-to-end in Task 10.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/SchemaForm.jsx
git commit -m "feat: add schema-driven editable-values form component"
```

---

### Task 10: Frontend storyboard review screen + wiring

Insert the review stage between "Choose visualizations" and "Results". The options screen's button now calls `POST /storyboard`; the review screen shows each scene with thumbnail, grounding, editable values, grade override, and per-scene controls; a bottom "Render approved" button calls `POST /render`.

**Files:**
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/vite.config.js`

**Interfaces:**
- Consumes: `SchemaForm` (Task 9); backend endpoints from Tasks 4–8.

- [ ] **Step 1: Add proxy routes**

In `frontend/vite.config.js`, add to the `proxy` object:

```js
      '/storyboard': 'http://localhost:8000',
      '/thumbnails': 'http://localhost:8000',
```

- [ ] **Step 2: Wire the storyboard state + handlers in `App.jsx`**

Add `import SchemaForm from './SchemaForm'` at the top. Add state near the others:

```jsx
  const [storyboard, setStoryboard] = useState(null)
  const [drafts, setDrafts] = useState({})       // scene_id -> edited params
  const [fieldErrors, setFieldErrors] = useState({})  // scene_id -> [{loc,msg}]
```

Replace `handleRender` (the options-screen action) with a handler that builds the storyboard:

```jsx
  async function handleBuildStoryboard() {
    if (!options || options.some((item) => !picks[item.candidate_id])) return
    setError(null)
    setLoading(true)
    try {
      const body = options.map((item) => ({
        candidate_id: item.candidate_id,
        template: picks[item.candidate_id],
      }))
      const resp = await fetch('/storyboard', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ picks: body }),
      })
      if (!resp.ok) throw new Error((await resp.json()).detail || 'Storyboard failed')
      const data = await resp.json()
      setStoryboard(data.scenes)
      setDrafts(Object.fromEntries(data.scenes.map((s) => [s.scene_id, s.params])))
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  function replaceScene(updated) {
    setStoryboard((prev) => prev.map((s) => (s.scene_id === updated.scene_id ? updated : s)))
    setDrafts((prev) => ({ ...prev, [updated.scene_id]: updated.params }))
  }

  async function sceneAction(sceneId, path, options) {
    setError(null)
    setLoading(true)
    try {
      const resp = await fetch(`/storyboard/${sceneId}${path}`, {
        credentials: 'include',
        ...options,
      })
      const data = await resp.json()
      if (resp.status === 422) {
        setFieldErrors((prev) => ({ ...prev, [sceneId]: data.detail.errors }))
        return
      }
      if (!resp.ok) throw new Error(data.detail || 'Action failed')
      setFieldErrors((prev) => ({ ...prev, [sceneId]: null }))
      replaceScene(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const saveEdits = (id) =>
    sceneAction(id, '', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ params: drafts[id] }),
    })
  const setGrade = (id, grade) =>
    sceneAction(id, '', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ grade_level: Number(grade) }),
    })
  const retryScene = (id) => sceneAction(id, '/retry', { method: 'POST' })
  const approveScene = (id) => sceneAction(id, '/approve', { method: 'POST' })
  const rejectScene = (id) => sceneAction(id, '/reject', { method: 'POST' })

  async function handleRender() {
    setError(null)
    setLoading(true)
    try {
      const resp = await fetch('/render', { method: 'POST', credentials: 'include' })
      if (!resp.ok) throw new Error((await resp.json()).detail || 'Render failed')
      setResults((await resp.json()).clips)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }
```

- [ ] **Step 3: Point the options button at the storyboard, gate Results on the storyboard**

In the options `<section>`, change the render button to:

```jsx
          <button onClick={handleBuildStoryboard} disabled={loading}>Review storyboard.</button>{' '}
```

Change the options section's render condition and the results section so the review screen sits between them. Update the options wrapper condition to `options && !storyboard && !results` and the results condition stays `results`.

- [ ] **Step 4: Add the review section**

Insert before the `{results && (...)}` block:

```jsx
      {storyboard && !results && (
        <section>
          <h2>Storyboard review</h2>
          {storyboard.map((scene) => (
            <div
              key={scene.scene_id}
              style={{
                border: '1px solid #ddd',
                borderRadius: 6,
                padding: '0.75rem',
                margin: '1rem 0',
                background:
                  scene.status === 'approved'
                    ? '#ecfdf5'
                    : scene.status === 'rejected'
                    ? '#fef2f2'
                    : 'white',
              }}
            >
              <strong>{scene.detected_summary}</strong>
              <div style={{ color: '#666', fontSize: '0.85rem', marginBottom: '0.5rem' }}>
                {scene.source_excerpt}
              </div>

              {scene.thumbnail_url ? (
                <img
                  src={scene.thumbnail_url}
                  alt="preview"
                  style={{ maxWidth: '100%', border: '1px solid #eee' }}
                />
              ) : (
                <div style={{ color: '#999' }}>Preview unavailable</div>
              )}

              {scene.fallback_reason && (
                <div style={{ color: '#b45309', fontSize: '0.85rem', margin: '0.5rem 0' }}>
                  Fallback: {scene.fallback_reason}
                </div>
              )}

              <div style={{ margin: '0.5rem 0' }}>
                <SchemaForm
                  schema={scene.params_schema}
                  value={drafts[scene.scene_id]}
                  onChange={(next) =>
                    setDrafts((prev) => ({ ...prev, [scene.scene_id]: next }))
                  }
                />
                {fieldErrors[scene.scene_id] && (
                  <ul style={{ color: 'crimson', fontSize: '0.85rem' }}>
                    {fieldErrors[scene.scene_id].map((e, i) => (
                      <li key={i}>{e.loc.join('.')}: {e.msg}</li>
                    ))}
                  </ul>
                )}
              </div>

              <label style={{ display: 'block', margin: '0.4rem 0' }}>
                Grade:{' '}
                <select
                  value={scene.grade_level}
                  disabled={loading}
                  onChange={(e) => setGrade(scene.scene_id, e.target.value)}
                >
                  {[0, 1, 2, 3, 4, 5, 6, 7, 8].map((g) => (
                    <option key={g} value={g}>{g}</option>
                  ))}
                </select>
                {scene.grade_overridden && ' (overridden)'}
              </label>

              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <button onClick={() => saveEdits(scene.scene_id)} disabled={loading}>Save edits</button>
                <button onClick={() => retryScene(scene.scene_id)} disabled={loading}>Retry</button>
                <button onClick={() => approveScene(scene.scene_id)} disabled={loading}>Approve</button>
                <button onClick={() => rejectScene(scene.scene_id)} disabled={loading}>Reject</button>
              </div>
            </div>
          ))}

          <button
            onClick={handleRender}
            disabled={loading || !storyboard.some((s) => s.status === 'approved')}
          >
            Render approved
          </button>
        </section>
      )}
```

- [ ] **Step 5: Verify build**

Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 6: Manual end-to-end verification**

Use the `/run` skill (or start backend `uvicorn app.main:app` in `backend/` + `npm run dev` in `frontend/`) against a known-good PPTX. Verify: upload → candidates → options → **Review storyboard** shows thumbnails + detected line + source excerpt; edit a value → Save → thumbnail updates; enter an invalid value → field error shown, thumbnail unchanged; change grade → "(overridden)"; Retry re-renders; Approve highlights the card; **Render approved** → Results with download links; a rejected scene is absent from Results.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/App.jsx frontend/vite.config.js
git commit -m "feat: add storyboard review screen and wire to backend"
```

---

## Self-Review

**Spec coverage:**
- New `/storyboard` step (extract + thumbnail, stored in session) → Tasks 2, 3, 4 ✓
- Editable values, re-validated (schema + guard), re-thumbnail → Tasks 5, 9 ✓
- Grade override → Task 5 (backend), Task 10 (UI) ✓
- Approve / reject → Task 7 (backend), Task 10 (UI) ✓
- Retry re-extracts same template → Task 6 ✓
- Full render of approved scenes from stored params, no re-extraction → Task 8 ✓
- Thumbnail serving → Tasks 2, 4 ✓
- Source-excerpt grounding + detected summary → Task 4 (`SceneOut`), Task 10 (UI) ✓
- Fallback scenes shown with reason; approvable → Tasks 1, 3, 7, 10 ✓
- Error/edge cases (unknown scene 404, no session 400, no approved 400, one render failure doesn't sink batch, thumbnail render failure) → Tasks 4–8 ✓
- Stated-answer check → **out of scope** per spec ✓ (no task, intentional)
- `httpx2` — verified already resolved, no task needed ✓

**Placeholder scan:** No TBD/TODO; every code step shows full code. ✓

**Type consistency:** `assemble_scene(candidate, output_dir, *, template, grade)` used identically in Tasks 3/4/6. `_scene_out(scene, candidate)` used in Tasks 4/5/6/7. `SceneOut` field names match between `_scene_out` and the frontend reads in Task 10 (`thumbnail_url`, `detected_summary`, `source_excerpt`, `params_schema`, `grade_overridden`, `status`, `fallback_reason`). `_field_errors` shape (`{errors:[{loc,msg}]}`) matches the frontend 422 read in Task 10. ✓

## Notes on decisions carried from the spec
- `process_scene` (the old one-shot extract+full-render) is left in place but is no longer called by routes after Task 8. Left intact to avoid touching any repo-root eval usage; safe to remove in a later cleanup if confirmed unused.
- Every re-render (edit/retry) registers a **new** thumbnail id, so the browser never serves a stale cached image; old ids age out of the LRU (separate `max_thumbnails` cap protects clips).
