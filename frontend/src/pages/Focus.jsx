import { useContext, useEffect, useMemo, useRef } from 'react'
import { Link, Navigate, useNavigate, useParams } from 'react-router-dom'
import { DemoContext } from './DemoShell'
import TemplateTabs from '../components/TemplateTabs'
import ParamTable from '../components/ParamTable'
import GatesDisclosure from '../components/GatesDisclosure'
import SolutionCard from '../components/SolutionCard'
import PreviewStage from '../components/PreviewStage'

export default function Focus() {
  // All hooks first (before any conditional returns)
  const { id } = useParams()
  const navigate = useNavigate()
  const ctx = useContext(DemoContext)
  const {
    storyboard, drafts, fieldErrors, loading,
    saveEdits, setDrafts, approveScene, rejectScene, retryScene,
    pendingRenders, setPendingRenders,
    acknowledgeMismatch,
  } = ctx
  const timerRef = useRef(null)
  useEffect(() => () => { if (timerRef.current) clearTimeout(timerRef.current) }, [])

  const sceneIndex = storyboard
    ? storyboard.findIndex((storyboardScene) => storyboardScene.scene_id === id)
    : -1
  const scene = sceneIndex >= 0 ? storyboard[sceneIndex] : null

  // The scene exposes only its selected template until alternatives are available.
  const templates = useMemo(
    () => (scene?.template ? [{ template: scene.template, matched: true }] : []),
    [scene?.template],
  )

  // Early return guard (after all hooks)
  if (!scene) return <Navigate to="/demo" replace />

  const total = storyboard.length
  const currentDraft = drafts[scene.scene_id] ?? scene.params
  const originalParams = scene.params

  // Debounce live edits; explicit reverts persist immediately.
  const handleParamsChange = (nextParams) => {
    setDrafts((currentDrafts) => ({ ...currentDrafts, [scene.scene_id]: nextParams }))
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => { saveEdits(scene.scene_id, nextParams)?.catch?.(() => {}) }, 250)
  }
  const handleParamsRevert = (nextParams) => {
    setDrafts((currentDrafts) => ({ ...currentDrafts, [scene.scene_id]: nextParams }))
    if (timerRef.current) clearTimeout(timerRef.current)
    saveEdits(scene.scene_id, nextParams)?.catch?.(() => {})
  }

  const rejected = [] // no scene-level rejected list yet

  const clipUrl = scene.clip_url ?? null

  // Backend rejects /approve with 409 when scene.mismatch is present and the
  // teacher has not acknowledged it. Surface the delta and require an explicit
  // acknowledge action before the primary CTA is enabled.
  const mismatch = scene.mismatch
  const needsMismatchAck = !!mismatch && !scene.mismatch_acknowledged

  const handleAcknowledgeMismatch = async () => {
    try { await acknowledgeMismatch(scene.scene_id) } catch { /* stay on Focus */ }
  }

  const handleApprove = async () => {
    try {
      await approveScene(scene.scene_id)
    } catch {
      return // stay on Focus so user sees `error` and can retry
    }
    setPendingRenders((currentPending) => {
      const next = new Set(currentPending)
      next.add(scene.scene_id)
      return next
    })
    navigate('/demo')
  }

  return (
    <article className="focus" aria-label={`Problem ${sceneIndex + 1} of ${total}`}>
      <header className="focus__top">
        <Link to="/demo" className="btn btn--ghost">← Back to queue</Link>
        <span className="focus__count">Problem {sceneIndex + 1} of {total}</span>
      </header>

      <TemplateTabs
        templates={templates}
        rejected={rejected}
        activeTemplate={scene.template}
        onSwitch={() => { /* Alternate-template switching is not implemented. */ }}
      />

      {mismatch && (
        <div
          className={`mismatch${scene.mismatch_acknowledged ? ' mismatch--acknowledged' : ''}`}
          role="alert"
          aria-live="polite"
        >
          <div className="mismatch__body">
            <div className="mismatch__title">
              {scene.mismatch_acknowledged
                ? 'Mismatch acknowledged'
                : "Slide answer doesn't match the math"}
            </div>
            <div className="mismatch__delta">
              <span><span className="mismatch__k">Slide says</span> <strong>{String(mismatch.stated)}</strong></span>
              <span><span className="mismatch__k">Python computes</span> <strong>{String(mismatch.computed)}</strong></span>
            </div>
            {!scene.mismatch_acknowledged && (
              <p className="mismatch__hint">
                Edit values on the right to match the slide, or acknowledge to render the Python-verified value.
              </p>
            )}
          </div>
          {!scene.mismatch_acknowledged && (
            <button
              type="button"
              className="btn btn--ghost mismatch__ack"
              onClick={handleAcknowledgeMismatch}
              disabled={loading}
            >
              Acknowledge &amp; keep going
            </button>
          )}
        </div>
      )}

      <div className="focus__split">
        <section className="focus__left">
          <PreviewStage scene={scene} clipUrl={clipUrl} rendering={pendingRenders.has(scene.scene_id)} />
          <SolutionCard answer={scene.computed_answer} />
          <GatesDisclosure gates={scene.gates ?? []} />
        </section>
        <section className="focus__right">
          <ParamTable
            key={`${scene.scene_id}:${JSON.stringify(scene.params)}`}
            params={currentDraft}
            schema={scene.params_schema}
            errors={fieldErrors[scene.scene_id] ?? []}
            original={originalParams}
            onChange={handleParamsChange}
            onRevert={handleParamsRevert}
          />
        </section>
      </div>

      <footer className="focus__actions">
        <button className="btn btn--danger" onClick={() => rejectScene(scene.scene_id).catch(() => {})} disabled={loading}>Reject</button>
        <button className="btn btn--ghost" onClick={() => retryScene(scene.scene_id).catch(() => {})} disabled={loading}>Retry</button>
        <button
          className="btn btn--primary"
          onClick={handleApprove}
          disabled={loading || needsMismatchAck}
          title={needsMismatchAck ? 'Acknowledge the mismatch first' : undefined}
        >
          Approve &amp; render →
        </button>
      </footer>
    </article>
  )
}
