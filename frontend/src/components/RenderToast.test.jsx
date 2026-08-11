import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi, test, expect } from 'vitest'
import { DemoContext } from '../pages/DemoShell'
import RenderToast from './RenderToast'

function mount(overrides = {}) {
  const value = {
    toasts: [], dismissToast: vi.fn(), pendingRenders: new Set(),
    ...overrides,
  }
  return { value, ...render(<DemoContext.Provider value={value}><RenderToast /></DemoContext.Provider>) }
}

test('renders one toast per entry', () => {
  mount({ toasts: [
    { id: 'a', title: 'first', clipUrl: '/a.mp4', kind: 'ok' },
    { id: 'b', title: 'second', clipUrl: '/b.mp4', kind: 'ok' },
  ]})
  expect(screen.getAllByText(/watch/i)).toHaveLength(2)
})

test('dismiss button removes only the addressed toast', async () => {
  const { value } = mount({ toasts: [
    { id: 'a', title: 'first', clipUrl: '/a.mp4', kind: 'ok' },
  ]})
  await userEvent.click(screen.getByRole('button', { name: /dismiss first/i }))
  expect(value.dismissToast).toHaveBeenCalledWith('a')
})

test('Watch button opens the clip in a modal', async () => {
  mount({ toasts: [{ id: 'a', title: 'first', clipUrl: '/a.mp4', kind: 'ok' }] })
  await userEvent.click(screen.getByRole('button', { name: /watch.*download/i }))
  expect(screen.getByRole('dialog', { name: /watch first/i })).toBeInTheDocument()
})
