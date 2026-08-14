import { useContext } from 'react'
import { DemoContext } from '../pages/DemoShell'
import { templateLabel } from '../lib/templates'
import useElapsedSeconds, { formatClock } from '../lib/useElapsedSeconds'
import { IconAlert, IconCheck, IconPending, IconWorking } from '../Icons'

// POST /render has no progress stream, so the dock reports only observable
// per-scene states and elapsed time; percentages and ETAs would be fabricated.
const ROW_STATES = {
  rendering: { word: 'rendering', Mark: IconWorking },
  rendered: { word: 'rendered', Mark: IconCheck },
  failed: { word: 'failed', Mark: IconAlert },
  queued: { word: 'queued', Mark: IconPending },
}

function DockRow({ name, state }) {
  const { word, Mark } = ROW_STATES[state] ?? ROW_STATES.queued
  return (
    <li className="dock__row" data-state={state}>
      {/* State is carried by the mark's shape plus the sr-only word, never by
          colour alone — the marks are aria-hidden. */}
      <span className="dock__mark"><Mark size={16} /></span>
      <span className="dock__row-name">{name}</span>
      <span className="sr-only"> — {word}</span>
    </li>
  )
}

export default function RenderDock() {
  const { renderJob, pendingRenders, storyboard, dismissRenderJob } = useContext(DemoContext)
  const running = (pendingRenders?.size ?? 0) > 0
  // Freezes at the time it took once the batch is done, rather than resetting.
  const elapsed = useElapsedSeconds(renderJob?.startedAt ?? null, running)

  if (!renderJob) return null

  // Every scene the batch has touched *plus* everything still waiting on it: a
  // scene approved while the POST was already out has no row of its own yet, and
  // leaving it off would contradict the queue, which is already showing it as
  // rendering. `renderJob.ids` is what has actually been dispatched, so anything
  // outside it is honestly still queued rather than in progress.
  const ids = [...new Set([...renderJob.ids, ...(pendingRenders ?? [])])]
  const rows = ids.map((sceneId) => {
    const scene = storyboard?.find((entry) => entry.scene_id === sceneId)
    // `template` is nullable on a scene, so the label is only half of the row
    // when it is missing; the summary alone still identifies the problem.
    const label = scene?.template ? `${templateLabel(scene.template)} · ` : ''
    const name = scene ? `${label}${scene.detected_summary ?? sceneId}` : sceneId
    const result = renderJob.results[sceneId]
    const state = result === 'ok' ? 'rendered'
      : result === 'failed' ? 'failed'
        : running && renderJob.ids.includes(sceneId) ? 'rendering'
          : 'queued'
    return { sceneId, name, state }
  })

  const failed = rows.filter((row) => row.state === 'failed').length
  // Counts what is still outstanding, not the whole batch: once a drain has
  // landed some clips — or a failed call has resolved part of the job — saying
  // "Rendering 3 clips" over one remaining scene is just wrong.
  const outstanding = rows.filter((row) => row.state === 'rendering' || row.state === 'queued').length
  const heading = running
    ? `Rendering ${outstanding} ${outstanding === 1 ? 'clip' : 'clips'}`
    : failed > 0
      ? `Render finished — ${failed} failed`
      : 'Render finished'

  return (
    <section className="dock" aria-label="Render progress">
      <div className="dock__inner">
        <div className="dock__head">
          <span className="dock__head-mark">
            {running ? <IconWorking size={20} /> : failed > 0 ? <IconAlert size={20} /> : <IconCheck size={20} />}
          </span>
          {/* The heading is the spoken account of the batch. The clock is
              aria-hidden: it mutates every second and would talk over it. */}
          <h2 className="dock__title" aria-live="polite">{heading}</h2>
          <span className="dock__clock" aria-hidden="true">{formatClock(elapsed)}</span>
          {running ? (
            <span className="dock__note">A minute or two per clip — you can keep working.</span>
          ) : (
            <button type="button" className="btn btn--ghost dock__hide" onClick={dismissRenderJob}>
              Hide
            </button>
          )}
        </div>
        <ul className="dock__rows">
          {rows.map((row) => (
            <DockRow key={row.sceneId} name={row.name} state={row.state} />
          ))}
        </ul>
      </div>
    </section>
  )
}
