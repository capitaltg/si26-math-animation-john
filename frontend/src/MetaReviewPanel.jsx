import { useEffect, useRef, useState } from 'react'

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
    && Boolean(fixture.observation_id)
    && Boolean(fixture.source_excerpt)
    && fixture.expected_result != null
    && fixture.structural_check_passed === true
  )
}

// `kind` (positive/negative/boundary) says where the fixture came from;
// `expected_outcome` (accept/reject) says what should happen when it runs.
// A boundary fixture can still be expected to accept, so the label must
// read `expected_outcome`, not assume anything non-positive is a rejection.
function fixtureKindLabel(fixture) {
  const rejects = fixture.expected_outcome === 'reject'
  if (fixture.kind === 'positive') return 'Positive example — should compute correctly'
  if (fixture.kind === 'boundary') {
    return rejects
      ? 'Boundary example — edge case that should be rejected'
      : 'Boundary example — edge case that should still compute correctly'
  }
  return 'Negative example — should be rejected (guard case)'
}

function fixtureKindColor(fixture) {
  if (fixture.expected_outcome === 'reject') return '#9a6700'
  if (fixture.kind === 'positive') return '#1a7f37'
  return '#0969da'
}

function fixtureStatusLabel(fixture) {
  if (fixture.structural_check_passed === null) return 'Not checked yet'
  if (fixture.structural_check_passed) return 'Structural check passed'
  return `Structural check failed: ${fixture.structural_check_detail}`
}

function fixtureStatusColor(fixture) {
  if (fixture.structural_check_passed === null) return '#666'
  if (fixture.structural_check_passed) return '#1a7f37'
  return '#c00'
}

// The reviewer never sees a raw quality-check code, path, or detail string --
// only a human-readable category, and only once every check in that category
// has passed (the quality checklist shown here is compact and pass-only; a
// draft that failed any check never reaches pending_review in the first
// place, so there is nothing to explain). This map is the one place the
// code-to-label grouping lives; do not scatter it into the JSX below.
const QUALITY_CHECK_CATEGORIES = [
  {
    label: 'Pacing',
    codes: new Set([
      'timeline_duration', 'timeline_over_budget', 'timeline_duration_out_of_bounds',
      'serial_simple_reveal', 'conclusion_hold_too_short', 'unexplained_idle_time',
      'premature_answer_emphasis', 'static_process_visual',
    ]),
  },
  {
    label: 'Anchor alignment',
    codes: new Set(['collection_anchor_for_item', 'dimension_anchor_mismatch', 'callout_collision']),
  },
]

function passingQualityCategoryLabels(qualityReport) {
  const checks = qualityReport?.checks ?? []
  return QUALITY_CHECK_CATEGORIES.filter(({ codes }) => {
    const matching = checks.filter((check) => codes.has(check.code))
    return matching.length > 0 && matching.every((check) => check.passed)
  }).map(({ label }) => label)
}

function capitalize(word) {
  return word.charAt(0).toUpperCase() + word.slice(1)
}

// Brief-specified format: capitalized beat kind, a middle-dot separator with
// spaces, then the beat's intent verbatim -- e.g. "Reveal · show the ordered
// values together".
function formatBeat(beat) {
  return `${capitalize(beat.kind)} · ${beat.intent}`
}

// Trim trailing zeros: 8 seconds, not 8.0 seconds; 7.5 seconds, not 7.50.
function formatSeconds(seconds) {
  return `${Number(seconds.toFixed(2))} seconds`
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

  useEffect(() => {
    isMountedRef.current = true
    return () => {
      isMountedRef.current = false
      if (previewBlobUrlRef.current) URL.revokeObjectURL(previewBlobUrlRef.current)
    }
  }, [])

  async function loadDrafts() {
    setLoading(true)
    setError(null)
    try {
      // Invalid or already-decided candidates never leak into this list --
      // the review API only ever returns pending_review drafts, so this is
      // the only status worth requesting.
      const resp = await fetch('/meta/drafts?status=pending_review', { headers: authHeaders() })
      const data = await responseJson(resp)
      if (!resp.ok) throw new Error(messageFor(resp, data, 'Could not load drafts'))
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
  const negativePredicateCoverage = selected?.validation_report?.negative_predicate_coverage ?? []
  const coverageCount = negativePredicateCoverage.length
  const hasFullPredicateCoverage = Boolean(selected?.validation_report) && coverageCount === predicateCount
  const missingPredicateIndexes = Array.from({ length: predicateCount }, (_, i) => i)
    .filter((i) => !negativePredicateCoverage.includes(i))
  const qualifyingFixtureCount = selected
    ? new Set(
      selected.fixtures
        .filter(isQualifyingFixture)
        .map((fixture) => fixture.observation_id),
    ).size
    : 0
  const requiredFixtureCount = selected?.required_fixture_count ?? 5
  const positiveFixtures = selected ? selected.fixtures.filter((f) => f.kind === 'positive') : []
  const guardFixtures = selected ? selected.fixtures.filter((f) => f.kind !== 'positive') : []
  const validationPassed = selected?.validation_report?.passed === true
  const passingQualityLabels = passingQualityCategoryLabels(selected?.quality_report)
  const totalDurationSeconds = selected?.total_duration_seconds ?? 0
  const canApprove = Boolean(
    selected
    && selected.status === 'pending_review'
    && validationPassed
    && hasFullPredicateCoverage
    && qualifyingFixtureCount >= requiredFixtureCount
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
        <button type="button" onClick={loadDrafts} disabled={loading}>
          Load drafts
        </button>
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

          <section>
            <h3>Teaching plan</h3>
            <p>{selected.teaching_plan.learning_objective}</p>
            <ol>
              {selected.teaching_plan.beats.map((beat) => (
                <li key={beat.id}>{formatBeat(beat)}</li>
              ))}
            </ol>
            <p>Total compiled duration: <strong>{formatSeconds(totalDurationSeconds)}</strong></p>
            {passingQualityLabels.length > 0 && (
              <ul>
                {passingQualityLabels.map((label) => (
                  <li key={label} style={{ color: '#1a7f37' }}>{label} passed</li>
                ))}
              </ul>
            )}
          </section>

          {previewSrc && (
            <img
              src={previewSrc}
              alt="preview"
              style={{ maxWidth: '100%', border: '1px solid #eee' }}
            />
          )}
          {!validationPassed && (
            <div style={{ border: '1px solid #c00', borderRadius: 4, padding: '0.75rem', margin: '0.75rem 0', background: '#fff5f5' }}>
              <strong style={{ color: '#c00' }}>
                This draft failed automatic validation and can't be approved yet.
              </strong>
              {selected.validation_report?.compile_error && (
                <p>Compile error: {selected.validation_report.compile_error}</p>
              )}
              {selected.validation_report?.preview_error && (
                <p>Preview error: {selected.validation_report.preview_error}</p>
              )}
              {missingPredicateIndexes.length > 0 && (
                <p>
                  {missingPredicateIndexes.length} of {predicateCount} guard predicates
                  (#{missingPredicateIndexes.join(', #')}) have no guard case proving they
                  correctly reject bad input.
                </p>
              )}
              <p>
                Guard cases are system-generated and not editable here — use
                "Reject and request refinement" below so the worker can regenerate
                with fixes.
              </p>
            </div>
          )}
          <h3>Fixtures to verify ({qualifyingFixtureCount} / {requiredFixtureCount})</h3>
          <p style={{ color: '#444' }}>
            Each one below is a real example pulled from course content. Confirm or
            correct its answer and save — once it passes its check, it counts toward
            the {requiredFixtureCount} required before this template can publish.
          </p>
          <ul style={{ listStyle: 'none', padding: 0 }}>
            {positiveFixtures.map((fixture, index) => (
              <li
                key={fixture.id}
                style={{ border: '1px solid #ddd', borderRadius: 4, padding: '0.75rem', margin: '0.75rem 0' }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                  <strong>Fixture {index + 1}</strong>
                  {isQualifyingFixture(fixture) && <span style={{ color: '#1a7f37' }}>✓ Verified</span>}
                </div>
                {fixture.source_excerpt ? (
                  <blockquote style={{ color: '#666', margin: '0.5rem 0' }}>
                    “{fixture.source_excerpt}”
                  </blockquote>
                ) : (
                  <p style={{ color: '#c00' }}>
                    ⚠ No source excerpt on this fixture — it isn't tied to a real
                    observation, so it can never count toward the requirement no
                    matter what's entered below.
                  </p>
                )}
                <div style={{ color: fixtureStatusColor(fixture) }}>{fixtureStatusLabel(fixture)}</div>
                <div>
                  <label htmlFor={`fixture-${fixture.id}-params`}>Fixture {fixture.id} params</label>
                  <div style={{ fontSize: '0.85em', color: '#666' }}>Inputs fed into the template</div>
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
                  <div style={{ fontSize: '0.85em', color: '#666' }}>
                    Answer the template should produce for these inputs
                  </div>
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

          <h3>Guard cases</h3>
          <p style={{ color: '#444' }}>
            These prove the template correctly rejects invalid input or handles edge
            values. They're system-generated and read-only — no answer to confirm,
            no action needed here.
          </p>
          {guardFixtures.length === 0 && <p style={{ color: '#666' }}>None for this draft.</p>}
          <ul style={{ listStyle: 'none', padding: 0 }}>
            {guardFixtures.map((fixture) => (
              <li
                key={fixture.id}
                style={{ border: '1px solid #eee', borderRadius: 4, padding: '0.75rem', margin: '0.75rem 0' }}
              >
                <span
                  style={{
                    color: '#fff',
                    background: fixtureKindColor(fixture),
                    borderRadius: 12,
                    padding: '0.1rem 0.6rem',
                    fontSize: '0.8em',
                  }}
                >
                  {fixtureKindLabel(fixture)}
                </span>
                <div style={{ color: fixtureStatusColor(fixture) }}>{fixtureStatusLabel(fixture)}</div>
                {fixture.source_excerpt && (
                  <blockquote style={{ color: '#666', margin: '0.5rem 0' }}>
                    “{fixture.source_excerpt}”
                  </blockquote>
                )}
              </li>
            ))}
          </ul>
          <h3>Approve</h3>
          <p>
            Verified fixtures: {qualifyingFixtureCount} / {requiredFixtureCount} required.
            {' '}
            Predicate coverage (guard cases confirmed to correctly reject bad input): {coverageCount} / {predicateCount}.
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
