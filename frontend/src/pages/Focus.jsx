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
    saveEdits, setDrafts, approveScene, rejectScene, retryScene, setPendingRenders,
  } = ctx
  const timerRef = useRef(null)
  useEffect(() => () => { if (timerRef.current) clearTimeout(timerRef.current) }, [])

  // Compute derived values
  const idx = storyboard ? storyboard.findIndex(s => s.scene_id === id) : -1
  const scene = idx >= 0 ? storyboard[idx] : null

  // templates + rejected — placeholders until template alternatives are on scene
  const templates = useMemo(
    () => (scene?.template ? [{ template: scene.template, matched: true }] : []),
    [scene?.template],
  )

  // Early return guard (after all hooks)
  if (!scene) return <Navigate to="/demo" replace />

  const total = storyboard.length
  const currentDraft = drafts[scene.scene_id] ?? scene.params
  const originalParams = scene.params

  // debounced autosave: on draft change, wait 250ms then persist
  const handleParamsChange = (nextParams) => {
    setDrafts(prev => ({ ...prev, [scene.scene_id]: nextParams }))
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => saveEdits(scene.scene_id), 250)
  }
  const handleParamsRevert = (nextParams) => {
    setDrafts(prev => ({ ...prev, [scene.scene_id]: nextParams }))
    if (timerRef.current) clearTimeout(timerRef.current)
    saveEdits(scene.scene_id) // revert immediately
  }

  const rejected = [] // no scene-level rejected list yet

  const clipUrl = null // Task 12 will feed rendered clip URLs

  const handleApprove = async () => {
    await approveScene(scene.scene_id)
    setPendingRenders(prev => {
      const next = new Set(prev)
      next.add(scene.scene_id)
      return next
    })
    navigate('/demo')
  }

  return (
    <article className="focus" aria-label={`Problem ${idx + 1} of ${total}`}>
      <header className="focus__top">
        <Link to="/demo" className="btn btn--ghost">← Back to queue</Link>
        <span className="focus__count">Problem {idx + 1} of {total}</span>
      </header>

      <TemplateTabs
        templates={templates}
        rejected={rejected}
        activeTemplate={scene.template}
        onSwitch={() => { /* alternate-template switching is out of scope this task */ }}
      />

      <div className="focus__split">
        <section className="focus__left">
          <PreviewStage scene={scene} clipUrl={clipUrl} />
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
        <button className="btn btn--danger" onClick={() => rejectScene(scene.scene_id)} disabled={loading}>Reject</button>
        <button className="btn btn--ghost" onClick={() => retryScene(scene.scene_id)} disabled={loading}>Retry</button>
        <button className="btn btn--primary" onClick={handleApprove} disabled={loading}>Approve &amp; render →</button>
      </footer>
    </article>
  )
}
