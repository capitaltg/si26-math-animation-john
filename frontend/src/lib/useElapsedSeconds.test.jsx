import { render, screen, act } from '@testing-library/react'
import { useLayoutEffect } from 'react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import useElapsedSeconds, { formatClock } from './useElapsedSeconds'

function Clock({ startedAt, running }) {
  return <span data-testid="clock">{formatClock(useElapsedSeconds(startedAt, running))}</span>
}

beforeEach(() => { vi.useFakeTimers() })
afterEach(() => { vi.useRealTimers() })

test('counts up once a second without any other input', () => {
  render(<Clock startedAt={Date.now()} running />)
  expect(screen.getByTestId('clock')).toHaveTextContent('0:00')
  act(() => { vi.advanceTimersByTime(3000) })
  expect(screen.getByTestId('clock')).toHaveTextContent('0:03')
  act(() => { vi.advanceTimersByTime(59000) })
  expect(screen.getByTestId('clock')).toHaveTextContent('1:02')
})

test('freezes at the elapsed time it reached once it stops running', () => {
  const startedAt = Date.now()
  const { rerender } = render(<Clock startedAt={startedAt} running />)
  act(() => { vi.advanceTimersByTime(5000) })
  rerender(<Clock startedAt={startedAt} running={false} />)
  expect(screen.getByTestId('clock')).toHaveTextContent('0:05')
  act(() => { vi.advanceTimersByTime(10000) })
  expect(screen.getByTestId('clock')).toHaveTextContent('0:05')
})

test('a new anchor never paints the old offset on top of it', () => {
  // Stands in for the caller's real shape: a polled server figure plus this
  // hook's local drift. Every committed frame is recorded, so a one-frame
  // flash of 48 between 20 and 44 is caught rather than being invisible to an
  // end-state assertion.
  const painted = []
  function Polled({ serverSeconds, polledAt }) {
    const drift = useElapsedSeconds(polledAt, true)
    const value = serverSeconds + drift
    // Recorded in a layout effect, so only *committed* renders count: a render
    // pass React discards never reaches the screen, and counting it would fail
    // the fixed code as loudly as the broken code.
    useLayoutEffect(() => { painted.push(value) })
    return <span data-testid="clock">{formatClock(value)}</span>
  }

  const first = Date.now()
  const { rerender } = render(<Polled serverSeconds={20} polledAt={first} />)
  act(() => { vi.advanceTimersByTime(4000) })
  expect(screen.getByTestId('clock')).toHaveTextContent('0:24')

  // The poll lands: the server figure and the anchor change together.
  painted.length = 0
  rerender(<Polled serverSeconds={44} polledAt={Date.now()} />)
  expect(screen.getByTestId('clock')).toHaveTextContent('0:44')
  // 48 would be the new figure carrying the previous anchor's four seconds.
  expect(painted).not.toContain(48)
  // And it keeps counting from the new anchor, not from zero.
  act(() => { vi.advanceTimersByTime(1000) })
  expect(screen.getByTestId('clock')).toHaveTextContent('0:45')
})

test('reads zero with no anchor', () => {
  render(<Clock startedAt={null} running />)
  expect(screen.getByTestId('clock')).toHaveTextContent('0:00')
})

test('formatClock pads seconds and rolls into minutes', () => {
  expect(formatClock(0)).toBe('0:00')
  expect(formatClock(9)).toBe('0:09')
  expect(formatClock(75)).toBe('1:15')
  expect(formatClock(600)).toBe('10:00')
})
