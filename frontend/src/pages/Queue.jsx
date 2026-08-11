import { useContext } from 'react'
import { Link } from 'react-router-dom'
import { DemoContext } from './DemoShell'
import { templateLabel } from '../lib/templates'

function pillFor(status) {
  switch (status) {
    case 'pending_review':
      return 'warn'
    case 'approved':
    case 'rendered':
      return 'ok'
    case 'render_failed':
      return 'danger'
    case 'rejected':
    case 'fallback':
      return 'muted'
    default:
      return 'muted'
  }
}

function statusLabel(status) {
  switch (status) {
    case 'pending_review':
      return 'needs review'
    case 'approved':
      return 'approved'
    case 'rendered':
      return 'rendered'
    case 'render_failed':
      return 'render failed'
    case 'rejected':
      return 'rejected'
    case 'fallback':
      return 'text card'
    default:
      return status
  }
}

export default function Queue() {
  const {
    candidates,
    selected,
    toggle,
    options,
    picks,
    setPicks,
    storyboard,
    loading,
    error,
    handleUpload,
    handleGetOptions,
    handleBuildStoryboard,
    approveScene,
    setPendingRenders,
  } = useContext(DemoContext)

  if (!candidates) {
    return (
      <form onSubmit={handleUpload} className="upload">
        <label htmlFor="deck-file" className="upload__label">Upload a PPTX</label>
        <input id="deck-file" type="file" name="file" accept=".pptx" aria-label="Upload a PPTX" />
        <button type="submit" className="btn btn--primary" disabled={loading}>Upload</button>
        {loading && <span className="upload__working">Working…</span>}
        {error && <p role="alert" className="upload__error">{error}</p>}
      </form>
    )
  }

  if (!options) {
    if (candidates.length === 0) {
      return <p>No solvable problems found in this deck.</p>
    }
    return (
      <section className="band">
        <h2>Problems found in your deck</h2>
        <p className="band__note">Tick the ones worth animating.</p>
        <ul className="picklist">
          {candidates.map((c) => (
            <li key={c.candidate_id}>
              <label className="pick">
                <input
                  type="checkbox"
                  checked={!!selected[c.candidate_id]}
                  onChange={() => toggle(c.candidate_id)}
                  disabled={loading}
                />
                <span>
                  <span className="pick__summary">{c.one_line_summary}</span>
                  <span className="pick__source">slide {c.slide_index} · {c.source_excerpt}</span>
                </span>
              </label>
            </li>
          ))}
        </ul>
        <button className="btn btn--primary" onClick={handleGetOptions} disabled={loading}>
          Pick visualizations
        </button>
        {error && <p role="alert" className="upload__error">{error}</p>}
      </section>
    )
  }

  if (!storyboard) {
    return (
      <section className="band">
        <h2>Choose visualizations</h2>
        {options.map((item) => (
          <fieldset key={item.candidate_id} className="option-set" disabled={loading}>
            <legend>
              {candidates.find((c) => c.candidate_id === item.candidate_id)?.one_line_summary
                || item.candidate_id}
            </legend>
            {item.templates.map((t) => (
              <label key={t.template} className="pick">
                <input
                  type="radio"
                  name={`v-${item.candidate_id}`}
                  value={t.template}
                  checked={picks[item.candidate_id] === t.template}
                  onChange={() => setPicks((prev) => ({ ...prev, [item.candidate_id]: t.template }))}
                />
                <span>{templateLabel(t.template)}</span>
              </label>
            ))}
          </fieldset>
        ))}
        <button className="btn btn--primary" onClick={handleBuildStoryboard} disabled={loading}>
          Build storyboard
        </button>
        {error && <p role="alert" className="upload__error">{error}</p>}
      </section>
    )
  }

  const readyScenes = storyboard.filter((scene) => scene.status === 'pending_review')
  const readyCount = readyScenes.length

  async function renderAllReady() {
    await Promise.all(readyScenes.map((scene) => approveScene(scene.scene_id)))
    setPendingRenders((prev) => {
      const next = new Set(prev)
      for (const scene of readyScenes) next.add(scene.scene_id)
      return next
    })
  }

  return (
    <section className="band">
      <h2>Problems in your storyboard</h2>
      <ul className="qlist">
        {storyboard.map((scene) => (
          <li key={scene.scene_id}>
            <Link to={`/demo/problem/${scene.scene_id}`} className="qrow" data-status={scene.status}>
              <div className="qrow__title">{scene.detected_summary}</div>
              <div className="qrow__meta">{templateLabel(scene.template)} · slide {scene.slide_index}</div>
              <span className={`pill pill--${pillFor(scene.status)}`}>{statusLabel(scene.status)}</span>
            </Link>
          </li>
        ))}
      </ul>
      {readyCount > 0 && (
        <button className="btn btn--primary" onClick={renderAllReady}>
          Approve all &amp; render remaining ({readyCount})
        </button>
      )}
      {error && <p role="alert" className="upload__error">{error}</p>}
    </section>
  )
}
