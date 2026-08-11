import { vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { DemoContext } from './DemoShell'
import Queue from './Queue'

function renderWithContext(overrides) {
  const value = {
    candidates: null, selected: {}, options: null, picks: {}, results: null,
    storyboard: null, drafts: {}, fieldErrors: {}, fileName: null, loading: false,
    error: null, pendingRenders: new Set(), toasts: [],
    handleUpload: vi.fn(), toggle: vi.fn(), handleGetOptions: vi.fn(),
    handleBuildStoryboard: vi.fn(), approveScene: vi.fn(),
    setPicks: vi.fn(), setPendingRenders: vi.fn(),
    ...overrides,
  }
  return render(
    <MemoryRouter>
      <DemoContext.Provider value={value}><Queue /></DemoContext.Provider>
    </MemoryRouter>
  )
}

test('renders upload input when no candidates yet', () => {
  renderWithContext({})
  expect(screen.getByLabelText(/upload a pptx/i)).toBeInTheDocument()
})

test('renders candidate checkboxes and Pick visualizations button after upload', () => {
  renderWithContext({
    candidates: [
      { candidate_id: 'c1', one_line_summary: 'Add fractions', slide_index: 1, source_excerpt: '1/2 + 1/3' },
      { candidate_id: 'c2', one_line_summary: 'Solve for x', slide_index: 2, source_excerpt: '2x + 3 = 7' },
    ],
  })
  expect(screen.getAllByRole('checkbox')).toHaveLength(2)
  expect(screen.getByRole('button', { name: /pick visualizations/i })).toBeInTheDocument()
})

test('renders one row per storyboard scene, linking to focus view', () => {
  renderWithContext({
    candidates: [],
    options: [],
    storyboard: [
      { scene_id: 's1', detected_summary: 'Add fractions', template: 'number_line', slide_index: 1, status: 'pending_review' },
      { scene_id: 's2', detected_summary: 'Solve for x', template: 'balance_scale', slide_index: 2, status: 'rendered' },
      { scene_id: 's3', detected_summary: 'Area of circle', template: 'shape_fill', slide_index: 3, status: 'rejected' },
    ],
  })
  const links = screen.getAllByRole('link')
  expect(links).toHaveLength(3)
  expect(links.map((l) => l.getAttribute('href')).sort()).toEqual([
    '/demo/problem/s1', '/demo/problem/s2', '/demo/problem/s3',
  ])
})

test('shows status pill per row', () => {
  renderWithContext({
    candidates: [],
    options: [],
    storyboard: [
      { scene_id: 's1', detected_summary: 'Add fractions', template: 'number_line', slide_index: 1, status: 'pending_review' },
      { scene_id: 's2', detected_summary: 'Solve for x', template: 'balance_scale', slide_index: 2, status: 'rendered' },
      { scene_id: 's3', detected_summary: 'Area of circle', template: 'shape_fill', slide_index: 3, status: 'rejected' },
    ],
  })
  expect(screen.getByText(/needs review/i)).toBeInTheDocument()
  expect(screen.getByText(/^rendered$/i)).toBeInTheDocument()
  expect(screen.getByText(/^rejected$/i)).toBeInTheDocument()
})

test('renders "Approve all & render remaining" button when ready scenes exist', () => {
  const { rerender } = renderWithContext({
    candidates: [],
    options: [],
    storyboard: [
      { scene_id: 's1', detected_summary: 'Add fractions', template: 'number_line', slide_index: 1, status: 'pending_review' },
    ],
  })
  expect(screen.getByRole('button', { name: /approve all.*render remaining/i })).toBeInTheDocument()

  rerender(
    <MemoryRouter>
      <DemoContext.Provider value={{
        candidates: [], selected: {}, options: [], picks: {}, results: null,
        storyboard: [
          { scene_id: 's1', detected_summary: 'Add fractions', template: 'number_line', slide_index: 1, status: 'rendered' },
        ],
        drafts: {}, fieldErrors: {}, fileName: null, loading: false,
        error: null, pendingRenders: new Set(), toasts: [],
        handleUpload: vi.fn(), toggle: vi.fn(), handleGetOptions: vi.fn(),
        handleBuildStoryboard: vi.fn(), approveScene: vi.fn(),
        setPicks: vi.fn(), setPendingRenders: vi.fn(),
      }}>
        <Queue />
      </DemoContext.Provider>
    </MemoryRouter>
  )
  expect(screen.queryByRole('button', { name: /approve all.*render remaining/i })).not.toBeInTheDocument()
})
