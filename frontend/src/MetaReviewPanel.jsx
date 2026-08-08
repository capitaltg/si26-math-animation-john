import { useEffect, useRef, useState } from 'react'
import GatePanel from './GatePanel'
import { IconAlert, IconCard, IconCheck, IconChecked, IconWorking } from './Icons'

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

function fixtureStatusLabel(fixture) {
  if (fixture.structural_check_passed === null) return 'Not checked yet'
  if (fixture.structural_check_passed) return 'Structural check passed'
  return `Structural check failed: ${fixture.structural_check_detail}`
}

// State carried in the stamp vocabulary rather than in a colour literal, so
// this panel reports a check the same way every other surface does.
function fixtureStatusState(fixture) {
  if (fixture.structural_check_passed === null) return 'todo'
  return fixture.structural_check_passed ? 'done' : 'failed'
}

function StatusStamp({ state, children }) {
  return (
    <p className="stamp" data-state={state}>
      <span className="stamp__mark">
        {state === 'done' ? <IconCheck size={16} />
          : state === 'failed' ? <IconAlert size={16} />
          : <IconWorking size={16} />}
      </span>
      {children}
    </p>
  )
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
  // Codes emitted by app/meta/v3/render_probe.py. Approval precondition 5
  // requires a passing quality_report, so a draft that reaches this panel has
  // already cleared these -- surfacing the category tells the reviewer the
  // render gates actually ran instead of only the static ones.
  {
    label: 'Rendered output',
    codes: new Set([
      'blank_probe_frame',
      'frame_out_of_bounds',
      'anchor_alignment_mismatch',
      'rendered_relation_mismatch',
      'rendered_state_mismatch',
      'state_order_invalid',
      'undeclared_path_event',
      'final_answer_not_persistent',
      'render_probe_contract_invalid',
      // A failing render-probe code that is not listed here would go
      // unnoticed by passingQualityCategoryLabels -- the category filter
      // matches on code, so an unmapped failure never drops the "Rendered
      // output passed" label. Keep this set exhaustive against the codes
      // emitted by app/meta/v3/render_probe.py.
      'visual_overlap',
      'dimension_label_missing',
    ]),
  },
]

// Per-category gate rows for the meta panel: keep a category's failed status
// visible instead of dropping the row entirely. A category with no matching
// checks in this quality report has no signal to show and is omitted.
function qualityCategoryGates(qualityReport) {
  const checks = qualityReport?.checks ?? []
  const gates = []
  for (const { label, codes } of QUALITY_CHECK_CATEGORIES) {
    const matching = checks.filter((check) => codes.has(check.code))
    if (matching.length === 0) continue
    const anyFailed = matching.some((check) => !check.passed)
    const status = anyFailed ? 'failed' : 'passed'
    const name = anyFailed ? `${label} failed` : `${label} passed`
    // Raw check codes/paths/details are internal — the reviewer sees status
    // only. GatePanel emits a fallback "Status: failed" line when `details`
    // is absent, which is enough signal without leaking check internals.
    gates.push({ name, category: label, status })
  }
  return gates
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
  const [versions, setVersions] = useState(null)
  const [libraryError, setLibraryError] = useState(null)
  const [rejectedCount, setRejectedCount] = useState(null)
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
      // the review API only ever returns pending_review drafts, regardless of
      // any status a caller might pass in the query string.
      const resp = await fetch('/meta/drafts', { headers: authHeaders() })
      const data = await responseJson(resp)
      if (!resp.ok) throw new Error(messageFor(resp, data, 'Could not load drafts'))
      setDrafts(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
    // A failed count is not worth a whole error banner -- the counter just
    // stays hidden. Reload pending drafts is the primary action.
    try {
      const resp = await fetch('/meta/drafts/rejected_count', { headers: authHeaders() })
      const data = await responseJson(resp)
      if (resp.ok && typeof data?.count === 'number') setRejectedCount(data.count)
    } catch {
      // ignored -- the counter is supplementary
    }
  }

  // The library keeps its own error state: a failure to list live versions must
  // not look like a failure to load the drafts, and vice versa.
  async function loadVersions() {
    setLibraryError(null)
    try {
      const resp = await fetch('/meta/versions', { headers: authHeaders() })
      const data = await responseJson(resp)
      if (!resp.ok) throw new Error(messageFor(resp, data, 'Could not load the template library'))
      setVersions(data)
    } catch (err) {
      setLibraryError(err.message)
    }
  }

  useEffect(() => {
    loadDrafts()
    loadVersions()
  }, [])

  // Clearing the owner is what turns a teacher's private template into
  // everyone's. The server re-checks the full evidence bar, so a refusal here is
  // an expected outcome and is reported rather than swallowed.
  async function promoteVersion(versionId) {
    setLibraryError(null)
    setLoading(true)
    try {
      const resp = await fetch(`/meta/versions/${versionId}/promote`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
      })
      const data = await responseJson(resp)
      if (!resp.ok) throw new Error(messageFor(resp, data, 'Could not share this template'))
      await loadVersions()
    } catch (err) {
      setLibraryError(err.message)
    } finally {
      setLoading(false)
    }
  }

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

  async function revalidateDraft() {
    if (!selected) return
    setLoading(true)
    setError(null)
    try {
      const resp = await fetch(`/meta/drafts/${selected.id}/revalidate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
      })
      const data = await responseJson(resp)
      if (!resp.ok) throw new Error(messageFor(resp, data, 'Could not re-validate draft'))
      // The route answers with the whole refreshed draft, so the restored
      // reports and preview land without a second detail fetch -- and unlike
      // openDraft, this keeps the template name and confirmation the reviewer
      // may already have filled in.
      setSelected(data)
      await loadPreview(data.preview_url)
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
      // A new enabled version just appeared, so the library below is stale.
      await loadVersions()
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
  // Approval precondition 5 (app/meta/approval.py) requires a passing quality
  // report whose artifact_hash matches the draft's own -- without this the
  // Approve button is enabled for a draft the server will refuse at 422.
  const qualityReportPassed = Boolean(
    selected
    && selected.quality_report?.passed === true
    && selected.quality_report.artifact_hash === selected.artifact_hash,
  )
  const qualityGates = qualityCategoryGates(selected?.quality_report)
  const totalDurationSeconds = selected?.total_duration_seconds ?? 0
  const canApprove = Boolean(
    selected
    && selected.status === 'pending_review'
    && validationPassed
    && qualityReportPassed
    && hasFullPredicateCoverage
    && qualifyingFixtureCount >= requiredFixtureCount
    && TEMPLATE_NAME_PATTERN.test(templateName)
    && mathSemanticsConfirmed,
  )

  return (
    <div className="shell">
      <header className="masthead">
        <div className="masthead__inner">
          <h1>Meta-template review (dev only)</h1>
          <p className="masthead__sub">
            Review the drafts no single teacher owns, and share a teacher&apos;s own
            template with everyone.
          </p>
        </div>
      </header>

      <main className="page">
        <section className="band">
          <div className="band__head">
            <h2>Reviewer token</h2>
            <p className="band__note">Kept in this tab&apos;s session storage only.</p>
          </div>
          <div className="reload-strip">
            <label className="field admin__token" htmlFor="reviewer-token">
              <span className="field__label">Reviewer token</span>
              <input
                id="reviewer-token"
                type="password"
                value={reviewerToken}
                onChange={handleTokenChange}
              />
            </label>
            <button type="button" className="btn" onClick={loadDrafts} disabled={loading}>
              Load drafts
            </button>
            {loading && <span className="dirty-flag">Working…</span>}
          </div>
        </section>

        {error && (
          <div className="notice notice--danger" role="alert">
            <IconAlert />
            <p className="notice__body">{error}</p>
          </div>
        )}

        {!selected && (
          <>
            <section className="band">
              <div className="band__head">
                <h2>Pending drafts</h2>
                <p className="band__note">
                  A threshold-triggered draft belongs to no session, so a human decides it.
                </p>
              </div>
              {rejectedCount !== null && (
                <p className="stamps__count">
                  {rejectedCount} draft{rejectedCount === 1 ? '' : 's'} rejected before review
                </p>
              )}
              {drafts && drafts.length === 0 && (
                <div className="notice notice--empty">
                  <IconCard />
                  <p className="notice__body">No drafts pending review.</p>
                </div>
              )}
              {drafts && drafts.map((draft) => (
                <div className="admin__row" key={draft.id}>
                  <div>
                    <p className="admin__row-title">{draft.fingerprint_key}</p>
                    <p className="admin__row-note">
                      revision {draft.revision} · {draft.status}
                    </p>
                  </div>
                  <button
                    type="button"
                    className="btn"
                    onClick={() => openDraft(draft.id)}
                    disabled={loading}
                  >
                    Review
                  </button>
                </div>
              ))}
            </section>

            <section className="band">
              <div className="band__head">
                <h2>Live template library</h2>
                <p className="band__note">
                  A version owned by a session is enabled for that teacher alone.
                </p>
              </div>

              {libraryError && (
                <div className="notice notice--danger" role="alert">
                  <IconAlert />
                  <p className="notice__body">{libraryError}</p>
                </div>
              )}

              {versions && versions.length === 0 && (
                <div className="notice notice--empty">
                  <IconCard />
                  <p className="notice__body">No templates are live yet.</p>
                </div>
              )}

              {versions && versions.map((version) => (
                <div className="admin__row" key={version.id}>
                  <div>
                    <p className="admin__row-title">{version.template_name}</p>
                    <p className="admin__row-note">
                      {version.fingerprint_key}
                      {version.owner_session_id
                        ? ` · private to session ${version.owner_session_id}`
                        : ''}
                    </p>
                  </div>
                  {version.owner_session_id ? (
                    <button
                      type="button"
                      className="btn"
                      onClick={() => promoteVersion(version.id)}
                      disabled={loading}
                    >
                      Share with everyone
                    </button>
                  ) : (
                    <span className="stamp" data-state="done">
                      <span className="stamp__mark"><IconChecked size={16} /></span>
                      Shared with everyone
                    </span>
                  )}
                </div>
              ))}
            </section>
          </>
        )}

        {selected && (
          <>
            <section className="band">
              <div className="band__head">
                <h2>{selected.fingerprint_key} (revision {selected.revision})</h2>
                <p className="band__note">
                  Total compiled duration <strong>{formatSeconds(totalDurationSeconds)}</strong>
                </p>
              </div>
              <p className="admin__bullet">{selected.classifier_bullet}</p>

              <h3 className="admin__subhead">Teaching plan</h3>
              {/* teaching_plan is required to be a plan_version-3 document by the
                  backend's own validation, but the API's declared shape is a
                  bare `dict`, so a minimal `{plan_version: 3}` can reach here
                  without crashing the panel. */}
              {selected.teaching_plan?.learning_objective && (
                <p className="admin__objective">{selected.teaching_plan.learning_objective}</p>
              )}
              {selected.teaching_plan?.beats && (
                <ol className="workshop__beats">
                  {selected.teaching_plan.beats.map((beat) => (
                    <li key={beat.id}>{formatBeat(beat)}</li>
                  ))}
                </ol>
              )}
              <GatePanel gates={qualityGates} />

              {previewSrc && (
                <div className="inset admin__preview">
                  <img src={previewSrc} alt="preview" />
                </div>
              )}
              <div className="actions">
                <button type="button" className="btn btn--quiet" onClick={returnToList}>
                  Back to list
                </button>
              </div>
            </section>

            {!validationPassed && (
              <div className="notice notice--danger" role="alert">
                <IconAlert />
                <div>
                  <p className="notice__body">
                    {selected.validation_report
                      ? "This draft failed automatic validation and can't be approved yet."
                      : "Your fixture edit cleared this draft's validation evidence, so it can't be approved."}
                  </p>
                  {selected.validation_report ? (
                    <>
                      {missingPredicateIndexes.length > 0 && (
                        <p className="notice__body">
                          {missingPredicateIndexes.length} of {predicateCount} guard predicates
                          (#{missingPredicateIndexes.join(', #')}) have no guard case proving they
                          correctly reject bad input.
                        </p>
                      )}
                      <p className="notice__body">
                        Guard cases are system-generated and not editable here — use
                        &quot;Reject and request refinement&quot; below so the worker can
                        regenerate with fixes.
                      </p>
                    </>
                  ) : (
                    <>
                      <p className="notice__body">
                        Nothing failed — the checks and the preview just need to run again
                        against your corrected fixture. Re-validating keeps your edit;
                        rejecting below discards it.
                      </p>
                      <div className="actions">
                        <button
                          type="button"
                          className="btn"
                          onClick={revalidateDraft}
                          disabled={loading}
                        >
                          Re-validate this draft
                        </button>
                      </div>
                    </>
                  )}
                </div>
              </div>
            )}

            <section className="band">
              <div className="band__head">
                <h2>Fixtures to verify ({qualifyingFixtureCount} / {requiredFixtureCount})</h2>
                <p className="band__note">
                  Predicate coverage {coverageCount} / {predicateCount}
                </p>
              </div>
              <p className="admin__lead">
                Each one below is a real example pulled from course content. Confirm or
                correct its answer and save — once it passes its check, it counts toward
                the {requiredFixtureCount} required before this template can publish.
              </p>
              <ul className="admin__list">
                {positiveFixtures.map((fixture, index) => (
                  <li className="admin__fixture" key={fixture.id}>
                    <div className="admin__fixture-head">
                      <p className="admin__row-title">Fixture {index + 1}</p>
                      {isQualifyingFixture(fixture) && (
                        <span className="stamp" data-state="done">
                          <span className="stamp__mark"><IconCheck size={16} /></span>
                          Verified
                        </span>
                      )}
                    </div>
                    {fixture.source_excerpt ? (
                      <p className="scene__source">{fixture.source_excerpt}</p>
                    ) : (
                      <div className="notice notice--danger" role="alert">
                        <IconAlert />
                        <p className="notice__body">
                          No source excerpt on this fixture — it isn&apos;t tied to a real
                          observation, so it can never count toward the requirement no
                          matter what&apos;s entered below.
                        </p>
                      </div>
                    )}
                    <StatusStamp state={fixtureStatusState(fixture)}>
                      {fixtureStatusLabel(fixture)}
                    </StatusStamp>
                    <div className="field">
                      <label
                        className="field__label"
                        htmlFor={`fixture-${fixture.id}-params`}
                      >
                        Fixture {fixture.id} params
                      </label>
                      <span className="admin__hint" id={`fixture-${fixture.id}-params-hint`}>
                        Inputs fed into the template
                      </span>
                      <textarea
                        id={`fixture-${fixture.id}-params`}
                        aria-describedby={`fixture-${fixture.id}-params-hint`}
                        className="workshop__feedback"
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
                    <div className="field">
                      <label
                        className="field__label"
                        htmlFor={`fixture-${fixture.id}-expected-result`}
                      >
                        Fixture {fixture.id} expected result
                      </label>
                      <span
                        className="admin__hint"
                        id={`fixture-${fixture.id}-result-hint`}
                      >
                        Answer the template should produce for these inputs
                      </span>
                      <textarea
                        id={`fixture-${fixture.id}-expected-result`}
                        aria-describedby={`fixture-${fixture.id}-result-hint`}
                        className="workshop__feedback"
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
                    <div className="actions">
                      <button type="button" className="btn" onClick={() => saveFixture(fixture)}>
                        Save fixture
                      </button>
                    </div>
                    {fixtureErrors[fixture.id] && (
                      <div className="errors">
                        <p className="errors__lead">{fixtureErrors[fixture.id]}</p>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </section>

            <section className="band">
              <div className="band__head">
                <h2>Guard cases</h2>
                <p className="band__note">System-generated and read-only.</p>
              </div>
              <p className="admin__lead">
                These prove the template correctly rejects invalid input or handles edge
                values. They&apos;re system-generated and read-only — no answer to confirm,
                no action needed here.
              </p>
              {guardFixtures.length === 0 && (
                <div className="notice notice--empty">
                  <IconCard />
                  <p className="notice__body">None for this draft.</p>
                </div>
              )}
              <ul className="admin__list">
                {guardFixtures.map((fixture) => (
                  <li className="admin__fixture" key={fixture.id}>
                    <span className="chip">{fixtureKindLabel(fixture)}</span>
                    <StatusStamp state={fixtureStatusState(fixture)}>
                      {fixtureStatusLabel(fixture)}
                    </StatusStamp>
                    {fixture.source_excerpt && (
                      <p className="scene__source">{fixture.source_excerpt}</p>
                    )}
                  </li>
                ))}
              </ul>
            </section>

            <section className="band">
              <div className="band__head">
                <h2>Approve</h2>
                <p className="band__note">
                  Verified fixtures: {qualifyingFixtureCount} / {requiredFixtureCount} required.
                  {' '}
                  Predicate coverage (guard cases confirmed to correctly reject bad input):
                  {' '}
                  {coverageCount} / {predicateCount}.
                </p>
              </div>

              <label className="field" htmlFor="template-name">
                <span className="field__label">Template name</span>
                <input
                  id="template-name"
                  type="text"
                  value={templateName}
                  onChange={(e) => setTemplateName(e.target.value)}
                />
              </label>

              <label className="combine" htmlFor="math-semantics-confirmed">
                <input
                  id="math-semantics-confirmed"
                  type="checkbox"
                  checked={mathSemanticsConfirmed}
                  onChange={(e) => setMathSemanticsConfirmed(e.target.checked)}
                />
                I confirm the mathematical semantics and preview are correct
              </label>

              <div className="actions">
                <button
                  type="button"
                  className="btn btn--ok"
                  onClick={submitApprove}
                  disabled={loading || !canApprove}
                >
                  <IconCheck size={16} />
                  Approve and publish
                </button>
              </div>
            </section>

            <section className="band">
              <div className="band__head">
                <h2>Reject with feedback</h2>
                <p className="band__note">
                  The worker regenerates from what you write here.
                </p>
              </div>
              <label className="field" htmlFor="reviewer-feedback">
                <span className="field__label">Feedback</span>
                <textarea
                  id="reviewer-feedback"
                  className="workshop__feedback"
                  aria-label="Feedback"
                  value={feedback}
                  onChange={(e) => setFeedback(e.target.value)}
                  rows={3}
                />
              </label>
              <div className="actions">
                <button
                  type="button"
                  className="btn btn--danger"
                  onClick={submitReject}
                  disabled={loading || !feedback.trim()}
                >
                  Reject and request refinement
                </button>
              </div>
            </section>
          </>
        )}
      </main>
    </div>
  )
}
