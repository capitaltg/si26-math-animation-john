import { IconAlert, IconCheck, IconPending } from './Icons'

// One expandable row per named gate. The audience needs to see, on any surface
// that shows scene state, that N named gates actually ran — not a single
// generic "preview rendered" stamp. Categories mirror the meta-flow taxonomy
// so gates read as one vocabulary across surfaces.

const STATE_WORDS = {
  passed: 'passed',
  failed: 'failed',
  pending: 'pending',
}

// Backend gate `status` is passed/failed/pending; the shared stamp CSS keys off
// done/failed/todo, so map into the surface vocabulary before rendering.
const STATE_TO_STAMP = {
  passed: 'done',
  failed: 'failed',
  pending: 'todo',
}

const STATE_ICON = {
  passed: IconCheck,
  failed: IconAlert,
  pending: IconPending,
}

function GateMark({ status }) {
  const Icon = STATE_ICON[status] || IconPending
  return (
    <span className="stamp__mark">
      <Icon size={16} />
    </span>
  )
}

// A gate `{ name, category, status, duration_ms }`; `details` is optional
// free-form text shown when the row is expanded. Every row is expandable so
// the audience can always drill into status and timing per gate.
export default function GatePanel({ gates }) {
  if (!gates || gates.length === 0) return null
  return (
    <ul className="stamps gate-panel">
      {gates.map((gate) => {
        const state = gate.status || 'pending'
        const stamp = STATE_TO_STAMP[state] || 'todo'
        const detail = gate.details
        const ms = typeof gate.duration_ms === 'number' ? gate.duration_ms : null
        return (
          <li key={gate.name} className="stamp gate" data-state={stamp}>
            <details>
              <summary>
                <GateMark status={state} />
                <span className="gate__name">{gate.name}</span>
                <span className="chip gate__category">{gate.category}</span>
                <span className="sr-only"> — {STATE_WORDS[state]}</span>
              </summary>
              <p className="gate__detail">
                {detail || `Status: ${STATE_WORDS[state]}`}
              </p>
              {ms !== null && (
                <p className="gate__timing">{`${Math.round(ms)} ms`}</p>
              )}
            </details>
          </li>
        )
      })}
    </ul>
  )
}
