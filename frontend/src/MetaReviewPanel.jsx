import { useEffect, useRef, useState } from 'react'

// Matches Settings.fingerprint_observation_threshold's default
// (backend/app/config.py). The server has no endpoint exposing the
// configured value, and this gate is UX-only -- approve_draft_service
// enforces the real threshold regardless of what the client shows.
const FIXTURE_THRESHOLD = 5
const TEMPLATE_NAME_PATTERN = /^[a-z][a-z0-9_]*$/

async function responseJson(resp) {
  try {
    return await resp.json()
  } catch {
    return null
  }
}

function isQualifyingFixture(fixture) {
  return (
    fixture.kind === 'positive'
    && Boolean(fixture.source_excerpt)
    && fixture.expected_result != null
    && fixture.structural_check_passed === true
  )
}

export default function MetaReviewPanel() {
  const [drafts, setDrafts] = useState(null)
  const [selected, setSelected] = useState(null)
  const [feedback, setFeedback] = useState('')
  const [templateName, setTemplateName] = useState('')
  const [mathSemanticsConfirmed, setMathSemanticsConfirmed] = useState(false)
  const [error, setError] = useState(null)
  const [fixtureTexts, setFixtureTexts] = useState({})
  const [fixtureErrors, setFixtureErrors] = useState({})
  const [loading, setLoading] = useState(false)
  const [reviewerToken, setReviewerToken] = useState(
    () => sessionStorage.getItem('metaReviewerToken') || '',
  )

  function handleTokenChange(e) {
    const value = e.target.value
    setReviewerToken(value)
    sessionStorage.setItem('metaReviewerToken', value)
  }

  function authHeaders() {
    return { Authorization: `Bearer ${reviewerToken}` }
  }

  function messageFor(resp, data, fallback) {
    if (resp.status === 401) return 'Invalid or missing reviewer token'
    return data?.detail || fallback
  }

  const [previewSrc, setPreviewSrc] = useState(null)
  const previewBlobUrlRef = useRef(null)
  const previewLoadIdRef = useRef(0)
  const isMountedRef = useRef(true)

  function clearPreview() {
    if (previewBlobUrlRef.current) {
      URL.revokeObjectURL(previewBlobUrlRef.current)
      previewBlobUrlRef.current = null
    }
    setPreviewSrc(null)
  }

  // Returning to the list view (after a reject/approve or via "Back to
  // list") must revoke the current preview blob URL: the <img> disappears
  // because it's gated on `selected`, but the blob itself would otherwise
  // stay alive -- and leaked -- until the next loadPreview call or unmount.
  //
  // It must also invalidate any loadPreview call already in flight at the
  // moment of navigation (selected is set, and "Back to list" is clickable,
  // before openDraft's loadPreview call resolves). Bumping the token here
  // means that in-flight call's own staleness check -- the same one used
  // for out-of-order loadPreview calls -- will see it's been superseded
  // once it resolves, and self-revoke instead of writing a blob URL into
  // state for a list view that's no longer showing a preview at all.
  //
  // This bump deliberately lives here rather than inside clearPreview():
  // loadPreview() also calls clearPreview() itself (to revoke the previous
  // blob) *after* capturing its own loadId into a local variable, so a
  // bump inside clearPreview() would make every loadPreview call see its
  // own freshly-claimed id as already stale.
  function returnToList() {
    clearPreview()
    previewLoadIdRef.current += 1
    setSelected(null)
  }

  async function loadPreview(url) {
    // Claim a token for this call before doing any async work. If a newer
    // loadPreview call starts before this one's fetch/blob resolves, the
    // token comparison below lets this call notice it's stale -- so it can
    // revoke its own now-unwanted blob URL instead of leaking it, and avoid
    // clobbering whatever the newer call has already put in state.
    previewLoadIdRef.current += 1
    const loadId = previewLoadIdRef.current
    clearPreview()
    if (!url) return
    try {
      const resp = await fetch(url, { headers: authHeaders() })
      if (!resp.ok) return
      const blob = await resp.blob()
      const objectUrl = URL.createObjectURL(blob)
      if (!isMountedRef.current) {
        // The component unmounted while this fetch/blob was in flight. The
        // unmount cleanup below already ran (and had nothing to revoke at
        // the time), so this now-orphaned blob URL is ours alone to clean
        // up -- revoke it immediately and don't touch state.
        URL.revokeObjectURL(objectUrl)
        return
      }
      if (previewLoadIdRef.current !== loadId) {
        // A newer call has since started (and possibly already resolved).
        // This result is stale: drop it and revoke the blob URL we just
        // created so it doesn't leak.
        URL.revokeObjectURL(objectUrl)
        return
      }
      previewBlobUrlRef.current = objectUrl
      setPreviewSrc(objectUrl)
    } catch {
      // Preview is supplementary -- a failed fetch just leaves no image,
      // same as the existing `selected.preview_url &&` conditional did
      // when a draft simply had no preview yet.
    }
  }

  useEffect(() => () => {
    isMountedRef.current = false
    if (previewBlobUrlRef.current) URL.revokeObjectURL(previewBlobUrlRef.current)
  }, [])

  async function loadDrafts() {
    setLoading(true)
    setError(null)
    try {
      const responses = await Promise.all([
        fetch('/meta/drafts?status=pending_review', { headers: authHeaders() }),
        fetch('/meta/drafts?status=failed_validation', { headers: authHeaders() }),
      ])
      const draftLists = await Promise.all(responses.map(async (resp) => {
        const data = await responseJson(resp)
        if (!resp.ok) throw new Error(messageFor(resp, data, 'Could not load drafts'))
        return data
      }))
      setDrafts([...new Map(draftLists.flat().map((draft) => [draft.id, draft])).values()])
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
      const resp = await fetch(`/meta/drafts/${id}`, { headers: authHeaders() })
      const data = await responseJson(resp)
      if (!resp.ok) throw new Error(messageFor(resp, data, 'Could not load draft'))
      setSelected(data)
      setFeedback('')
      setTemplateName('')
      setMathSemanticsConfirmed(false)
      setFixtureTexts({})
      setFixtureErrors({})
      await loadPreview(data.preview_url)
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
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ feedback }),
      })
      const data = await responseJson(resp)
      if (!resp.ok) throw new Error(messageFor(resp, data, 'Could not reject draft'))
      returnToList()
      await loadDrafts()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function saveFixture(fixture) {
    const texts = fixtureTexts[fixture.id] || {
      params: JSON.stringify(fixture.params),
      expectedResult: JSON.stringify(fixture.expected_result || { answer: '' }),
    }
    let params
    let expectedResult
    try {
      params = JSON.parse(texts.params)
      expectedResult = JSON.parse(texts.expectedResult)
    } catch {
      setFixtureErrors((current) => ({ ...current, [fixture.id]: 'Enter valid JSON' }))
      return
    }

    setFixtureErrors((current) => ({ ...current, [fixture.id]: null }))
    try {
      const resp = await fetch(`/meta/drafts/${selected.id}/fixtures/${fixture.id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ params, expected_result: expectedResult }),
      })
      const data = await responseJson(resp)
      if (!resp.ok) throw new Error(messageFor(resp, data, 'Could not save fixture'))
      // Re-fetch the full draft detail rather than patching just this one
      // fixture locally: editing a fixture forces server-side revalidation
      // (Task 3), so the validation report and preview can change too.
      await openDraft(selected.id)
    } catch (err) {
      setFixtureErrors((current) => ({ ...current, [fixture.id]: err.message }))
    }
  }

  async function submitApprove() {
    if (!selected || !canApprove) return
    setLoading(true)
    setError(null)
    try {
      const resp = await fetch(`/meta/drafts/${selected.id}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          template_name: templateName,
          math_semantics_confirmed: mathSemanticsConfirmed,
        }),
      })
      const data = await responseJson(resp)
      if (!resp.ok) throw new Error(messageFor(resp, data, 'Could not approve draft'))
      returnToList()
      await loadDrafts()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const predicateCount = selected?.guard_document?.predicates?.length ?? 0
  const coverageCount = selected?.validation_report?.negative_predicate_coverage?.length ?? 0
  const hasFullPredicateCoverage = Boolean(selected?.validation_report) && coverageCount === predicateCount
  const qualifyingFixtureCount = selected ? selected.fixtures.filter(isQualifyingFixture).length : 0
  const canApprove = Boolean(
    selected
    && selected.status === 'pending_review'
    && selected.validation_report?.passed === true
    && hasFullPredicateCoverage
    && qualifyingFixtureCount >= FIXTURE_THRESHOLD
    && TEMPLATE_NAME_PATTERN.test(templateName)
    && mathSemanticsConfirmed,
  )

  return (
    <main style={{ maxWidth: 900, margin: '2rem auto', fontFamily: 'sans-serif' }}>
      <h1>Meta-template review (dev only)</h1>
      <div>
        <label htmlFor="reviewer-token">Reviewer token</label>
        <input
          id="reviewer-token"
          type="password"
          value={reviewerToken}
          onChange={handleTokenChange}
        />
      </div>
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
          <button onClick={returnToList}>Back to list</button>
          <h2>{selected.fingerprint_key} (revision {selected.revision})</h2>
          <p>{selected.classifier_bullet}</p>
          {previewSrc && (
            <img
              src={previewSrc}
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
                <div>
                  <label htmlFor={`fixture-${fixture.id}-params`}>Fixture {fixture.id} params</label>
                  <textarea
                    id={`fixture-${fixture.id}-params`}
                    value={fixtureTexts[fixture.id]?.params ?? JSON.stringify(fixture.params)}
                    onChange={(e) => setFixtureTexts((current) => ({
                      ...current,
                      [fixture.id]: {
                        params: e.target.value,
                        expectedResult: current[fixture.id]?.expectedResult
                          ?? JSON.stringify(fixture.expected_result || { answer: '' }),
                      },
                    }))}
                    rows={3}
                  />
                </div>
                <div>
                  <label htmlFor={`fixture-${fixture.id}-expected-result`}>
                    Fixture {fixture.id} expected result
                  </label>
                  <textarea
                    id={`fixture-${fixture.id}-expected-result`}
                    value={fixtureTexts[fixture.id]?.expectedResult
                      ?? JSON.stringify(fixture.expected_result || { answer: '' })}
                    onChange={(e) => setFixtureTexts((current) => ({
                      ...current,
                      [fixture.id]: {
                        params: current[fixture.id]?.params ?? JSON.stringify(fixture.params),
                        expectedResult: e.target.value,
                      },
                    }))}
                    rows={3}
                  />
                </div>
                <button onClick={() => saveFixture(fixture)}>Save fixture</button>
                {fixtureErrors[fixture.id] && <p style={{ color: 'crimson' }}>{fixtureErrors[fixture.id]}</p>}
              </li>
            ))}
          </ul>
          <h3>Approve</h3>
          <p>
            Verified fixtures: {qualifyingFixtureCount} / {FIXTURE_THRESHOLD} required.
            {' '}
            Predicate coverage: {coverageCount} / {predicateCount}.
          </p>
          <div>
            <label htmlFor="template-name">Template name</label>
            <input
              id="template-name"
              value={templateName}
              onChange={(e) => setTemplateName(e.target.value)}
            />
          </div>
          <div>
            <input
              id="math-semantics-confirmed"
              type="checkbox"
              checked={mathSemanticsConfirmed}
              onChange={(e) => setMathSemanticsConfirmed(e.target.checked)}
            />
            <label htmlFor="math-semantics-confirmed">
              I confirm the mathematical semantics and preview are correct
            </label>
          </div>
          <div>
            <button onClick={submitApprove} disabled={loading || !canApprove}>
              Approve and publish
            </button>
          </div>
          <h3>Reject with feedback</h3>
          <textarea
            aria-label="Feedback"
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
