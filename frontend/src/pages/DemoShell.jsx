import { createContext, useCallback, useState } from 'react'
import { Route, Routes } from 'react-router-dom'
import StageRail from '../components/StageRail'
import Queue from './Queue'
import Focus from './Focus'
import RenderToast from '../components/RenderToast'
import RenderDock from '../components/RenderDock'
import useRenderQueue from '../lib/useRenderQueue'

async function responseJson(response, fallbackMessage) {
  try {
    return await response.json()
  } catch {
    throw new Error(response.ok ? 'Server returned an invalid response' : fallbackMessage)
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

let toastSeq = 0

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
  const [toasts, setToasts] = useState([])

  const pushToast = useCallback((toast) => {
    // Not crypto.randomUUID(): it is undefined outside a secure context, so on
    // an http:// demo host it would throw here — inside the render effect's
    // success path, which would cost the toast *and* the status update.
    const id = `toast-${toastSeq++}`
    setToasts((previous) => [...previous, { id, ...toast }])
    return id
  }, [])

  const dismissToast = useCallback((id) => {
    setToasts((previous) => previous.filter((toast) => toast.id !== id))
  }, [])

  const {
    pendingRenders,
    setPendingRenders,
    renderJob,
    dismissRenderJob,
  } = useRenderQueue({ storyboard, setStoryboard, pushToast })

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
      const response = await fetch('/upload', {
        method: 'POST',
        body: form,
        credentials: 'include',
      })
      const data = await responseJson(response, 'Upload failed')
      if (!response.ok) throw new Error(responseError(data, 'Upload failed'))
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
      const response = await fetch('/options', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ candidate_ids: candidateIds }),
      })
      const data = await responseJson(response, 'Could not get options')
      if (!response.ok) throw new Error(responseError(data, 'Could not get options'))
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
      const response = await fetch('/options', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ candidate_ids: [candidateId] }),
      })
      const data = await responseJson(response, 'Could not refresh visualizations')
      if (!response.ok) throw new Error(responseError(data, 'Could not refresh visualizations'))
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
      const response = await fetch('/storyboard', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ picks: body }),
      })
      const data = await responseJson(response, 'Storyboard failed')
      if (!response.ok) throw new Error(responseError(data, 'Storyboard failed'))
      setStoryboard(data.scenes)
      setDrafts(Object.fromEntries(data.scenes.map((scene) => [scene.scene_id, scene.params])))
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  function replaceScene(updated, { resetDraft = false } = {}) {
    setStoryboard((currentStoryboard) => currentStoryboard.map(
      (scene) => (scene.scene_id === updated.scene_id ? updated : scene),
    ))
    if (resetDraft) {
      setDrafts((currentDrafts) => ({ ...currentDrafts, [updated.scene_id]: updated.params }))
    }
  }

  async function sceneAction(sceneId, path, options, { resetDraft = false } = {}) {
    setError(null)
    setLoading(true)
    try {
      const response = await fetch(`/storyboard/${sceneId}${path}`, {
        credentials: 'include',
        ...options,
      })
      const data = await responseJson(response, 'Action failed')
      if (response.status === 422) {
        const errors = Array.isArray(data?.detail?.errors) ? data.detail.errors : []
        if (errors.length === 0) {
          throw new Error(responseError(data, 'Could not save edits'))
        }
        setFieldErrors((currentErrors) => ({ ...currentErrors, [sceneId]: errors }))
        return
      }
      if (!response.ok) throw new Error(responseError(data, 'Action failed'))
      setFieldErrors((currentErrors) => ({ ...currentErrors, [sceneId]: null }))
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
  const acknowledgeMismatch = (id) =>
    sceneAction(id, '/acknowledge-mismatch', { method: 'POST' })

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
    renderJob,
    dismissRenderJob,
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
    acknowledgeMismatch,
  }

  return (
    <DemoContext.Provider value={value}>
      {/* The dock is fixed to the bottom, so the shell pads out of its way
          while it is up rather than letting it cover a clip. */}
      <div
        className={`shell${renderJob ? ' shell--docked' : ''}`}
        data-testid="demo-shell"
        aria-label="demo"
      >
        <StageRail current={stage} />
        <Routes>
          <Route index element={<Queue />} />
          <Route path="problem/:id" element={<Focus />} />
        </Routes>
        <RenderDock />
        <RenderToast />
      </div>
    </DemoContext.Provider>
  )
}
