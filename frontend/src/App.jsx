import { useEffect, useState } from 'react'
import MetaReviewPanel from './MetaReviewPanel'
import SchemaForm from './SchemaForm'
import TemplateWorkshop from './TemplateWorkshop'
import {
  IconAlert,
  IconBlocks,
  IconCard,
  IconCheck,
  IconChecked,
  IconCross,
  IconDownload,
  IconFilm,
  IconPending,
  IconRedo,
  IconSeedling,
  IconTray,
  IconWorking,
} from './Icons'

function sceneIsDirty(scene, drafts) {
  return JSON.stringify(drafts[scene.scene_id]) !== JSON.stringify(scene.params)
}

async function responseJson(resp, fallbackMessage) {
  try {
    return await resp.json()
  } catch {
    throw new Error(resp.ok ? 'Server returned an invalid response' : fallbackMessage)
  }
}

function responseError(data, fallbackMessage) {
  return typeof data?.detail === 'string' ? data.detail : fallbackMessage
}

// A candidate whose only offered visualization is the generic text card has no
// built-in template that fits it. Picking the text card here is exactly the
// signal the meta-template loop learns from: the backend records the problem as
// an "unsupported shape" observation, and once enough similar problems are seen
// it may propose a brand-new visualization template for this kind of problem.
// (Mirrors classify_text_card_reason == UNSUPPORTED_SHAPE: text_card picked with
// no structural option available.)
function isUnsupportedShape(item) {
  return (
    item.templates.length > 0
    && item.templates.every((option) => option.template === 'text_card')
  )
}

function templateLabel(template) {
  return template.replace(/_/g, ' ')
}

// Server validation errors arrive as Pydantic paths ("steps.0.amount"). A teacher
// reads "Steps 1 → Amount", not a dotted accessor.
function humanLoc(loc) {
  return loc
    .filter((part) => part !== 'params' && part !== 'body')
    .map((part) => (typeof part === 'number' ? String(part + 1) : part.replace(/_/g, ' ')))
    .join(' → ')
    .replace(/^./, (c) => c.toUpperCase())
}

function sceneIds(entry) {
  return entry.candidate_ids || [entry.candidate_id || entry.scene_id]
}

function formatElapsed(seconds) {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

// The rod law: colour belongs to the VALUE, 1 through 10, as a K-8 classroom
// already teaches it. Pale rods take dark numerals. Values outside 1-10 have no
// rod in the physical set, so they get none here either.
const ROD_DARK_INK = new Set([1, 3, 5, 10])

function rodFor(value) {
  if (!Number.isInteger(value) || value < 1 || value > 10) return null
  return { hue: `var(--rod-${value})`, ink: ROD_DARK_INK.has(value) ? 'dark' : 'light' }
}

// Collect the numbers this scene actually operates on, with a readable role for
// each, so the rods show real validated values rather than decoration.
function numericValues(params, role = '', depth = 0) {
  if (depth > 3 || params == null) return []
  if (typeof params === 'number') return [{ role, value: params }]
  if (Array.isArray(params)) {
    return params.flatMap((item, i) => numericValues(item, `${role} ${i + 1}`.trim(), depth + 1))
  }
  if (typeof params === 'object') {
    return Object.entries(params).flatMap(([key, value]) =>
      numericValues(value, key === 'items' || key === 'steps' ? role : key.replace(/_/g, ' '), depth + 1))
  }
  return []
}

function Rods({ params }) {
  const values = numericValues(params).filter((entry) => rodFor(entry.value)).slice(0, 5)
  if (values.length === 0) return null
  return (
    <>
      <p className="rods__caption">Validated values, on the rod scale</p>
      <ul className="rods">
        {values.map((entry, i) => {
          const rod = rodFor(entry.value)
          return (
            <li className="rod" key={`${entry.role}-${i}`}>
              <span
                className="rod__bar"
                data-ink={rod.ink}
                style={{ background: rod.hue, width: `${entry.value * 9}%` }}
              >
                {entry.value}
              </span>
              <span className="rod__role">
                {entry.role.replace(/^./, (c) => c.toUpperCase())}
              </span>
            </li>
          )
        })}
      </ul>
    </>
  )
}

// Decorative only — the playful layer sits behind content and never competes
// with a validated number.
function Decor() {
  return (
    <div className="decor" aria-hidden="true">
      <svg className="decor__blob-a" viewBox="0 0 200 200" fill="currentColor">
        <path d="M43 12c30-14 71-9 96 13s33 62 20 93-47 54-80 57-64-14-73-45 7-104 37-118z" />
      </svg>
      <svg className="decor__blob-b" viewBox="0 0 200 200" fill="currentColor">
        <path d="M52 20c34-19 84-13 111 17s26 79 4 110-63 44-99 33S6 145 8 108 18 39 52 20z" />
      </svg>
      {/* A marker stroke, so the width varies with pressure the way a hand does. */}
      <svg className="decor__squiggle" viewBox="0 0 200 44" fill="currentColor">
        <path d="M3 30c13-21 27-22 41-3 3 4 5 6 8 6 6 0 11-6 16-13 6-8 13-13 20-9 5 3 8 8 11 12 3 4 6 6 9 5 5-1 9-7 14-13 6-7 13-11 20-7 6 3 9 9 13 13 3 3 6 4 9 2l6-4 3 6-7 5c-6 4-12 2-16-3-4-4-7-10-11-12-4-2-8 1-12 6-6 7-11 14-19 15-7 1-12-5-15-10-3-4-5-8-8-9-3-1-7 3-12 10-6 8-12 15-20 15-6 0-10-4-13-8-11-15-20-15-30 1l-4 6z" />
      </svg>
    </div>
  )
}

const STAGES = [
  { key: 'upload', name: 'Upload deck' },
  { key: 'problems', name: 'Pick problems' },
  { key: 'visuals', name: 'Pick visuals' },
  { key: 'storyboard', name: 'Check values' },
  { key: 'clips', name: 'Get clips' },
]

function StageRail({ current }) {
  const currentIndex = STAGES.findIndex((stage) => stage.key === current)
  return (
    <ol className="rail">
      {STAGES.map((stage, index) => {
        const state = index < currentIndex ? 'done' : index === currentIndex ? 'active' : 'todo'
        return (
          <li
            key={stage.key}
            className="rail__step"
            data-state={state}
            aria-current={state === 'active' ? 'step' : undefined}
          >
            <span className="rail__index">
              {state === 'done' ? <IconCheck size={16} /> : index + 1}
              <span className="sr-only">
                {`Step ${index + 1} — `}
                {state === 'done' ? 'done' : state === 'active' ? 'current step' : 'not started'}
              </span>
            </span>
            <span className="rail__name">{stage.name}</span>
          </li>
        )
      })}
    </ol>
  )
}

const STAMP_STATE_WORDS = {
  done: 'done',
  active: 'in progress',
  failed: 'failed',
  todo: 'not started',
}

function Stamp({ label, state }) {
  const mark =
    state === 'done' ? <IconCheck size={16} />
      : state === 'active' ? <IconWorking size={16} />
      : state === 'failed' ? <IconAlert size={16} />
      : <IconPending size={16} />
  return (
    <li className="stamp" data-state={state}>
      <span className="stamp__mark">{mark}</span>
      {label}
      {/* The icons are decorative, so the state is carried in text too. */}
      <span className="sr-only"> — {STAMP_STATE_WORDS[state]}</span>
    </li>
  )
}

// Discrete, countable stages, every one read from real scene state and every one
// reachable. There is no percentage to show: POST /render is a single blocking
// batch call with no progress stream, so the render itself is reported by the
// dock rather than faked as a per-scene bar here.
function StampColumn({ scene, hasErrors, draft }) {
  const extracted = draft != null && Object.keys(draft).length > 0
  const rejected = scene.status === 'rejected'
  const stamps = [
    { label: 'Values extracted', state: extracted ? 'done' : 'todo' },
    {
      label: 'Validated in Python',
      state: hasErrors ? 'failed' : extracted ? 'done' : 'todo',
    },
    { label: 'Preview rendered', state: scene.thumbnail_url ? 'done' : 'todo' },
    {
      label: rejected ? 'Rejected — will not render' : 'Approved for render',
      state: rejected ? 'failed' : scene.status === 'approved' ? 'done' : 'todo',
    },
  ]
  const done = stamps.filter((stamp) => stamp.state === 'done').length
  return (
    <div>
      <p className="stamps__count">{done} of {stamps.length} stages complete</p>
      <ul className="stamps">
        {stamps.map((stamp) => (
          <Stamp key={stamp.label} label={stamp.label} state={stamp.state} />
        ))}
      </ul>
    </div>
  )
}

function RenderDock({ scenes, results, rendering, elapsed, onDismiss }) {
  const templateFor = (ids) =>
    scenes.find((scene) => sceneIds(scene).join(', ') === ids)?.template

  const rows = results
    ? results.map((result) => {
      const ids = sceneIds(result).join(', ')
      const template = templateFor(ids)
      return {
        ids,
        label: template ? `${templateLabel(template)} · ${ids}` : ids,
        state: result.status === 'error' ? 'failed' : 'done',
        note: result.status === 'fallback' ? 'text card' : null,
      }
    })
    : scenes.map((scene) => {
      const ids = sceneIds(scene).join(', ')
      return {
        ids,
        label: `${templateLabel(scene.template)} · ${ids}`,
        state: 'working',
        note: null,
      }
    })

  const stateWord = { working: 'rendering', failed: 'failed', done: 'finished' }

  return (
    <aside className="dock" aria-label="Render progress">
      <div className="dock__inner">
        <div className="dock__head">
          {rendering ? <IconWorking /> : <IconCheck />}
          {/* Only the heading and rows announce. The clock is excluded: it
              mutates every second and would talk over everything else. */}
          <h2 className="dock__title" aria-live="polite">
            {rendering ? 'Rendering' : 'Render finished'}
          </h2>
          {rendering && (
            <span className="dock__elapsed" aria-hidden="true">{formatElapsed(elapsed)}</span>
          )}
          {!rendering && (
            <button type="button" className="btn btn--quiet btn--tiny" onClick={onDismiss}>
              Hide
            </button>
          )}
        </div>
        <div className="dock__rows">
          {rows.map((row) => (
            <div className="dock__row" key={row.ids}>
              <span className="stamp__mark">
                {row.state === 'working' ? <IconWorking size={16} />
                  : row.state === 'failed' ? <IconAlert size={16} />
                  : <IconCheck size={16} />}
              </span>
              <span className="dock__row-name">{row.label}</span>
              <span className="sr-only">{stateWord[row.state]}</span>
              {row.note && <span className="clip__ids">{row.note}</span>}
            </div>
          ))}
        </div>
        {rendering && (
          <p className="dock__note">
            Manim renders every approved scene in one pass. This takes minutes,
            not seconds — you can leave this open.
          </p>
        )}
      </div>
    </aside>
  )
}

function MainApp() {
  const [candidates, setCandidates] = useState(null)
  const [selected, setSelected] = useState({})
  const [options, setOptions] = useState(null)
  const [picks, setPicks] = useState({})
  const [results, setResults] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [storyboard, setStoryboard] = useState(null)
  const [drafts, setDrafts] = useState({})       // scene_id -> edited params
  const [fieldErrors, setFieldErrors] = useState({})  // scene_id -> [{loc,msg}]
  const [chainSelected, setChainSelected] = useState({})  // scene_id -> bool, combine checkboxes
  const [fileName, setFileName] = useState(null)
  const [rendering, setRendering] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [dockHidden, setDockHidden] = useState(false)
  const [batchFailure, setBatchFailure] = useState(null)

  useEffect(() => {
    if (!rendering) return undefined
    const timer = setInterval(() => setElapsed((value) => value + 1), 1000)
    return () => clearInterval(timer)
  }, [rendering])

  async function handleUpload(event) {
    event.preventDefault()
    const file = event.target.file.files[0]
    if (!file) return
    setError(null)
    setBatchFailure(null)
    setLoading(true)
    setOptions(null)
    setPicks({})
    setResults(null)
    setStoryboard(null)
    setDrafts({})
    setFieldErrors({})
    setChainSelected({})
    const form = new FormData()
    form.append('file', file)
    try {
      const resp = await fetch('/upload', {
        method: 'POST',
        body: form,
        credentials: 'include',
      })
      const data = await responseJson(resp, 'Upload failed')
      if (!resp.ok) throw new Error(responseError(data, 'Upload failed'))
      setCandidates(data.candidates)
      setSelected({})
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  function toggle(id) {
    setSelected((previous) => ({ ...previous, [id]: !previous[id] }))
  }

  async function handleGetOptions() {
    const candidateIds = Object.keys(selected).filter((id) => selected[id])
    if (candidateIds.length === 0) return
    setError(null)
    setLoading(true)
    try {
      const resp = await fetch('/options', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ candidate_ids: candidateIds }),
      })
      const data = await responseJson(resp, 'Could not get options')
      if (!resp.ok) throw new Error(responseError(data, 'Could not get options'))
      const initialPicks = Object.fromEntries(
        data.options
          .filter((item) => item.templates.length > 0)
          .map((item) => [item.candidate_id, item.templates[0].template]),
      )
      setOptions(data.options)
      setPicks(initialPicks)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleBuildStoryboard() {
    if (!options || options.some((item) => !picks[item.candidate_id])) return
    setError(null)
    // A previous batch's failure belongs to a storyboard that no longer exists.
    setBatchFailure(null)
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
      const data = await responseJson(resp, 'Storyboard failed')
      if (!resp.ok) throw new Error(responseError(data, 'Storyboard failed'))
      setStoryboard(data.scenes)
      setDrafts(Object.fromEntries(data.scenes.map((s) => [s.scene_id, s.params])))
      setChainSelected({})
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  function replaceScene(updated, { resetDraft = false } = {}) {
    setStoryboard((prev) => prev.map((s) => (s.scene_id === updated.scene_id ? updated : s)))
    if (resetDraft) {
      setDrafts((prev) => ({ ...prev, [updated.scene_id]: updated.params }))
    }
  }

  async function sceneAction(sceneId, path, options, { resetDraft = false } = {}) {
    setError(null)
    setLoading(true)
    try {
      const resp = await fetch(`/storyboard/${sceneId}${path}`, {
        credentials: 'include',
        ...options,
      })
      const data = await responseJson(resp, 'Action failed')
      if (resp.status === 422) {
        const errors = Array.isArray(data?.detail?.errors) ? data.detail.errors : []
        if (errors.length === 0) {
          throw new Error(responseError(data, 'Could not save edits'))
        }
        setFieldErrors((prev) => ({ ...prev, [sceneId]: errors }))
        return
      }
      if (!resp.ok) throw new Error(responseError(data, 'Action failed'))
      setFieldErrors((prev) => ({ ...prev, [sceneId]: null }))
      replaceScene(data, { resetDraft })
      if (data.status !== 'pending_review' || data.candidate_ids) {
        setChainSelected((prev) => ({ ...prev, [sceneId]: false }))
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const saveEdits = (id) =>
    sceneAction(
      id,
      '',
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ params: drafts[id] }),
      },
      { resetDraft: true },
    )
  const setGrade = (id, grade) =>
    sceneAction(id, '', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ grade_level: Number(grade) }),
    })
  const retryScene = (id) => sceneAction(id, '/retry', { method: 'POST' }, { resetDraft: true })
  const approveScene = (id) => sceneAction(id, '/approve', { method: 'POST' })
  const rejectScene = (id) => sceneAction(id, '/reject', { method: 'POST' })

  function toggleChainSelect(sceneId) {
    setChainSelected((previous) => ({ ...previous, [sceneId]: !previous[sceneId] }))
  }

  const checkedSceneIds = storyboard
    ? storyboard.filter((s) => chainSelected[s.scene_id]).map((s) => s.scene_id)
    : []
  const checkedScenes = storyboard ? storyboard.filter((s) => chainSelected[s.scene_id]) : []
  const canCombine =
    checkedScenes.length >= 2 &&
    checkedScenes.length <= 4 &&
    checkedScenes.every(
      (s) =>
        s.status === 'pending_review' &&
        !!s.candidate_id &&
        !s.candidate_ids &&
        !sceneIsDirty(s, drafts) &&
        s.template === checkedScenes[0]?.template,
    )

  async function handleCombineScenes() {
    if (!canCombine) return
    setError(null)
    setLoading(true)
    try {
      const resp = await fetch('/storyboard/chain', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ scene_ids: checkedSceneIds }),
      })
      const data = await responseJson(resp, 'Could not combine scenes')
      if (!resp.ok) throw new Error(responseError(data, 'Could not combine scenes'))
      setStoryboard((prev) => {
        const firstIndex = Math.min(
          ...checkedSceneIds.map((id) => prev.findIndex((s) => s.scene_id === id)),
        )
        const next = prev.filter((s) => !checkedSceneIds.includes(s.scene_id))
        next.splice(firstIndex, 0, data)
        return next
      })
      setDrafts((prev) => {
        const next = { ...prev }
        for (const id of checkedSceneIds) delete next[id]
        next[data.scene_id] = data.params
        return next
      })
      setFieldErrors((prev) => {
        const next = { ...prev }
        for (const id of checkedSceneIds) delete next[id]
        next[data.scene_id] = null
        return next
      })
      setChainSelected({})
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleUngroupScene(sceneId) {
    setError(null)
    setLoading(true)
    try {
      const resp = await fetch(`/storyboard/${sceneId}/ungroup`, {
        method: 'POST',
        credentials: 'include',
      })
      const data = await responseJson(resp, 'Could not ungroup scene')
      if (!resp.ok) throw new Error(responseError(data, 'Could not ungroup scene'))
      setStoryboard((prev) => {
        const index = prev.findIndex((s) => s.scene_id === sceneId)
        const next = prev.filter((s) => s.scene_id !== sceneId)
        next.splice(index, 0, ...data.scenes)
        return next
      })
      setDrafts((prev) => {
        const next = { ...prev }
        delete next[sceneId]
        for (const scene of data.scenes) next[scene.scene_id] = scene.params
        return next
      })
      setFieldErrors((prev) => {
        const next = { ...prev }
        delete next[sceneId]
        for (const scene of data.scenes) next[scene.scene_id] = null
        return next
      })
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleRender() {
    if (storyboard?.some((scene) => scene.status === 'approved' && sceneIsDirty(scene, drafts))) {
      setError('Save all edits before rendering approved scenes')
      return
    }
    setError(null)
    setBatchFailure(null)
    setLoading(true)
    setRendering(true)
    setElapsed(0)
    setDockHidden(false)
    try {
      const resp = await fetch('/render', { method: 'POST', credentials: 'include' })
      const data = await responseJson(resp, 'Render failed')
      if (!resp.ok) throw new Error(responseError(data, 'Render failed'))
      setResults(data.clips)
    } catch (err) {
      // The whole batch failed — a Manim error or RENDER_TIMEOUT_SECONDS. This
      // is the likeliest failure, so it gets the designed recovery state rather
      // than a banner: approvals and edits are all still in memory.
      setBatchFailure(err.message)
    } finally {
      setLoading(false)
      setRendering(false)
    }
  }

  const stage = results ? 'clips'
    : storyboard ? 'storyboard'
    : options ? 'visuals'
    : candidates ? 'problems'
    : 'upload'

  const approvedScenes = storyboard
    ? storyboard.filter((scene) => scene.status === 'approved')
    : []
  const showDock = !dockHidden && (rendering || !!results)
  // Problems whose only offered visualization is the generic text card: the
  // exact set the meta-template loop can build something new for.
  const unsupportedCandidateIds = (options || [])
    .filter(isUnsupportedShape)
    .map((item) => item.candidate_id)

  return (
    <div className="shell">
      <Decor />

      <header className="masthead">
        <div className="masthead__inner">
          <h1>Math Animation Generator</h1>
          <p className="masthead__sub">
            Upload the deck you already wrote. Every number in every clip is
            recomputed and checked in Python before it reaches a slide.
          </p>
        </div>
      </header>

      <main className={`page${showDock ? ' page--docked' : ''}`}>
        <StageRail current={stage} />

        {error && (
          <div className="notice notice--danger" role="alert">
            <IconAlert />
            <p className="notice__body">{error}</p>
          </div>
        )}

        {/* One stable form and one stable file input across every stage: the
            uploader collapses to a strip once a deck is in, but never remounts. */}
        <section className="band">
          <div className="band__head">
            <h2>{candidates ? 'Deck' : 'Upload a deck'}</h2>
            <p className="band__note">
              {candidates
                ? 'Uploading a different deck clears everything below.'
                : 'PPTX only, up to 50 slides and 50 MB.'}
            </p>
          </div>
          <form onSubmit={handleUpload}>
            {/* Always visually hidden: the platform's own file widget never
                appears in a committed world. The label is the control. */}
            <input
              id="deck-file"
              className="drop__input"
              type="file"
              name="file"
              accept=".pptx"
              aria-label={candidates ? 'Choose a different PPTX' : 'Choose a PPTX'}
              onChange={(event) => setFileName(event.target.files[0]?.name ?? null)}
            />
            {candidates ? (
              <div className="reload-strip">
                <label htmlFor="deck-file" className="btn btn--quiet">
                  Choose a different PPTX
                </label>
                <span className="reload-strip__name">{fileName || 'Deck loaded'}</span>
                <button type="submit" className="btn" disabled={loading}>
                  Upload
                </button>
                {loading && <span className="dirty-flag">Working…</span>}
              </div>
            ) : (
              <div className="upload-grid">
                <div>
                  <label className="drop" htmlFor="deck-file">
                    <span className="drop__icon"><IconTray /></span>
                    <span className="drop__title">Choose a PPTX</span>
                    <span className="drop__hint">
                      Text-based slides only — problems that exist solely as
                      pictures are not detected.
                    </span>
                    {fileName && <span className="drop__file">{fileName}</span>}
                  </label>
                  <div className="actions">
                    <button type="submit" className="btn btn--primary" disabled={loading}>
                      Upload
                    </button>
                    {loading && <span className="dirty-flag">Working…</span>}
                  </div>
                </div>

                <dl className="facts">
                  <div className="fact">
                    <span className="fact__icon"><IconBlocks /></span>
                    <div>
                      <dt>Templates are hand-authored</dt>
                      <dd>
                        Every animation comes from a template a person built and
                        tested. Nothing is generated at render time.
                      </dd>
                    </div>
                  </div>
                  <div className="fact">
                    <span className="fact__icon"><IconChecked /></span>
                    <div>
                      <dt>Python checks the arithmetic</dt>
                      <dd>
                        The model finds problems and pulls out values. It never
                        computes them — totals and equalities are recomputed here.
                      </dd>
                    </div>
                  </div>
                  <div className="fact">
                    <span className="fact__icon"><IconFilm /></span>
                    <div>
                      <dt>One MP4 per scene</dt>
                      <dd>
                        You download each clip and insert it yourself. Nothing is
                        saved once you close the tab.
                      </dd>
                    </div>
                  </div>
                </dl>
              </div>
            )}
          </form>
        </section>

        {candidates && candidates.length === 0 && (
          <div className="notice notice--empty">
            <IconCard />
            <p className="notice__body">
              No solvable problems found in this document. Slides with concept
              explanations, vocabulary, or &quot;color/identify&quot; prompts
              aren&apos;t flagged unless they state a concrete problem with
              numbers to work out.
            </p>
          </div>
        )}

        {candidates && candidates.length > 0 && !options && !results && (
          <section className="band">
            <div className="band__head">
              <h2>Problems found in your deck</h2>
              <p className="band__note">
                Tick the ones worth animating. Each shows the slide text it came from.
              </p>
            </div>
            <div className="picklist">
              {candidates.map((candidate) => (
                <label className="pick" key={candidate.candidate_id}>
                  <input
                    type="checkbox"
                    checked={!!selected[candidate.candidate_id]}
                    disabled={loading}
                    onChange={() => toggle(candidate.candidate_id)}
                  />
                  <span>
                    <span className="pick__summary">{candidate.one_line_summary}</span>
                    <span className="pick__source">
                      <span className="slide-tag">slide {candidate.slide_index}</span>
                      {candidate.source_excerpt}
                    </span>
                  </span>
                </label>
              ))}
            </div>
            <button className="btn btn--primary" onClick={handleGetOptions} disabled={loading}>
              Get visualizations
            </button>
          </section>
        )}

        {/* Sits above the current stage's band and stays there as the teacher
            moves on: a build takes minutes and must not hold up the deck, so
            this is gated on having a deck rather than on the current stage.
            Nothing here resets the flow on approval — the band says to ask for
            visualizations again, and "Back to candidates" already exists. */}
        {candidates && candidates.length > 0 && (
          <TemplateWorkshop
            candidates={candidates}
            unsupportedCandidateIds={unsupportedCandidateIds}
          />
        )}

        {options && !storyboard && !results && (
          <section className="band">
            <div className="band__head">
              <h2>Choose visualizations</h2>
              <p className="band__note">
                Ranked by how well each template fits the problem's structure.
              </p>
            </div>
            {options.map((item) => {
              const candidate = candidates.find(
                (entry) => entry.candidate_id === item.candidate_id,
              )
              return (
                <fieldset className="option-set" key={item.candidate_id} disabled={loading}>
                  <legend>{candidate?.one_line_summary || item.candidate_id}</legend>
                  {isUnsupportedShape(item) && (
                    <div className="notice notice--teach">
                      <IconSeedling />
                      <p className="notice__body">
                        No built-in visualization fits this problem yet, so it falls back
                        to a plain text card. You can have one built from this problem —
                        see &quot;Teaching a new visual&quot; above.
                      </p>
                    </div>
                  )}
                  <div className="picklist">
                    {item.templates.map((option) => (
                      <label className="pick" key={option.template}>
                        <input
                          type="radio"
                          name={`visualization-${item.candidate_id}`}
                          value={option.template}
                          checked={picks[item.candidate_id] === option.template}
                          onChange={() => setPicks((previous) => ({
                            ...previous,
                            [item.candidate_id]: option.template,
                          }))}
                        />
                        <span>
                          <span className="chip" data-template={option.template}>
                            {templateLabel(option.template)}
                          </span>
                          <span className="option__rationale">{option.rationale}</span>
                        </span>
                      </label>
                    ))}
                  </div>
                </fieldset>
              )
            })}
            <div className="actions">
              <button className="btn btn--primary" onClick={handleBuildStoryboard} disabled={loading}>
                Build storyboard
              </button>
              <button
                className="btn btn--quiet"
                onClick={() => {
                  setOptions(null)
                  setPicks({})
                  setError(null)
                }}
                disabled={loading}
              >
                Back to candidates
              </button>
            </div>
          </section>
        )}

        {storyboard && !results && (
          <section className="band">
            <div className="band__head">
              <h2>Storyboard review</h2>
              <p className="band__note">
                Fix any wrong value here. Every edit is re-checked in Python before
                a scene can be approved.
              </p>
            </div>

            {batchFailure && (
              <div className="notice notice--danger" role="alert">
                <IconAlert />
                <div>
                  <p className="notice__body">
                    {/* Don't stutter when the server's message is already generic. */}
                    {/^render failed\.?$/i.test(batchFailure.trim())
                      ? 'The render did not finish.'
                      : `The render did not finish: ${batchFailure}`}
                  </p>
                  <p className="notice__body">
                    Manim either errored or ran past its timeout. Nothing was lost —
                    your approvals and edited values are still below. Retry a scene
                    whose values look wrong, then render again.
                  </p>
                  <div className="actions">
                    <button
                      className="btn btn--primary"
                      onClick={handleRender}
                      disabled={loading}
                    >
                      <IconRedo size={16} />
                      Render approved again
                    </button>
                    <button
                      className="btn btn--quiet"
                      onClick={() => setBatchFailure(null)}
                      disabled={loading}
                    >
                      Dismiss
                    </button>
                  </div>
                </div>
              </div>
            )}

            {canCombine && (
              <div className="actions" style={{ marginTop: 0, marginBottom: '1rem' }}>
                <button className="btn" onClick={handleCombineScenes} disabled={loading}>
                  Combine {checkedScenes.length} into one scene
                </button>
              </div>
            )}

            {storyboard.map((scene) => {
              const isDirty = sceneIsDirty(scene, drafts)
              const isChain = !!scene.candidate_ids
              const combinable =
                scene.status === 'pending_review' && !!scene.candidate_id && !isChain
              const errors = fieldErrors[scene.scene_id]
              return (
                <article className="scene" key={scene.scene_id} data-status={scene.status}>
                  {combinable && (
                    <label className="combine">
                      <input
                        type="checkbox"
                        checked={!!chainSelected[scene.scene_id]}
                        disabled={loading}
                        onChange={() => toggleChainSelect(scene.scene_id)}
                      />
                      Combine with other selected scenes
                    </label>
                  )}

                  <h3 className="scene__title">{scene.detected_summary}</h3>

                  <div className="scene__meta">
                    <span className="chip" data-template={scene.template}>
                      {templateLabel(scene.template)}
                    </span>
                    {isChain && (
                      <span className="clip__ids">
                        combined: {scene.candidate_ids.join(', ')}
                      </span>
                    )}
                  </div>

                  <p className="scene__source">{scene.source_excerpt}</p>

                  {scene.fallback_reason && (
                    <div className="notice notice--fallback">
                      <IconCard />
                      <p className="notice__body">
                        Fallback: {scene.fallback_reason}
                      </p>
                    </div>
                  )}

                  <div className="scene__grid">
                    <div>
                      <div className="inset">
                        {scene.thumbnail_url ? (
                          <img
                            src={scene.thumbnail_url}
                            alt={`First frame of the ${templateLabel(scene.template)} animation for ${scene.detected_summary || 'this scene'}`}
                          />
                        ) : (
                          <div className="inset__empty">
                            {scene.template === 'text_card'
                              ? 'Renders as a labeled text card'
                              : 'Preview unavailable'}
                          </div>
                        )}
                      </div>
                      <StampColumn
                        scene={scene}
                        hasErrors={!!errors}
                        draft={drafts[scene.scene_id]}
                      />
                      <Rods params={drafts[scene.scene_id]} />
                    </div>

                    <div>
                      <SchemaForm
                        schema={scene.params_schema}
                        value={drafts[scene.scene_id]}
                        disabled={loading}
                        onChange={(next) =>
                          setDrafts((prev) => ({ ...prev, [scene.scene_id]: next }))
                        }
                      />
                      {errors && (
                        <div className="errors">
                          <p className="errors__lead">
                            Fix these values, then save again — nothing renders until
                            they pass.
                          </p>
                          <ul className="errors__list">
                            {errors.map((e, i) => (
                              <li key={i}>{humanLoc(e.loc)}: {e.msg}</li>
                            ))}
                          </ul>
                        </div>
                      )}

                      <label className="grade">
                        Grade
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
                    </div>
                  </div>

                  <div className="actions">
                    <button className="btn" onClick={() => saveEdits(scene.scene_id)} disabled={loading}>
                      Save edits
                    </button>
                    {isChain ? (
                      <button className="btn" onClick={() => handleUngroupScene(scene.scene_id)} disabled={loading}>
                        Ungroup
                      </button>
                    ) : (
                      <button className="btn" onClick={() => retryScene(scene.scene_id)} disabled={loading}>
                        <IconRedo size={16} />
                        Retry
                      </button>
                    )}
                    <button
                      className="btn btn--ok"
                      onClick={() => approveScene(scene.scene_id)}
                      disabled={loading || isDirty}
                      title={isDirty ? 'Save edits before approving' : undefined}
                    >
                      <IconCheck size={16} />
                      Approve
                    </button>
                    <button className="btn btn--danger" onClick={() => rejectScene(scene.scene_id)} disabled={loading}>
                      <IconCross size={16} />
                      Reject
                    </button>
                    {isDirty && (
                      <span className="dirty-flag">Unsaved edits — Save first</span>
                    )}
                  </div>
                </article>
              )
            })}

            <button
              className="btn btn--primary"
              onClick={handleRender}
              disabled={
                loading
                || !storyboard.some((scene) => scene.status === 'approved')
                || storyboard.some(
                  (scene) => scene.status === 'approved' && sceneIsDirty(scene, drafts),
                )
              }
            >
              Render approved
            </button>
          </section>
        )}

        {results && (
          <section className="band">
            <div className="band__head">
              <h2>Results</h2>
              <p className="band__note">
                Download each clip and insert it into your own slideshow with
                Insert &gt; Video. Nothing is saved once you close this tab.
              </p>
            </div>
            <div className="clips">
              {results.map((result) => {
                const ids = sceneIds(result)
                return (
                  <article className="clip" key={result.scene_id || result.candidate_id}>
                    {result.status === 'error' ? (
                      <>
                        <div className="notice notice--danger" role="alert">
                          <IconAlert />
                          <p className="notice__body">
                            Render failed for {ids.join(', ')}
                          </p>
                        </div>
                        <p className="clip__ids">
                          {result.fallback_reason
                            || 'Manim either errored or ran past the render timeout. Your approvals and edits are still here.'}
                        </p>
                      </>
                    ) : result.clip_url ? (
                      <>
                        <div className="inset">
                          <video
                            aria-label={`Rendered clip ${ids.join(', ')}`}
                            src={result.clip_url}
                            controls
                            preload="metadata"
                          >
                            Your browser does not support HTML video playback.
                          </video>
                        </div>
                        <a className="download" href={result.clip_url} download>
                          <IconDownload size={16} />
                          Download clip ({ids.join(', ')})
                        </a>
                      </>
                    ) : (
                      <p className="clip__title">Clip {ids.join(', ')}</p>
                    )}
                    {result.status === 'fallback' && (
                      <div className="notice notice--fallback">
                        <IconCard />
                        <p className="notice__body">
                          Fallback: {result.fallback_reason}
                        </p>
                      </div>
                    )}
                  </article>
                )
              })}
            </div>
            <div className="actions">
              {results.some((result) => result.status === 'error') && (
                <button
                  className="btn"
                  onClick={() => {
                    setResults(null)
                    setDockHidden(true)
                    setError(null)
                  }}
                >
                  <IconRedo size={16} />
                  Back to storyboard review
                </button>
              )}
              <button
                className="btn btn--quiet"
                onClick={() => {
                  setResults(null)
                  setStoryboard(null)
                  setDrafts({})
                  setFieldErrors({})
                  setChainSelected({})
                  setError(null)
                }}
              >
                Back to options
              </button>
            </div>
          </section>
        )}
      </main>

      {showDock && (
        <RenderDock
          scenes={approvedScenes}
          results={results}
          rendering={rendering}
          elapsed={elapsed}
          onDismiss={() => setDockHidden(true)}
        />
      )}
    </div>
  )
}

export default function App() {
  const params = typeof window !== 'undefined' ? new URLSearchParams(window.location.search) : null
  if (params?.has('meta-review')) {
    return <MetaReviewPanel />
  }
  return <MainApp />
}
