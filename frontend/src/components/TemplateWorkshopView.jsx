import { useState } from 'react'
import { formatClock } from '../lib/useElapsedSeconds'
import {
  IconAlert,
  IconCard,
  IconCheck,
  IconCross,
  IconPending,
  IconRedo,
  IconSeedling,
  IconWorking,
} from '../Icons'

const STALL_SECONDS = 60

// These endings are successful fallbacks: no unsafe or duplicate template was built.
const BENIGN_ENDINGS = new Set(['needs_manual', 'already_available'])

// The worker reports discrete stages, so a percentage between them would be fabricated.
const STAGES = [
  { key: 'filed', label: 'Problem filed' },
  { key: 'queued', label: 'Queued' },
  { key: 'building', label: 'Writing the template' },
  { key: 'ready', label: 'Ready for your approval' },
]

const STAGE_STATES = {
  filed: ['active', 'todo', 'todo', 'todo'],
  queued: ['done', 'done', 'todo', 'todo'],
  building: ['done', 'done', 'active', 'todo'],
  ready: ['done', 'done', 'done', 'done'],
  approved: ['done', 'done', 'done', 'done'],
  failed: ['done', 'failed', 'todo', 'todo'],
  needs_manual: ['done', 'done', 'failed', 'todo'],
}

const STATE_WORDS = {
  done: 'done',
  active: 'in progress',
  failed: 'failed',
  todo: 'not started',
}

function stageStates(stage) {
  const states = STAGE_STATES[stage] ?? STAGE_STATES.filed
  return STAGES.map((entry, index) => ({ ...entry, state: states[index] }))
}

function formatSeconds(seconds) {
  return `${Number(seconds.toFixed(2))} seconds`
}

function capitalize(word) {
  return word.charAt(0).toUpperCase() + word.slice(1)
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

      {draft.attempts.length > 0 && (
        <p className="workshop__current">Attempt {draft.revision} — the one to judge</p>
      )}

      <div className="workshop__grid">
        <div className="inset">
          {draft.preview_url ? (
            <>
              <img
                src={draft.preview_url}
                alt={`First frame of the visual built for this problem, attempt ${draft.revision}`}
              />
              <p className="inset__caption">First frame preview</p>
            </>
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
        I have reviewed the preview frame and it teaches this correctly
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

export function PendingWorkshopCard({ candidate, requesting, onRequest }) {
  return (
    <aside className="notice notice--teach workshop-card">
      <IconSeedling />
      <div className="workshop-card__body">
        <h3 className="workshop-card__title">
          {candidate ? candidate.one_line_summary : 'This problem'}
        </h3>
        <p className="workshop-card__caption">No built-in visual fits yet</p>
        <p className="notice__body">
          One can be built from this problem — you check it before anything uses it.
        </p>
        <div className="actions">
          <button className="btn" disabled={requesting} onClick={onRequest}>
            {requesting ? 'Starting…' : 'Build one for this problem'}
          </button>
        </div>
      </div>
    </aside>
  )
}

export function WorkshopBuildCard({
  build,
  candidate,
  draft,
  approvedName,
  refreshFailed,
  elapsed,
  showElapsed,
  busy,
  error,
  onApprove,
  onReject,
  onClear,
}) {
  const stalled = build.stage === 'queued' && elapsed >= STALL_SECONDS
  return (
    <section className="workshop" aria-labelledby={`workshop-title-${build.candidate_id}`}>
      <header className="workshop__head">
        <p className="workshop__caption" aria-live="polite">
          <span>{approvedName ? 'New visual ready to use' : 'Teaching a new visual'}</span>
          {showElapsed && (
            <span className="workshop__elapsed" aria-hidden="true">
              {formatClock(elapsed)}
            </span>
          )}
        </p>
        <h3 className="workshop__title" id={`workshop-title-${build.candidate_id}`}>
          {candidate ? candidate.one_line_summary : 'Untitled problem'}
        </h3>
      </header>

      {approvedName ? (
        <>
          <p className="band__note">
            {refreshFailed ? (
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
          onApprove={onApprove}
          onReject={onReject}
        />
      ) : BENIGN_ENDINGS.has(build.stage) ? (
        <>
          <div className="notice notice--fallback">
            <IconCard />
            <p className="notice__body">
              {build.error || 'No new visual was built for this problem.'}
            </p>
          </div>
          <ClearAction build={build} busy={busy} onClear={onClear} />
        </>
      ) : build.stage === 'failed' ? (
        <>
          <div className="notice notice--danger" role="alert">
            <IconAlert />
            <p className="notice__body">
              {build.error || 'This visual could not be built.'}
            </p>
          </div>
          <ClearAction build={build} busy={busy} onClear={onClear} />
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
}
