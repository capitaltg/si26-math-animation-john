import { render, screen, act } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import TemplateWorkshop from './TemplateWorkshop'

const CANDIDATES = [{ candidate_id: 'c1', one_line_summary: 'A perimeter problem' }]

function json(body) {
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) })
}

let build

beforeEach(() => {
  // Installed before mount so every clock in the component is under our control;
  // testing-library's own waitFor does not drive vitest's fake timers, so the
  // tests below advance time explicitly instead of polling for a change.
  vi.useFakeTimers()
  build = { candidate_id: 'c1', stage: 'building', elapsed_seconds: 20, draft_id: null, error: null }
  globalThis.fetch = (url) => {
    if (url === '/meta/my/capabilities') return json({ enabled: true })
    if (url === '/meta/my/builds') return json([build])
    throw new Error(`unmocked ${url}`)
  }
})

afterEach(() => { vi.useRealTimers() })

// Lets the capabilities check, the first build load, and any timers due at `ms`
// settle inside one act() so assertions see a committed DOM.
async function tick(ms = 0) {
  await act(async () => { await vi.advanceTimersByTimeAsync(ms) })
  await act(async () => { await vi.advanceTimersByTimeAsync(0) })
}

async function mount() {
  const utils = render(
    <TemplateWorkshop candidates={CANDIDATES} unsupportedCandidateIds={['c1']} onApproved={() => {}} />
  )
  await tick()
  return utils
}

test('the elapsed clock advances every second between polls', async () => {
  await mount()
  // Seeded from the server's own figure on the first load.
  expect(screen.getByText('0:20')).toBeInTheDocument()

  // One second of wall clock, no new poll: the clock must still move. Before
  // this it only changed when a POLL_MS (4s) response landed, so it sat still
  // and then jumped four seconds — a slow build looked like a hung one.
  await tick(1000)
  expect(screen.getByText('0:21')).toBeInTheDocument()
  await tick(2000)
  expect(screen.getByText('0:23')).toBeInTheDocument()
})

test('a poll re-anchors the clock to the server figure', async () => {
  await mount()
  expect(screen.getByText('0:20')).toBeInTheDocument()
  build = { ...build, elapsed_seconds: 44 }
  // Cross the 4s poll interval: the interpolated drift resets and the server's
  // number takes over, so the two never double-count.
  await tick(4000)
  expect(screen.getByText('0:44')).toBeInTheDocument()
})

test('a terminal build stops the clock entirely', async () => {
  build = { ...build, stage: 'needs_manual', error: 'Generation gave up.' }
  await mount()
  await tick(3000)
  // No elapsed clock on a finished build, and nothing left ticking for it.
  expect(screen.queryByText(/^\d+:\d\d$/)).not.toBeInTheDocument()
  expect(vi.getTimerCount()).toBe(0)
})

test('the in-progress stage mark is the one that spins', async () => {
  const { container } = await mount()
  expect(screen.getByText(/Writing the template/i)).toBeInTheDocument()
  // `.spin` is what the stylesheet animates; the active stamp must carry it.
  expect(container.querySelector('.stamp[data-state="active"] .spin')).not.toBeNull()
  expect(container.querySelector('.stamp[data-state="todo"] .spin')).toBeNull()
})

test('the stall note appears once a queued build passes the threshold', async () => {
  build = { ...build, stage: 'queued', elapsed_seconds: 58 }
  await mount()
  expect(screen.queryByText(/has not started on this yet/i)).not.toBeInTheDocument()
  // Reached by the local clock, without waiting for a poll to say so.
  await tick(2000)
  expect(screen.getByText(/has not started on this yet/i)).toBeInTheDocument()
})
