import { useCallback, useEffect, useRef, useState } from 'react'

export default function useRenderQueue({ storyboard, setStoryboard, pushToast }) {
  const [pendingRenders, setPendingRenders] = useState(new Set())
  const [renderJob, setRenderJob] = useState(null)

  // Fire-once render dispatch, not polling: /render is a synchronous batch
  // endpoint (POST only — there is no GET /storyboard/{id} to poll), so a
  // pendingRenders change triggers exactly one POST /render whose response
  // already carries the finished-or-failed status for every approved scene.
  // A successful clip always carries a clip_url; error/timeout clips never
  // do (see backend/app/routes.py _clip_result call sites), so clip_url
  // truthiness — not a literal status string — is the success signal.
  const renderInFlight = useRef(false)
  const storyboardRef = useRef(storyboard)
  useEffect(() => { storyboardRef.current = storyboard }, [storyboard])
  // Read inside the effect's async tail so a scene approved *after* the POST
  // went out is still recognised as requested when the response covers it.
  const pendingRef = useRef(pendingRenders)
  useEffect(() => { pendingRef.current = pendingRenders }, [pendingRenders])
  const jobOpen = useRef(false)
  const mountedRef = useRef(true)
  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])
  // Let an in-flight batch finish, then subtract only the scene ids it covered.
  // New ids survive for the next dispatch instead of being stranded by cleanup.
  useEffect(() => {
    // An empty queue means the batch this job was reporting on is over: the
    // dock stays up showing what it did, but the next approval opens a new job
    // with its own clock rather than reviving this one.
    if (!pendingRenders || pendingRenders.size === 0) {
      jobOpen.current = false
      return
    }
    if (renderInFlight.current) return
    renderInFlight.current = true
    // Stand the dock up now, not when the response lands — the wait is the part
    // that needs reporting. A follow-up POST from the drain path joins the same
    // open job (same clock, same rows) rather than starting a second one.
    const dispatched = [...pendingRenders]
    if (jobOpen.current) {
      setRenderJob((previous) => (previous
        ? { ...previous, ids: [...new Set([...previous.ids, ...dispatched])] }
        : { ids: dispatched, startedAt: Date.now(), results: {} }))
    } else {
      jobOpen.current = true
      setRenderJob({ ids: dispatched, startedAt: Date.now(), results: {} })
    }
    ;(async () => {
      const processed = new Set()
      try {
        const response = await fetch('/render', {
          method: 'POST',
          credentials: 'include',
        })
        if (!response.ok) throw new Error(`Render request failed (HTTP ${response.status})`)
        const data = await response.json()
        const clips = Array.isArray(data.clips) ? data.clips : []
        if (!mountedRef.current) return
        const currentStoryboard = storyboardRef.current
        // /render answers for *every* approved scene in the session, not just
        // the ones this call queued, and it serves an unchanged scene straight
        // from cache. Announcing all of them would re-toast clips the teacher
        // was already told about on an earlier batch, so only scenes still
        // waiting in the queue earn a notification — `processed` below still
        // takes the full list, because draining is a different question.
        const requested = pendingRef.current ?? new Set()
        const results = {}
        for (const clip of clips) {
          processed.add(clip.scene_id)
          // The dock tracks what the server last said about every scene in the
          // batch, so a clip that comes back fine on a follow-up call corrects
          // a row an earlier failure had marked failed. Only the notification
          // is scoped — a corrected row is not news worth a second toast.
          results[clip.scene_id] = clip.clip_url ? 'ok' : 'failed'
          if (!requested.has(clip.scene_id)) continue
          const scene = currentStoryboard?.find(
            (storyboardScene) => storyboardScene.scene_id === clip.scene_id,
          )
          const title = scene?.detected_summary || 'Scene'
          if (clip.clip_url) {
            pushToast({ sceneId: clip.scene_id, title, clipUrl: clip.clip_url, kind: 'ok' })
          } else {
            pushToast({ sceneId: clip.scene_id, title, kind: 'warn', message: 'Render failed — open the problem to retry.' })
          }
        }
        setRenderJob((previous) => (previous
          ? { ...previous, results: { ...previous.results, ...results } }
          : previous))
        setStoryboard((currentStoryboardState) => currentStoryboardState?.map((scene) => {
          const clip = clips.find((candidateClip) => candidateClip.scene_id === scene.scene_id)
          if (!clip) return scene
          return { ...scene, status: clip.clip_url ? 'rendered' : 'render_failed', clip_url: clip.clip_url }
        }) ?? currentStoryboardState)
        setPendingRenders((currentPending) => {
          const next = new Set(currentPending)
          for (const id of processed) next.delete(id)
          return next
        })
      } catch (err) {
        if (!mountedRef.current) return
        pushToast({ title: 'Render error', kind: 'warn', message: err.message })
        // The dock must not read "finished" over rows that never resolved: this
        // call failed as a unit, so every scene *it carried* failed. Scenes
        // approved after it went out are untouched — nothing was attempted for
        // them yet.
        setRenderJob((previous) => {
          if (!previous) return previous
          // Merge failures so verdicts from earlier calls remain authoritative.
          const failures = Object.fromEntries(
            dispatched
              .filter((id) => previous.results[id] === undefined)
              .map((id) => [id, 'failed']),
          )
          return { ...previous, results: { ...previous.results, ...failures } }
        })
        // Drop only this call's ids; later approvals still need dispatching.
        setPendingRenders((currentPending) => {
          const next = new Set(currentPending)
          for (const id of dispatched) next.delete(id)
          return next
        })
      } finally {
        renderInFlight.current = false
      }
    })()
    // NO cleanup — do NOT abort in flight; see comment above.
  }, [pendingRenders])

  const dismissRenderJob = useCallback(() => setRenderJob(null), [])

  return { pendingRenders, setPendingRenders, renderJob, dismissRenderJob }
}
