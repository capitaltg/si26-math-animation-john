import { useState } from 'react'

export default function App() {
  const [candidates, setCandidates] = useState(null)
  const [selected, setSelected] = useState({})
  const [options, setOptions] = useState(null)
  const [picks, setPicks] = useState({})
  const [results, setResults] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

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

  async function handleRender() {
    if (!options || options.some((item) => !picks[item.candidate_id])) return
    setError(null)
    setLoading(true)
    try {
      const renderPicks = options.map((item) => ({
        candidate_id: item.candidate_id,
        template: picks[item.candidate_id],
      }))
      const resp = await fetch('/render', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ picks: renderPicks }),
      })
      if (!resp.ok) throw new Error((await resp.json()).detail || 'Render failed')
      const data = await resp.json()
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

      {options && !results && (
        <section>
          <h2>Choose visualizations</h2>
          {options.map((item) => {
            const candidate = candidates.find(
              (entry) => entry.candidate_id === item.candidate_id,
            )
            return (
              <fieldset key={item.candidate_id} style={{ margin: '1rem 0' }}>
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
          <button onClick={handleRender} disabled={loading}>Render.</button>{' '}
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
