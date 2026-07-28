import { useEffect, useState } from 'react'

async function responseJson(resp) {
  try {
    return await resp.json()
  } catch {
    return null
  }
}

export default function MetaReviewPanel() {
  const [drafts, setDrafts] = useState(null)
  const [selected, setSelected] = useState(null)
  const [feedback, setFeedback] = useState('')
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  async function loadDrafts() {
    setLoading(true)
    setError(null)
    try {
      const resp = await fetch('/meta/drafts?status=pending_review')
      const data = await responseJson(resp)
      if (!resp.ok) throw new Error(data?.detail || 'Could not load drafts')
      setDrafts(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadDrafts()
  }, [])

  async function openDraft(id) {
    setLoading(true)
    setError(null)
    try {
      const resp = await fetch(`/meta/drafts/${id}`)
      const data = await responseJson(resp)
      if (!resp.ok) throw new Error(data?.detail || 'Could not load draft')
      setSelected(data)
      setFeedback('')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function submitReject() {
    if (!selected || !feedback.trim()) return
    setLoading(true)
    setError(null)
    try {
      const resp = await fetch(`/meta/drafts/${selected.id}/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ feedback }),
      })
      const data = await responseJson(resp)
      if (!resp.ok) throw new Error(data?.detail || 'Could not reject draft')
      setSelected(null)
      await loadDrafts()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <main style={{ maxWidth: 900, margin: '2rem auto', fontFamily: 'sans-serif' }}>
      <h1>Meta-template review (dev only)</h1>
      {error && <p style={{ color: 'crimson' }}>{error}</p>}
      {loading && <p>Working…</p>}

      {!selected && (
        <section>
          <h2>Pending drafts</h2>
          {drafts && drafts.length === 0 && <p>No drafts pending review.</p>}
          {drafts && drafts.map((draft) => (
            <div
              key={draft.id}
              style={{ border: '1px solid #ddd', padding: '0.5rem', margin: '0.5rem 0' }}
            >
              <strong>{draft.fingerprint_key}</strong> — revision {draft.revision} — {draft.status}
              <button onClick={() => openDraft(draft.id)} disabled={loading} style={{ marginLeft: '1rem' }}>
                Review
              </button>
            </div>
          ))}
        </section>
      )}

      {selected && (
        <section>
          <button onClick={() => setSelected(null)}>Back to list</button>
          <h2>{selected.fingerprint_key} (revision {selected.revision})</h2>
          <p>{selected.classifier_bullet}</p>
          {selected.preview_url && (
            <img
              src={selected.preview_url}
              alt="preview"
              style={{ maxWidth: '100%', border: '1px solid #eee' }}
            />
          )}
          <h3>Fixtures</h3>
          <ul>
            {selected.fixtures.map((fixture) => (
              <li key={fixture.id}>
                [{fixture.kind}/{fixture.expected_outcome}] {JSON.stringify(fixture.params)}
                {' — '}
                {fixture.structural_check_passed === null
                  ? 'not checked'
                  : fixture.structural_check_passed
                  ? 'passed'
                  : `failed: ${fixture.structural_check_detail}`}
                {fixture.source_excerpt && <div style={{ color: '#666' }}>{fixture.source_excerpt}</div>}
              </li>
            ))}
          </ul>
          <h3>Reject with feedback</h3>
          <textarea
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            rows={3}
            style={{ width: '100%' }}
          />
          <div>
            <button onClick={submitReject} disabled={loading || !feedback.trim()}>
              Reject and request refinement
            </button>
          </div>
        </section>
      )}
    </main>
  )
}
