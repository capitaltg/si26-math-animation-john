import { useState } from 'react'
import SchemaForm from './SchemaForm'

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
  const [chainSelected, setChainSelected] = useState({})  // scene_id -> bool, combine checkboxes

  async function handleUpload(event) {
    event.preventDefault()
    const file = event.target.file.files[0]
    if (!file) return
    setError(null)
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
    setLoading(true)
    try {
      const resp = await fetch('/render', { method: 'POST', credentials: 'include' })
      const data = await responseJson(resp, 'Render failed')
      if (!resp.ok) throw new Error(responseError(data, 'Render failed'))
      setResults(data.clips)
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

      {candidates && candidates.length === 0 && (
        <p>
          No solvable problems found in this document. Slides with concept
          explanations, vocabulary, or &quot;color/identify&quot; prompts
          aren&apos;t flagged unless they state a concrete problem with
          numbers to work out.
        </p>
      )}

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

          {canCombine && (
            <div style={{ margin: '0.5rem 0' }}>
              <button onClick={handleCombineScenes} disabled={loading}>
                Combine {checkedScenes.length} into one scene
              </button>
            </div>
          )}

          {storyboard.map((scene) => {
            const isDirty = sceneIsDirty(scene, drafts)
            const isChain = !!scene.candidate_ids
            const combinable =
              scene.status === 'pending_review' && !!scene.candidate_id && !isChain
            return (
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
              {combinable && (
                <label style={{ display: 'block', marginBottom: '0.3rem' }}>
                  <input
                    type="checkbox"
                    checked={!!chainSelected[scene.scene_id]}
                    disabled={loading}
                    onChange={() => toggleChainSelect(scene.scene_id)}
                  />
                  {' '}Combine with other selected scenes
                </label>
              )}

              <strong>{scene.detected_summary}</strong>
              {isChain && (
                <span style={{ color: '#666', fontSize: '0.8rem' }}>
                  {' '}(combined: {scene.candidate_ids.join(', ')})
                </span>
              )}
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
                  disabled={loading}
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

              <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                <button onClick={() => saveEdits(scene.scene_id)} disabled={loading}>Save edits</button>
                {isChain ? (
                  <button onClick={() => handleUngroupScene(scene.scene_id)} disabled={loading}>
                    Ungroup
                  </button>
                ) : (
                  <button onClick={() => retryScene(scene.scene_id)} disabled={loading}>Retry</button>
                )}
                <button
                  onClick={() => approveScene(scene.scene_id)}
                  disabled={loading || isDirty}
                  title={isDirty ? 'Save edits before approving' : undefined}
                >
                  Approve
                </button>
                <button onClick={() => rejectScene(scene.scene_id)} disabled={loading}>Reject</button>
                {isDirty && (
                  <span style={{ color: '#b45309', fontSize: '0.85rem' }}>
                    Unsaved edits — Save first
                  </span>
                )}
              </div>
            </div>
            )
          })}

          <button
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
        <section>
          <h2>Results</h2>
          {results.map((result) => {
            const ids = result.candidate_ids || [result.candidate_id || result.scene_id]
            return (
              <div key={result.scene_id || result.candidate_id} style={{ margin: '0.75rem 0' }}>
                {result.status === 'error' ? (
                  <span style={{ color: 'crimson' }}>
                    Render failed for {ids.join(', ')}
                  </span>
                ) : result.clip_url ? (
                  <a href={result.clip_url} download>
                    Download clip ({ids.join(', ')})
                  </a>
                ) : (
                  <span>Clip {ids.join(', ')}</span>
                )}
                {result.status === 'fallback' && (
                  <div style={{ color: '#b45309', fontSize: '0.85rem' }}>
                    Fallback: {result.fallback_reason}
                  </div>
                )}
              </div>
            )
          })}
          <button
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
        </section>
      )}
    </main>
  )
}
