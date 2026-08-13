import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { DemoContext } from '../pages/DemoShell'
import RenderDock from './RenderDock'

const STORYBOARD = [
  { scene_id: 's1', detected_summary: 'Perimeter of a rectangle', template: 'number_line' },
  { scene_id: 's2', detected_summary: 'Unit rate', template: 'bar_model' },
]

function mount(overrides = {}) {
  const value = {
    renderJob: null,
    pendingRenders: new Set(),
    storyboard: STORYBOARD,
    dismissRenderJob: vi.fn(),
    ...overrides,
  }
  return { value, ...render(<DemoContext.Provider value={value}><RenderDock /></DemoContext.Provider>) }
}

test('nothing is docked until a batch is dispatched', () => {
  mount()
  expect(screen.queryByRole('region', { name: /render progress/i })).not.toBeInTheDocument()
})

test('reports how many clips are rendering, and names each scene', () => {
  mount({
    renderJob: { ids: ['s1', 's2'], startedAt: Date.now(), results: {} },
    pendingRenders: new Set(['s1', 's2']),
  })
  expect(screen.getByRole('heading', { name: /Rendering 2 clips/i })).toBeInTheDocument()
  expect(screen.getByText(/number line · Perimeter of a rectangle/i)).toBeInTheDocument()
  expect(screen.getByText(/bar model · Unit rate/i)).toBeInTheDocument()
  // A running batch offers no Hide — the row set is the live account of it.
  expect(screen.queryByRole('button', { name: /hide/i })).not.toBeInTheDocument()
})

test('singular for a one-scene batch', () => {
  mount({
    renderJob: { ids: ['s1'], startedAt: Date.now(), results: {} },
    pendingRenders: new Set(['s1']),
  })
  expect(screen.getByRole('heading', { name: /Rendering 1 clip$/i })).toBeInTheDocument()
})

test('per-scene state is carried in words, not only in the mark', () => {
  mount({
    renderJob: { ids: ['s1', 's2'], startedAt: Date.now(), results: { s1: 'ok', s2: 'failed' } },
    pendingRenders: new Set(),
  })
  expect(screen.getByText(/— rendered/)).toBeInTheDocument()
  expect(screen.getByText(/— failed/)).toBeInTheDocument()
})

test('a finished batch says so, counts the failures, and can be hidden', async () => {
  const { value } = mount({
    renderJob: { ids: ['s1', 's2'], startedAt: Date.now(), results: { s1: 'ok', s2: 'failed' } },
    pendingRenders: new Set(),
  })
  expect(screen.getByRole('heading', { name: /Render finished — 1 failed/i })).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: /hide/i }))
  expect(value.dismissRenderJob).toHaveBeenCalled()
})

test('the clock is hidden from assistive tech, the heading is not', () => {
  mount({
    renderJob: { ids: ['s1'], startedAt: Date.now(), results: {} },
    pendingRenders: new Set(['s1']),
  })
  const heading = screen.getByRole('heading', { name: /Rendering/i })
  expect(heading).toHaveAttribute('aria-live', 'polite')
  expect(screen.getByText('0:00')).toHaveAttribute('aria-hidden', 'true')
})

test('a scene approved mid-flight gets a row, marked queued rather than rendering', () => {
  mount({
    // s1 was dispatched; s2 was approved while that POST was still out.
    renderJob: { ids: ['s1'], startedAt: Date.now(), results: {} },
    pendingRenders: new Set(['s1', 's2']),
  })
  expect(screen.getByRole('heading', { name: /Rendering 2 clips/i })).toBeInTheDocument()
  expect(screen.getByText(/— rendering/)).toBeInTheDocument()
  expect(screen.getByText(/— queued/)).toBeInTheDocument()
})

test('a scene missing from the storyboard still gets a row', () => {
  mount({
    renderJob: { ids: ['gone'], startedAt: Date.now(), results: {} },
    pendingRenders: new Set(['gone']),
    storyboard: STORYBOARD,
  })
  expect(screen.getByText('gone')).toBeInTheDocument()
})

test('a scene with no template is named by its summary alone', () => {
  mount({
    renderJob: { ids: ['s3'], startedAt: Date.now(), results: {} },
    pendingRenders: new Set(['s3']),
    storyboard: [{ scene_id: 's3', detected_summary: 'Text card only', template: null }],
  })
  expect(screen.getByText('Text card only')).toBeInTheDocument()
})
