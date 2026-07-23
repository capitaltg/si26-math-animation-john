import { useState } from 'react'
import SchemaForm from './SchemaForm'

export default function App() {
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

  async function handleUpload(event) {
    event.preventDefault()
    const file = event.target.file.files[0]
    if (!file) return
    setError(null)
    setLoading(true)
    setOptions(null)
    setPicks({})
    setResults(null)
    const form = new FormData()
    form.append('file', file)
    try {
      const resp = await fetch('/upload', {
        method: 'POST',
        body: form,
        credentials: 'include',
      })
      if (!resp.ok) throw new Error((await resp.json()).detail || 'Upload failed')
      const data = await resp.json()
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
      if (!resp.ok) throw new Error((await resp.json()).detail || 'Could not get options')
      const data = await resp.json()
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

  return (
    <main style={{ maxWidth: 720, margin: '2rem auto', fontFamily: 'sans-serif' }}>
      <h1>Math Animation Generator</h1>

      <form onSubmit={handleUpload}>
        <input type="file" name="file" accept=".pptx" />
        <button type="submit" disabled={loading}>Upload</button>
      </form>

      {error && <p style={{ color: 'crimson' }}>{error}</p>}
      {loading && <p>Working…</p>}

      {candidates && candidates.length === 0 && <p>No problems found in this document.</p>}

      {candidates && candidates.length > 0 && !options && !results && (
        <section>
          <h2>Candidates</h2>
          {candidates.map((candidate) => (
            <label
              key={candidate.candidate_id}
              style={{ display: 'block', margin: '0.5rem 0' }}
            >
              <input
                type="checkbox"
                checked={!!selected[candidate.candidate_id]}
                disabled={loading}
                onChange={() => toggle(candidate.candidate_id)}
              />
              <strong> {candidate.one_line_summary}</strong>
              <div style={{ color: '#666', fontSize: '0.85rem' }}>
                slide {candidate.slide_index}: {candidate.source_excerpt}
              </div>
            </label>
          ))}
          <button onClick={handleGetOptions} disabled={loading}>Get options.</button>
        </section>
      )}

      {options && !storyboard && !results && (
        <section>
          <h2>Choose visualizations</h2>
          {options.map((item) => {
            const candidate = candidates.find(
              (entry) => entry.candidate_id === item.candidate_id,
            )
            return (
              <fieldset
                key={item.candidate_id}
                disabled={loading}
                style={{ margin: '1rem 0' }}
              >
                <legend>{candidate?.one_line_summary || item.candidate_id}</legend>
                {item.templates.map((option) => (
                  <label key={option.template} style={{ display: 'block', margin: '0.4rem 0' }}>
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
                    {' '}{option.template} — {option.rationale}
                  </label>
                ))}
              </fieldset>
            )
          })}
          <button onClick={handleBuildStoryboard} disabled={loading}>Review storyboard.</button>{' '}
          <button
            onClick={() => {
              setOptions(null)
              setPicks({})
              setError(null)
            }}
            disabled={loading}
          >
            Back to candidates
          </button>
        </section>
      )}

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

      {results && (
        <section>
          <h2>Results</h2>
          {results.map((result) => (
            <div key={result.candidate_id} style={{ margin: '0.75rem 0' }}>
              {result.clip_url ? (
                <a href={result.clip_url} download>
                  Download clip ({result.candidate_id})
                </a>
              ) : (
                <span>Clip {result.candidate_id}</span>
              )}
              {result.status === 'fallback' && (
                <div style={{ color: '#b45309', fontSize: '0.85rem' }}>
                  Fallback: {result.fallback_reason}
                </div>
              )}
            </div>
          ))}
          <button onClick={() => setResults(null)}>Back to options</button>
        </section>
      )}
    </main>
  )
}
