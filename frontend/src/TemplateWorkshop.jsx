import { useCallback, useEffect, useState } from 'react'
import {
  IconAlert,
  IconCard,
  IconCheck,
  IconCross,
  IconPending,
  IconRedo,
  IconSeedling,
  IconWorking,
} from './Icons'

// How long a queued build may sit before we say so. The generator is a separate
// process (scripts/meta_worker.py); a queue nobody is draining must not read as
// progress, so past this point the band says nothing has picked the work up.
const STALL_SECONDS = 60
const POLL_MS = 4000

const TERMINAL_STAGES = new Set([
  'ready', 'approved', 'failed', 'needs_manual', 'already_available',
])

// Two of these end the build without anything having gone wrong: automatic
// generation giving up leaves the labelled text card standing, and a template
// this session can already reach was never a problem. A fallback is a success
// state in this product and must not be styled as failure — only a genuine
// failure earns `danger`.
const BENIGN_ENDINGS = new Set(['needs_manual', 'already_available'])

// The four stages a teacher watches. Discrete and countable, every one real and
// reachable: there is no progress stream inside the worker's generation loop, so
// a percentage or a bar here would be invented. Same rule the render dock obeys.
const STAGES = [
  { key: 'filed', label: 'Problem filed' },
  { key: 'queued', label: 'Queued' },
  { key: 'building', label: 'Writing the template' },
  { key: 'ready', label: 'Ready for your approval' },
]

// Written out per stage rather than derived from an index, because two of these
// rows are accomplished facts and two are work: being queued is *done* the
// moment it is true, so at that point nothing is in progress — which is honest,
// and is exactly the state the stall note below explains if it lasts.
const STAGE_STATES = {
  filed: ['active', 'todo', 'todo', 'todo'],
  queued: ['done', 'done', 'todo', 'todo'],
  building: ['done', 'done', 'active', 'todo'],
  ready: ['done', 'done', 'done', 'done'],
  approved: ['done', 'done', 'done', 'done'],
  failed: ['done', 'failed', 'todo', 'todo'],
  needs_manual: ['done', 'done', 'failed', 'todo'],
}

function stageStates(stage) {
  const states = STAGE_STATES[stage] ?? STAGE_STATES.filed
  return STAGES.map((entry, index) => ({ ...entry, state: states[index] }))
}

const STATE_WORDS = {
  done: 'done',
  active: 'in progress',
  failed: 'failed',
  todo: 'not started',
}

function formatElapsed(seconds) {
  const minutes = Math.floor(seconds / 60)
  return `${minutes}:${String(seconds % 60).padStart(2, '0')}`
}

// 12.5 seconds, not 12.50; 8 seconds, not 8.0.
function formatSeconds(seconds) {
  return `${Number(seconds.toFixed(2))} seconds`
}

function capitalize(word) {
  return word.charAt(0).toUpperCase() + word.slice(1)
}

async function responseJson(resp) {
  try {
    return await resp.json()
  } catch {
    return null
  }
}

function errorFrom(data, fallback) {
  return typeof data?.detail === 'string' ? data.detail : fallback
}

function StageList({ stage }) {
  const stages = stageStates(stage)
  const done = stages.filter((entry) => entry.state === 'done').length
  return (
    <div>
      <p className="stamps__count">{done} of {stages.length} stages complete</p>
      <ul className="stamps">
        {stages.map((entry) => (
          <li className="stamp" key={entry.key} data-state={entry.state}>
            <span className="stamp__mark">
              {entry.state === 'done' ? <IconCheck size={16} />
                : entry.state === 'active' ? <IconWorking size={16} />
                : entry.state === 'failed' ? <IconAlert size={16} />
                : <IconPending size={16} />}
            </span>
            {entry.label}
            {/* The marks are decorative, so the state is carried in text too. */}
            <span className="sr-only"> — {STATE_WORDS[entry.state]}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function Attempts({ attempts }) {
  if (attempts.length === 0) return null
  return (
    <div className="workshop__history">
      <p className="workshop__history-lead">
        What you turned down before, oldest first.
      </p>
      <ul className="workshop__attempts" aria-label="Earlier attempts">
        {attempts.map((attempt) => (
          <li className="workshop__attempt" key={attempt.revision}>
            <div>
              <p className="workshop__attempt-title">Attempt {attempt.revision}</p>
              {attempt.feedback && (
                <p className="workshop__attempt-note">“{attempt.feedback}”</p>
              )}
            </div>
            {attempt.preview_url && (
              <div className="inset inset--thumb">
                <img
                  src={attempt.preview_url}
                  alt={`First frame of attempt ${attempt.revision}`}
                />
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

function ClearAction({ build, busy, onClear }) {
  return (
    <div className="actions">
      <button className="btn" disabled={busy} onClick={() => onClear(build)}>
        <IconRedo size={16} />
        Try this problem again
      </button>
    </div>
  )
}

function ReadyBand({ draft, onApprove, onReject, busy, error }) {
  const [name, setName] = useState(draft.suggested_template_name)
  const [confirmed, setConfirmed] = useState(false)
  const [rejecting, setRejecting] = useState(false)
  const [feedback, setFeedback] = useState('')

  const canApprove = Boolean(name.trim()) && confirmed && !busy

  return (
    <>
      <Attempts attempts={draft.attempts} />

      {/* With history above, the current attempt needs naming or it reads as a
          continuation of the last rejected one. */}
      {draft.attempts.length > 0 && (
        <p className="workshop__current">Attempt {draft.revision} — the one to judge</p>
      )}

      <div className="workshop__grid">
        <div className="inset">
          {draft.preview_url ? (
            <img
              src={draft.preview_url}
              alt={`First frame of the visual built for this problem, attempt ${draft.revision}`}
            />
          ) : (
            <div className="inset__empty">Preview unavailable</div>
          )}
        </div>

        <div>
          <p className="workshop__objective">{draft.learning_objective}</p>
          <p className="workshop__caption">What it does, in order</p>
          <ol className="workshop__beats">
            {draft.beats.map((beat) => (
              <li key={beat.id}>{capitalize(beat.kind)} · {beat.intent}</li>
            ))}
          </ol>
          <p className="workshop__duration">
            Runs for {formatSeconds(draft.total_duration_seconds)}
          </p>
        </div>
      </div>

      {error && (
        <div className="notice notice--danger" role="alert">
          <IconAlert />
          <p className="notice__body">{error}</p>
        </div>
      )}

      <label className="field workshop__name">
        <span className="field__label">Name this visual</span>
        <input
          type="text"
          value={name}
          disabled={busy}
          onChange={(event) => setName(event.target.value)}
        />
      </label>

      <label className="combine">
        <input
          type="checkbox"
          checked={confirmed}
          disabled={busy}
          onChange={(event) => setConfirmed(event.target.checked)}
        />
        I have watched the preview and it teaches this correctly
      </label>

      <div className="actions">
        <button
          className="btn btn--ok"
          disabled={!canApprove}
          onClick={() => onApprove(name.trim())}
        >
          <IconCheck size={16} />
          Looks right — use this
        </button>
        <button
          className="btn btn--danger"
          disabled={busy}
          onClick={() => setRejecting((open) => !open)}
        >
          <IconCross size={16} />
          Not right — try again
        </button>
      </div>

      {rejecting && (
        <div className="workshop__reject">
          <label className="field">
            <span className="field__label">What is wrong with it?</span>
            <textarea
              className="workshop__feedback"
              rows={3}
              value={feedback}
              disabled={busy}
              onChange={(event) => setFeedback(event.target.value)}
            />
          </label>
          <p className="workshop__cost">
            Another attempt takes a few minutes, and you have{' '}
            {draft.attempts_remaining} attempts left.
          </p>
          <button
            className="btn"
            disabled={busy || !feedback.trim()}
            onClick={() => onReject(feedback.trim())}
          >
            Try again with this note
          </button>
        </div>
      )}
    </>
  )
}

export default function TemplateWorkshop({ candidates, unsupportedCandidateIds, onApproved }) {
  const [enabled, setEnabled] = useState(false)
  const [builds, setBuilds] = useState([])
  const [drafts, setDrafts] = useState({})
  const [approved, setApproved] = useState({})   // candidate_id -> template name
  const [refreshFailed, setRefreshFailed] = useState({})  // candidate_id -> bool
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [requestError, setRequestError] = useState(null)

  useEffect(() => {
    let live = true
    fetch('/meta/my/capabilities', { credentials: 'include' })
      .then(responseJson)
      .then((data) => {
        if (live) setEnabled(Boolean(data?.enabled))
      })
      .catch(() => {})
    return () => {
      live = false
    }
  }, [])

  const loadBuilds = useCallback(async () => {
    try {
      const resp = await fetch('/meta/my/builds', { credentials: 'include' })
      const data = await responseJson(resp)
      if (resp.ok && Array.isArray(data)) setBuilds(data)
    } catch {
      // A dropped poll is not worth a banner; the next one reports the truth.
    }
  }, [])

  // One load as soon as the feature is available, whether or not this page view
  // is the one that asked. The request lives on the server session, so a teacher
  // who reloads mid-build must still find their build here.
  useEffect(() => {
    if (enabled) loadBuilds()
  }, [enabled, loadBuilds])

  // Then poll only while something is actually in flight, and never after
  // unmount. A finished build has nothing left to report, so continuing to ask
  // would be noise against a server answering the same thing every time.
  const anyRunning = builds.some((build) => !TERMINAL_STAGES.has(build.stage))
  useEffect(() => {
    if (!enabled || !anyRunning) return undefined
    const timer = setInterval(loadBuilds, POLL_MS)
    return () => clearInterval(timer)
  }, [enabled, anyRunning, loadBuilds])

  // Fetch each ready build's draft once. Keyed by draft id, so a refinement
  // arriving as a new revision is fetched again rather than showing the old one.
  useEffect(() => {
    const wanted = builds
      .filter((build) => build.draft_id && !drafts[build.draft_id])
      .map((build) => build.draft_id)
    if (wanted.length === 0) return
    let live = true
    Promise.all(wanted.map(async (draftId) => {
      const resp = await fetch(`/meta/my/drafts/${draftId}`, { credentials: 'include' })
      const data = await responseJson(resp)
      return resp.ok && data ? [draftId, data] : null
    }))
      .then((loaded) => {
        if (!live) return
        const entries = loaded.filter(Boolean)
        if (entries.length > 0) setDrafts((current) => ({ ...current, ...Object.fromEntries(entries) }))
      })
      .catch(() => {})
    return () => {
      live = false
    }
  }, [builds, drafts])

  async function requestBuild(candidateId) {
    setRequestError(null)
    setBusy(true)
    try {
      const resp = await fetch('/meta/my/builds', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ candidate_id: candidateId }),
      })
      const data = await responseJson(resp)
      if (!resp.ok) throw new Error(errorFrom(data, 'Could not start building a visual'))
      await loadBuilds()
    } catch (err) {
      setRequestError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function approveDraft(build, templateName) {
    setError(null)
    setBusy(true)
    try {
      const resp = await fetch(`/meta/my/drafts/${build.draft_id}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          template_name: templateName,
          math_semantics_confirmed: true,
        }),
      })
      const data = await responseJson(resp)
      if (!resp.ok) throw new Error(errorFrom(data, 'Could not use this visual'))
      let failed = false
      try {
        // The approval itself already succeeded below; a failure here only
        // means the option list didn't refresh, not that approval failed.
        await onApproved?.(data.template_name, build.candidate_id)
      } catch {
        failed = true
      }
      setRefreshFailed((current) => ({ ...current, [build.candidate_id]: failed }))
      setApproved((current) => ({ ...current, [build.candidate_id]: data.template_name }))
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  // Every terminal-but-empty state needs a way out: the entry offer below is
  // hidden for any candidate that has a build record, so without this a failed
  // or refused build would be the last word on that problem for the session.
  async function clearBuild(build) {
    setError(null)
    setBusy(true)
    try {
      const resp = await fetch(`/meta/my/builds/${build.candidate_id}`, {
        method: 'DELETE',
        credentials: 'include',
      })
      if (!resp.ok) {
        const data = await responseJson(resp)
        throw new Error(errorFrom(data, 'Could not clear this attempt'))
      }
      setBuilds((current) => current.filter((entry) => entry.candidate_id !== build.candidate_id))
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function rejectDraft(build, feedback) {
    setError(null)
    setBusy(true)
    try {
      const resp = await fetch(`/meta/my/drafts/${build.draft_id}/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ feedback }),
      })
      const data = await responseJson(resp)
      if (!resp.ok) throw new Error(errorFrom(data, 'Could not ask for another attempt'))
      if (data?.requeued === false) {
        setError(
          'Automatic generation has run out of attempts for this problem. The '
          + 'labelled text card still works.',
        )
      }
      await loadBuilds()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (!enabled) return null

  const pending = unsupportedCandidateIds.filter(
    (candidateId) => !builds.some((build) => build.candidate_id === candidateId),
  )

  return (
    <>
      {pending.map((candidateId) => {
        const candidate = candidates.find((entry) => entry.candidate_id === candidateId)
        return (
          <div className="notice notice--teach" key={candidateId}>
            <IconSeedling />
            <div>
              <p className="notice__body">
                No built-in visual fits {candidate ? `“${candidate.one_line_summary}”` : 'this problem'} yet.
                One can be built from it — you check it before anything uses it.
              </p>
              <div className="actions">
                <button className="btn" disabled={busy} onClick={() => requestBuild(candidateId)}>
                  Build one for this problem
                </button>
              </div>
            </div>
          </div>
        )
      })}

      {requestError && (
        <div className="notice notice--danger" role="alert">
          <IconAlert />
          <p className="notice__body">{requestError}</p>
        </div>
      )}

      {builds.map((build) => {
        const draft = build.draft_id ? drafts[build.draft_id] : null
        const approvedName = approved[build.candidate_id]
        const stalled = build.stage === 'queued' && build.elapsed_seconds >= STALL_SECONDS
        return (
          <section className="band" key={build.candidate_id}>
            <div className="band__head">
              {/* Only the heading announces. The clock is excluded: it changes
                  every second and would talk over everything else. */}
              <h2 aria-live="polite">
                {approvedName ? 'New visual ready to use' : 'Teaching a new visual'}
              </h2>
              {!TERMINAL_STAGES.has(build.stage) && (
                <span className="dock__elapsed" aria-hidden="true">
                  {formatElapsed(build.elapsed_seconds)}
                </span>
              )}
            </div>

            {approvedName ? (
              <>
                <p className="band__note">
                  {refreshFailed[build.candidate_id] ? (
                    <>
                      “{approvedName}” is available in this session, but the
                      option list did not refresh automatically. Ask for
                      visualizations again to pick it up.
                    </>
                  ) : (
                    <>
                      “{approvedName}” is available in this session and has
                      been added as an option for this problem.
                    </>
                  )}
                </p>
              </>
            ) : build.stage === 'ready' && draft ? (
              <ReadyBand
                draft={draft}
                busy={busy}
                error={error}
                onApprove={(name) => approveDraft(build, name)}
                onReject={(feedback) => rejectDraft(build, feedback)}
              />
            ) : BENIGN_ENDINGS.has(build.stage) ? (
              <>
                <div className="notice notice--fallback">
                  <IconCard />
                  <p className="notice__body">
                    {build.error || 'No new visual was built for this problem.'}
                  </p>
                </div>
                <ClearAction build={build} busy={busy} onClear={clearBuild} />
              </>
            ) : build.stage === 'failed' ? (
              <>
                <div className="notice notice--danger" role="alert">
                  <IconAlert />
                  <p className="notice__body">
                    {build.error || 'This visual could not be built.'}
                  </p>
                </div>
                <ClearAction build={build} busy={busy} onClear={clearBuild} />
              </>
            ) : (
              <>
                <StageList stage={build.stage} />
                <p className="workshop__wait">
                  Writing a new visual takes minutes, not seconds — you can carry
                  on with the rest of your deck below.
                </p>
                {stalled && (
                  <p className="workshop__stalled">
                    The generator has not started on this yet.
                  </p>
                )}
                {error && (
                  <div className="notice notice--danger" role="alert">
                    <IconAlert />
                    <p className="notice__body">{error}</p>
                  </div>
                )}
              </>
            )}
          </section>
        )
      })}
    </>
  )
}
