import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { beforeEach, expect, test } from 'vitest'
import DemoShell from './DemoShell'

test('renders stage rail and upload input on entry', () => {
  render(
    <MemoryRouter initialEntries={['/demo']}>
      <Routes><Route path="/demo/*" element={<DemoShell />} /></Routes>
    </MemoryRouter>
  )
  expect(screen.getByRole('list', { name: /pipeline stages/i })).toBeInTheDocument()
  expect(screen.getByLabelText(/upload a pptx/i)).toBeInTheDocument()
})

// The integration tests below were blocked for three rounds of review by one
// jsdom gap: jsdom does not implement HTMLFormElement's "supported property
// names", so `event.target.file` in `handleUpload` — which works in every real
// browser — resolves to `undefined`, and upload is the only route to a non-empty
// `pendingRenders`. The seam is to define that one named property on the form in
// the test (`reachStoryboard` below); everything downstream then exercises the
// real components. This is what lets the /render effect, the render dock and the
// toast stack be tested end to end at last.

function mkScene(sceneId, summary) {
  return {
    scene_id: sceneId,
    detected_summary: summary,
    template: 'number_line',
    slide_index: 1,
    status: 'pending_review',
    params: { a: 1 },
    params_schema: { properties: { a: { type: 'integer' } } },
    gates: [],
  }
}

const SCENES = [mkScene('s1', 'Scene one'), mkScene('s2', 'Scene two')]

function json(body, status = 200) {
  return Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(body) })
}

function deferred() {
  let resolve
  const promise = new Promise((r) => { resolve = r })
  return { promise, resolve }
}

let approvedOnServer
let renderCalls

// Stands in for the backend's /render: answers for every approved scene in the
// session (not just the ones the caller queued) and serves an unchanged scene
// from cache, which is what makes duplicate announcements possible.
let nextRender

beforeEach(() => {
  approvedOnServer = new Set()
  renderCalls = []
  nextRender = () => json({
    clips: [...approvedOnServer].map((id) => ({ scene_id: id, status: 'approved', clip_url: `/clips/${id}` })),
  })
  globalThis.fetch = (url, opts = {}) => {
    const method = opts.method ?? 'GET'
    if (url === '/meta/my/capabilities') return json({ enabled: false })
    if (url === '/upload') {
      return json({
        candidates: SCENES.map((scene, i) => ({
          candidate_id: `c${i}`, one_line_summary: `Cand ${i}`, slide_index: 1, source_excerpt: 'x',
        })),
      })
    }
    if (url === '/options') {
      return json({ options: SCENES.map((_, i) => ({ candidate_id: `c${i}`, templates: [{ template: 'number_line' }] })) })
    }
    if (url === '/storyboard' && method === 'POST') return json({ scenes: SCENES })
    const approve = /^\/storyboard\/(s\d)\/approve$/.exec(url)
    if (approve) {
      approvedOnServer.add(approve[1])
      return json({ ...SCENES.find((s) => s.scene_id === approve[1]), status: 'approved' })
    }
    if (url === '/render') {
      renderCalls.push([...approvedOnServer])
      return nextRender()
    }
    throw new Error(`unmocked ${method} ${url}`)
  }
})

async function reachStoryboard(user) {
  const input = screen.getByLabelText(/upload a pptx/i)
  await user.upload(input, new File(['x'], 'deck.pptx'))
  const form = input.closest('form')
  // The jsdom seam described above.
  Object.defineProperty(form, 'file', { value: input, configurable: true })
  fireEvent.submit(form)
  await screen.findByText(/Cand 0/i)
  for (const box of screen.getAllByRole('checkbox')) await user.click(box)
  await user.click(screen.getByRole('button', { name: /pick visualizations/i }))
  await screen.findByRole('button', { name: /build storyboard/i })
  await user.click(screen.getByRole('button', { name: /build storyboard/i }))
  return screen.findByRole('button', { name: /approve all/i })
}

function mount() {
  return render(
    <MemoryRouter initialEntries={['/demo']}>
      <Routes><Route path="/demo/*" element={<DemoShell />} /></Routes>
    </MemoryRouter>
  )
}

test('the dock reports the batch while it runs, then that it finished', async () => {
  const user = userEvent.setup()
  const gate = deferred()
  nextRender = () => gate.promise.then(() => json({
    clips: [...approvedOnServer].map((id) => ({ scene_id: id, status: 'approved', clip_url: `/clips/${id}` })),
  }))
  mount()
  const approveAll = await reachStoryboard(user)
  await user.click(approveAll)

  // While the blocking POST is in flight the wait is reported in place, not
  // left to a toast that only arrives at the very end.
  const dock = await screen.findByRole('region', { name: /render progress/i })
  expect(dock).toHaveTextContent(/Rendering 2 clips/i)
  await waitFor(() => expect(screen.getAllByText(/rendering…/i)).toHaveLength(2))

  gate.resolve()
  await waitFor(() => expect(dock).toHaveTextContent(/Render finished/i))
  expect(screen.getAllByRole('button', { name: /watch & download/i })).toHaveLength(2)
  expect(screen.getAllByText('rendered')).toHaveLength(2)

  await user.click(screen.getByRole('button', { name: /^hide$/i }))
  expect(screen.queryByRole('region', { name: /render progress/i })).not.toBeInTheDocument()
})

test('a clip re-returned by a follow-up batch is not announced twice', async () => {
  const user = userEvent.setup()
  const gate = deferred()
  // First call: slow, and covers only the scene approved at dispatch time.
  nextRender = () => gate.promise.then(() => json({
    clips: [{ scene_id: 's1', status: 'approved', clip_url: '/clips/s1' }],
  }))
  mount()
  await reachStoryboard(user)

  // Approve scene one from its own page: this starts an in-flight /render.
  await user.click(screen.getByText('Scene one'))
  await user.click(await screen.findByRole('button', { name: /approve & render/i }))
  await screen.findByRole('region', { name: /render progress/i })

  // Then approve the rest from the queue while that render is still running.
  await user.click(await screen.findByRole('button', { name: /approve all/i }))
  // The follow-up call answers for both scenes, s1 straight from cache.
  nextRender = () => json({
    clips: [
      { scene_id: 's1', status: 'approved', clip_url: '/clips/s1' },
      { scene_id: 's2', status: 'approved', clip_url: '/clips/s2' },
    ],
  })
  gate.resolve()

  await waitFor(() => expect(renderCalls).toHaveLength(2))
  await waitFor(() => {
    expect(screen.getByRole('region', { name: /render progress/i })).toHaveTextContent(/Render finished/i)
  })
  // Two scenes, two clips, two notifications — s1 is not announced again just
  // because the second batch's response mentioned it.
  expect(screen.getAllByRole('button', { name: /watch & download/i })).toHaveLength(2)
})

test('a failed batch is reported on the dock, not left reading as finished', async () => {
  const user = userEvent.setup()
  nextRender = () => json({ detail: 'boom' }, 500)
  mount()
  const approveAll = await reachStoryboard(user)
  await user.click(approveAll)

  const dock = await screen.findByRole('region', { name: /render progress/i })
  await waitFor(() => expect(dock).toHaveTextContent(/Render finished — 2 failed/i))
  expect(await screen.findByText(/Render error/i)).toBeInTheDocument()
})
