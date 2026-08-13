import { useEffect, useState } from 'react'

function secondsSince(startedAt) {
  return Math.max(0, Math.floor((Date.now() - startedAt) / 1000))
}

// A clock that ticks once a second on its own, anchored to a wall-clock start.
//
// Used anywhere the honest thing to show is "how long has this been going" and
// the only server-side number arrives on a slow poll: adding this to a polled
// figure keeps the seconds moving between polls instead of jumping by the whole
// poll interval, which reads as a frozen UI. It is deliberately not a progress
// figure — there is no progress stream behind either the render batch or the
// meta-template worker, so an elapsed count is all we can truthfully show.
//
// `running: false` freezes the clock at the elapsed value it had when it
// stopped, so a finished job keeps showing how long it took.
export default function useElapsedSeconds(startedAt, running = true) {
  const [seconds, setSeconds] = useState(() => (startedAt == null ? 0 : secondsSince(startedAt)))
  useEffect(() => {
    if (startedAt == null) {
      setSeconds(0)
      return undefined
    }
    setSeconds(secondsSince(startedAt))
    if (!running) return undefined
    const timer = setInterval(() => setSeconds(secondsSince(startedAt)), 1000)
    return () => clearInterval(timer)
  }, [startedAt, running])
  return seconds
}

// 0:07, 1:42 — tabular and stable in width past a minute.
export function formatClock(seconds) {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}
