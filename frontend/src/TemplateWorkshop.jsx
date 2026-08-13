import { useCallback, useEffect, useState } from 'react'
import useElapsedSeconds from './lib/useElapsedSeconds'
import { IconAlert } from './Icons'
import { PendingWorkshopCard, WorkshopBuildCard } from './components/TemplateWorkshopView'

const POLL_MS = 4000

const TERMINAL_STAGES = new Set([
  'ready', 'approved', 'failed', 'needs_manual', 'already_available',
])


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

export default function TemplateWorkshop({ candidates, unsupportedCandidateIds, onApproved }) {
  const [enabled, setEnabled] = useState(false)
  const [builds, setBuilds] = useState([])
  // When the figures below were last true. `elapsed_seconds` is computed by the
  // server and only arrives on a POLL_MS poll, so the clock is drawn as
  // "server value + seconds since that poll" — otherwise it sits still for four
  // seconds and then jumps four, which reads as a hung build rather than a slow
  // one.
  const [polledAt, setPolledAt] = useState(null)
  const [drafts, setDrafts] = useState({})
  const [approved, setApproved] = useState({})   // candidate_id -> template name
  const [refreshFailed, setRefreshFailed] = useState({})  // candidate_id -> bool
  // Per-candidate in-flight state so starting a build for one problem does
  // not gate every other "Build one for this problem" button — a teacher
  // watching several unsupported problems must be able to kick each build
  // off independently.
  const [requestingIds, setRequestingIds] = useState(() => new Set())
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
      const response = await fetch('/meta/my/builds', { credentials: 'include' })
      const data = await responseJson(response)
      if (response.ok && Array.isArray(data)) {
        setBuilds(data)
        setPolledAt(Date.now())
      }
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

  // Seconds accrued since that poll, ticking once a second on its own.
  const sincePoll = useElapsedSeconds(polledAt, anyRunning)

  // Fetch each ready build's draft once. Keyed by draft id, so a refinement
  // arriving as a new revision is fetched again rather than showing the old one.
  useEffect(() => {
    const wanted = builds
      .filter((build) => build.draft_id && !drafts[build.draft_id])
      .map((build) => build.draft_id)
    if (wanted.length === 0) return
    let live = true
    Promise.all(wanted.map(async (draftId) => {
      const response = await fetch(`/meta/my/drafts/${draftId}`, { credentials: 'include' })
      const data = await responseJson(response)
      return response.ok && data ? [draftId, data] : null
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
    setRequestingIds((current) => {
      const next = new Set(current)
      next.add(candidateId)
      return next
    })
    try {
      const response = await fetch('/meta/my/builds', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ candidate_id: candidateId }),
      })
      const data = await responseJson(response)
      if (!response.ok) throw new Error(errorFrom(data, 'Could not start building a visual'))
      await loadBuilds()
    } catch (err) {
      setRequestError(err.message)
    } finally {
      setRequestingIds((current) => {
        if (!current.has(candidateId)) return current
        const next = new Set(current)
        next.delete(candidateId)
        return next
      })
    }
  }

  async function approveDraft(build, templateName) {
    setError(null)
    setBusy(true)
    try {
      const response = await fetch(`/meta/my/drafts/${build.draft_id}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          template_name: templateName,
          math_semantics_confirmed: true,
        }),
      })
      const data = await responseJson(response)
      if (!response.ok) throw new Error(errorFrom(data, 'Could not use this visual'))
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
      const response = await fetch(`/meta/my/builds/${build.candidate_id}`, {
        method: 'DELETE',
        credentials: 'include',
      })
      if (!response.ok) {
        const data = await responseJson(response)
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
      const response = await fetch(`/meta/my/drafts/${build.draft_id}/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ feedback }),
      })
      const data = await responseJson(response)
      if (!response.ok) throw new Error(errorFrom(data, 'Could not ask for another attempt'))
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
          <PendingWorkshopCard
            key={candidateId}
            candidate={candidate}
            requesting={requestingIds.has(candidateId)}
            onRequest={() => requestBuild(candidateId)}
          />
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
        const elapsed = build.elapsed_seconds + sincePoll
        const showElapsed = !TERMINAL_STAGES.has(build.stage)
        const candidate = candidates.find((entry) => entry.candidate_id === build.candidate_id)
        return (
          <WorkshopBuildCard
            key={build.candidate_id}
            build={build}
            candidate={candidate}
            draft={draft}
            approvedName={approvedName}
            refreshFailed={refreshFailed[build.candidate_id]}
            elapsed={elapsed}
            showElapsed={showElapsed}
            busy={busy}
            error={error}
            onApprove={(name) => approveDraft(build, name)}
            onReject={(feedback) => rejectDraft(build, feedback)}
            onClear={clearBuild}
          />
        )
      })}
    </>
  )
}
