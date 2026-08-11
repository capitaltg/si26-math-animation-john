import { createContext, useCallback, useEffect, useRef, useState } from 'react'
import { Route, Routes } from 'react-router-dom'
import StageRail from '../components/StageRail'
import Queue from './Queue'
import Focus from './Focus'
import RenderToast from '../components/RenderToast'

async function responseJson(resp, fallbackMessage) {
  try {
    return await resp.json()
  } catch {
    throw new Error(resp.ok ? 'Server returned an invalid response' : fallbackMessage)
  }
}

function responseError(data, fallbackMessage) {
  return typeof data?.detail === 'string' ? data.detail : fallbackMessage
}

function deriveStage(candidates, options, storyboard) {
  if (storyboard?.some((s) => s.status === 'rendered')) return 'clips'
  if (storyboard) return 'storyboard'
  if (options) return 'visuals'
  if (candidates) return 'problems'
  return 'upload'
}

export const DemoContext = createContext(null)

export default function DemoShell() {
  const [candidates, setCandidates] = useState(null)
  const [selected, setSelected] = useState({})
  const [options, setOptions] = useState(null)
  const [picks, setPicks] = useState({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [storyboard, setStoryboard] = useState(null)
  const [drafts, setDrafts] = useState({})       // scene_id -> edited params
  const [fieldErrors, setFieldErrors] = useState({})  // scene_id -> [{loc,msg}]
  const [fileName, setFileName] = useState(null)
  const [pendingRenders, setPendingRenders] = useState(new Set())
  const [toasts, setToasts] = useState([])

  const pushToast = useCallback((toast) => {
    const id = crypto.randomUUID()
    setToasts((previous) => [...previous, { id, ...toast }])
    return id
  }, [])

  const dismissToast = useCallback((id) => {
    setToasts((previous) => previous.filter((toast) => toast.id !== id))
  }, [])

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
  useEffect(() => {
    if (renderInFlight.current) return
    if (!pendingRenders || pendingRenders.size === 0) return
    const controller = new AbortController()
    renderInFlight.current = true
    ;(async () => {
      try {
        const resp = await fetch('/render', {
          method: 'POST',
          credentials: 'include',
          signal: controller.signal,
        })
        if (!resp.ok) throw new Error(`Render request failed (HTTP ${resp.status})`)
        const data = await resp.json()
        const clips = Array.isArray(data.clips) ? data.clips : []
        const currentStoryboard = storyboardRef.current
        for (const clip of clips) {
          const scene = currentStoryboard?.find(s => s.scene_id === clip.scene_id)
          const title = scene?.detected_summary || 'Scene'
          if (clip.clip_url) {
            pushToast({ sceneId: clip.scene_id, title, clipUrl: clip.clip_url, kind: 'ok' })
          } else {
            pushToast({ sceneId: clip.scene_id, title, kind: 'warn', message: 'Render failed — open the problem to retry.' })
          }
        }
        setStoryboard(prev => prev?.map(s => {
          const clip = clips.find(c => c.scene_id === s.scene_id)
          if (!clip) return s
          return { ...s, status: clip.clip_url ? 'rendered' : 'render_failed', clip_url: clip.clip_url }
        }) ?? prev)
        setPendingRenders(new Set())
      } catch (err) {
        if (err.name !== 'AbortError') {
          pushToast({ title: 'Render error', kind: 'warn', message: err.message })
          setPendingRenders(new Set())
        }
      } finally {
        renderInFlight.current = false
      }
    })()
    return () => controller.abort()
  }, [pendingRenders])

  async function handleUpload(event) {
    event.preventDefault()
    const file = event.target.file.files[0]
    if (!file) return
    setError(null)
    setLoading(true)
    setOptions(null)
    setPicks({})
    setStoryboard(null)
    setDrafts({})
    setFieldErrors({})
    const form = new FormData()
    form.append('file', file)
    try {
      const resp = await fetch('/upload', {
        method: 'POST',
        body: form,
        credentials: 'include',
      })
      const data = await responseJson(resp, 'Upload failed')
      if (!resp.ok) throw new Error(responseError(data, 'Upload failed'))
      setCandidates(data.candidates)
      setSelected({})
      setFileName(file.name)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  function toggle(id) {
    setSelected((previous) => ({ ...previous, [id]: !previous[id] }))
  }

  async function handleGetOptions() {
    const candidateIds = Object.keys(selected).filter((id) => selected[id])
    if (candidateIds.length === 0) return
    setError(null)
    setLoading(true)
    try {
      const resp = await fetch('/options', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ candidate_ids: candidateIds }),
      })
      const data = await responseJson(resp, 'Could not get options')
      if (!resp.ok) throw new Error(responseError(data, 'Could not get options'))
      const initialPicks = Object.fromEntries(
        data.options
          .filter((item) => item.templates.length > 0)
          .map((item) => [item.candidate_id, item.templates[0].template]),
      )
      setOptions(data.options)
      setPicks(initialPicks)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  // Called after a meta-template draft is approved for one candidate: refetches
  // that candidate's options in place so the new template shows up without the
  // teacher re-requesting visualizations for everything. Only the approved
  // candidate's entry is replaced — other candidates' options and picks are
  // left untouched.
  async function refreshOptionsFor(candidateId) {
    setError(null)
    setLoading(true)
    try {
      const resp = await fetch('/options', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ candidate_ids: [candidateId] }),
      })
      const data = await responseJson(resp, 'Could not refresh visualizations')
      if (!resp.ok) throw new Error(responseError(data, 'Could not refresh visualizations'))
      const refreshed = data.options[0]
      if (!refreshed) return
      // If the teacher has since left the visuals stage (e.g. "Back to
      // candidates"), options is null — leave it null rather than reopening
      // an empty visuals stage with just this one entry.
      setOptions((previous) => {
        if (!previous) return previous
        const stillShown = previous.some((item) => item.candidate_id === candidateId)
        return stillShown
          ? previous.map((item) => (item.candidate_id === candidateId ? refreshed : item))
          : previous
      })
      // picks is reset to {} in lockstep with options whenever the teacher
      // leaves the visuals stage, so candidateId being a key here is itself
      // proof options is still showing it — no need to read the setOptions
      // updater's own decision, which isn't guaranteed to have run yet.
      if (refreshed.templates.length > 0) {
        setPicks((previous) => (candidateId in previous
          ? { ...previous, [candidateId]: refreshed.templates[0].template }
          : previous))
      }
    } catch (err) {
      setError(err.message)
      throw err
    } finally {
      setLoading(false)
    }
  }

  async function handleBuildStoryboard() {
    if (!options || options.some((item) => !picks[item.candidate_id])) return
    setError(null)
    setLoading(true)
    try {
      const body = options.map((item) => ({
        candidate_id: item.candidate_id,
        template: picks[item.candidate_id],
      }))
      const resp = await fetch('/storyboard', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ picks: body }),
      })
      const data = await responseJson(resp, 'Storyboard failed')
      if (!resp.ok) throw new Error(responseError(data, 'Storyboard failed'))
      setStoryboard(data.scenes)
      setDrafts(Object.fromEntries(data.scenes.map((s) => [s.scene_id, s.params])))
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  function replaceScene(updated, { resetDraft = false } = {}) {
    setStoryboard((prev) => prev.map((s) => (s.scene_id === updated.scene_id ? updated : s)))
    if (resetDraft) {
      setDrafts((prev) => ({ ...prev, [updated.scene_id]: updated.params }))
    }
  }

  async function sceneAction(sceneId, path, options, { resetDraft = false } = {}) {
    setError(null)
    setLoading(true)
    try {
      const resp = await fetch(`/storyboard/${sceneId}${path}`, {
        credentials: 'include',
        ...options,
      })
      const data = await responseJson(resp, 'Action failed')
      if (resp.status === 422) {
        const errors = Array.isArray(data?.detail?.errors) ? data.detail.errors : []
        if (errors.length === 0) {
          throw new Error(responseError(data, 'Could not save edits'))
        }
        setFieldErrors((prev) => ({ ...prev, [sceneId]: errors }))
        return
      }
      if (!resp.ok) throw new Error(responseError(data, 'Action failed'))
      setFieldErrors((prev) => ({ ...prev, [sceneId]: null }))
      replaceScene(data, { resetDraft })
    } catch (err) {
      setError(err.message)
      throw err
    } finally {
      setLoading(false)
    }
  }

  const saveEdits = (id, params = undefined) =>
    sceneAction(
      id,
      '',
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ params: params ?? drafts[id] }),
      },
      { resetDraft: true },
    )
  const setGrade = (id, grade) =>
    sceneAction(id, '', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ grade_level: Number(grade) }),
    })
  const retryScene = (id) => sceneAction(id, '/retry', { method: 'POST' }, { resetDraft: true })
  const approveScene = (id) => sceneAction(id, '/approve', { method: 'POST' })
  const rejectScene = (id) => sceneAction(id, '/reject', { method: 'POST' })

  const stage = deriveStage(candidates, options, storyboard)

  const value = {
    candidates,
    setCandidates,
    selected,
    setSelected,
    options,
    setOptions,
    picks,
    setPicks,
    loading,
    error,
    setError,
    storyboard,
    setStoryboard,
    drafts,
    setDrafts,
    fieldErrors,
    setFieldErrors,
    fileName,
    setFileName,
    pendingRenders,
    setPendingRenders,
    toasts,
    setToasts,
    pushToast,
    dismissToast,
    handleUpload,
    toggle,
    handleGetOptions,
    refreshOptionsFor,
    handleBuildStoryboard,
    sceneAction,
    saveEdits,
    setGrade,
    retryScene,
    approveScene,
    rejectScene,
  }

  return (
    <DemoContext.Provider value={value}>
      <div className="shell" data-testid="demo-shell" aria-label="demo">
        <StageRail current={stage} />
        <Routes>
          <Route index element={<Queue />} />
          <Route path="problem/:id" element={<Focus />} />
        </Routes>
        <RenderToast />
      </div>
    </DemoContext.Provider>
  )
}
