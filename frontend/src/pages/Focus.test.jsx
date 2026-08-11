import { vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { DemoContext } from './DemoShell'
import Focus from './Focus'

const baseScene = {
  scene_id: 'S1', template: 'array_grid', status: 'pending_review',
  params: { rows: 4, cols: 7 }, params_schema: {
    properties: {
      rows: { type: 'integer' },
      cols: { type: 'integer' },
    }
  },
  thumbnail_url: '/t.png', detected_summary: 'four by seven',
  computed_answer: { value: '= 28', expression: '4 × 7 = 28' },
  gates: [{ name: 'Schema check', category: 'Fixture', status: 'passed' }],
}

function renderFocus(overrides = {}) {
  const value = {
    storyboard: [baseScene],
    drafts: {},
    fieldErrors: {},
    pendingRenders: new Set(),
    loading: false,
    error: null,
    saveEdits: vi.fn(),
    setDrafts: vi.fn(),
    approveScene: vi.fn().mockResolvedValue(undefined),
    rejectScene: vi.fn(),
    retryScene: vi.fn(),
    setPendingRenders: vi.fn(),
    ...overrides,
  }
  return render(
    <MemoryRouter initialEntries={['/demo/problem/S1']}>
      <DemoContext.Provider value={value}>
        <Routes>
          <Route path="/demo/problem/:id" element={<Focus />} />
          <Route path="/demo" element={<div data-testid="queue">back</div>} />
        </Routes>
      </DemoContext.Provider>
    </MemoryRouter>
  )
}

test('renders template tabs with picked count 1', () => {
  renderFocus()
  expect(screen.getByRole('tab', { name: /picked/i })).toHaveTextContent('1')
})

test('renders numeric solution when computed_answer present', () => {
  renderFocus()
  expect(screen.getByText('= 28')).toBeInTheDocument()
})

test('renders param table with one row per scene param', () => {
  renderFocus()
  expect(screen.getByLabelText('rows')).toBeInTheDocument()
  expect(screen.getByLabelText('cols')).toBeInTheDocument()
})

test('renders gates disclosure collapsed by default', () => {
  renderFocus()
  expect(screen.getByRole('group')).not.toHaveAttribute('open')
})

test('Approve & render calls approveScene and navigates to /demo', async () => {
  const approveScene = vi.fn().mockResolvedValue(undefined)
  const setPendingRenders = vi.fn()
  renderFocus({ approveScene, setPendingRenders })
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: /approve.*render/i }))
  expect(approveScene).toHaveBeenCalledWith('S1')
  expect(screen.getByTestId('queue')).toBeInTheDocument()
})

test('unknown id redirects to /demo', () => {
  renderFocus({ storyboard: [] })
  expect(screen.getByTestId('queue')).toBeInTheDocument()
})

test('Approve & render does not navigate or enqueue rendering when approveScene rejects', async () => {
  const approveScene = vi.fn().mockRejectedValue(new Error('nope'))
  const setPendingRenders = vi.fn()
  renderFocus({ approveScene, setPendingRenders })
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: /approve.*render/i }))
  expect(approveScene).toHaveBeenCalledWith('S1')
  expect(setPendingRenders).not.toHaveBeenCalled()
  expect(screen.queryByTestId('queue')).not.toBeInTheDocument()
})

test('renders the rendered clip video when scene.clip_url is set', () => {
  renderFocus({ storyboard: [{ ...baseScene, clip_url: '/clips/s1.mp4' }] })
  const region = screen.getByRole('region', { name: /scene preview/i })
  expect(region.querySelector('video')).toBeInTheDocument()
})

// Regression coverage for the debounced-autosave stale-closure bug: saveEdits
// must receive the just-typed params directly, not whatever `drafts` looked
// like when the 250ms timer was scheduled.
const scalarScene = {
  scene_id: 'S1', template: 'array_grid', status: 'pending_review',
  params: { w: 4 }, params_schema: { properties: { w: { type: 'integer' } } },
  thumbnail_url: '/t.png', detected_summary: 'width four',
  computed_answer: { value: '= 4', expression: 'w = 4' },
  gates: [],
}

test('debounced autosave persists the latest typed value, not a stale draft', () => {
  vi.useFakeTimers()
  try {
    const saveEdits = vi.fn()
    renderFocus({ storyboard: [scalarScene], saveEdits })

    fireEvent.change(screen.getByLabelText('w'), { target: { value: '6' } })
    fireEvent.blur(screen.getByLabelText('w'))

    vi.advanceTimersByTime(300)

    expect(saveEdits).toHaveBeenCalledWith('S1', { w: 6 })
  } finally {
    vi.useRealTimers()
  }
})

test('revert saves the restored original value immediately', () => {
  const saveEdits = vi.fn()
  // drafts already holds an edited value (w: 6) that differs from the
  // scene's original params (w: 4), which is what enables the Revert button.
  renderFocus({ storyboard: [scalarScene], drafts: { S1: { w: 6 } }, saveEdits })

  fireEvent.click(screen.getByRole('button', { name: /revert/i }))

  expect(saveEdits).toHaveBeenCalledWith('S1', { w: 4 })
})

// PR-review fix (Finding 2, 2026-08-11): sceneAction now rethrows on
// failure, so revert/retry/reject must swallow rejections themselves or a
// 4xx/5xx surfaces as an unhandled promise rejection. These tests fail the
// whole run if an unhandled rejection is emitted (Vitest reports unhandled
// rejections as a top-level test failure), so simply completing without
// throwing — plus an explicit `await` to let the rejection's microtask
// settle before the test ends — is a real guarantee, not a weak one.
test('reject swallows a rejected rejectScene call (no unhandled rejection)', async () => {
  const rejectScene = vi.fn().mockRejectedValue(new Error('boom'))
  renderFocus({ rejectScene })
  const user = userEvent.setup()

  await user.click(screen.getByRole('button', { name: /reject/i }))
  await Promise.resolve() // flush the .catch(() => {}) microtask

  expect(rejectScene).toHaveBeenCalledWith('S1')
})

test('retry swallows a rejected retryScene call (no unhandled rejection)', async () => {
  const retryScene = vi.fn().mockRejectedValue(new Error('boom'))
  renderFocus({ retryScene })
  const user = userEvent.setup()

  await user.click(screen.getByRole('button', { name: /retry/i }))
  await Promise.resolve()

  expect(retryScene).toHaveBeenCalledWith('S1')
})

test('revert swallows a rejected saveEdits call (no unhandled rejection)', async () => {
  const saveEdits = vi.fn().mockRejectedValue(new Error('boom'))
  renderFocus({ storyboard: [scalarScene], drafts: { S1: { w: 6 } }, saveEdits })

  fireEvent.click(screen.getByRole('button', { name: /revert/i }))
  await Promise.resolve()

  expect(saveEdits).toHaveBeenCalledWith('S1', { w: 4 })
})
