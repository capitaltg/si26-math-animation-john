import { useState } from 'react'

export default function App() {
  const [candidates, setCandidates] = useState(null)
  const [selected, setSelected] = useState({})
  const [results, setResults] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  async function handleUpload(event) {
    event.preventDefault()
    const file = event.target.file.files[0]
    if (!file) return
    setError(null)
    setLoading(true)
    setResults(null)
    const form = new FormData()
    form.append('file', file)
    try {
      const resp = await fetch('/upload', { method: 'POST', body: form, credentials: 'include' })
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
    setSelected((prev) => ({ ...prev, [id]: !prev[id] }))
  }

  async function handleRender() {
    const ids = Object.keys(selected).filter((id) => selected[id])
    if (ids.length === 0) return
    setError(null)
    setLoading(true)
    try {
      const resp = await fetch('/render', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ candidate_ids: ids }),
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

      {candidates && candidates.length > 0 && !results && (
        <section>
          <h2>Candidates</h2>
          {candidates.map((c) => (
            <label key={c.candidate_id} style={{ display: 'block', margin: '0.5rem 0' }}>
              <input
                type="checkbox"
                checked={!!selected[c.candidate_id]}
                onChange={() => toggle(c.candidate_id)}
              />
              <strong> {c.one_line_summary}</strong>
              <div style={{ color: '#666', fontSize: '0.85rem' }}>
                slide {c.slide_index}: {c.source_excerpt}
              </div>
            </label>
          ))}
          <button onClick={handleRender} disabled={loading}>Render selected</button>
        </section>
      )}

      {results && (
        <section>
          <h2>Results</h2>
          {results.map((r) => (
            <div key={r.candidate_id} style={{ margin: '0.75rem 0' }}>
              {r.clip_url ? (
                <a href={r.clip_url} download>Download clip ({r.candidate_id})</a>
              ) : (
                <span>Clip {r.candidate_id}</span>
              )}
              {r.status === 'fallback' && (
                <div style={{ color: '#b45309', fontSize: '0.85rem' }}>
                  Fallback: {r.fallback_reason}
                </div>
              )}
            </div>
          ))}
          <button onClick={() => setResults(null)}>Back to candidates</button>
        </section>
      )}
    </main>
  )
}
