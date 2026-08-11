import { vi } from 'vitest'
import { render, screen } from '@testing-library/react'
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
    results: null,
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
