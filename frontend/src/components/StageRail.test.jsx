import { render, screen } from '@testing-library/react'
import StageRail from './StageRail'

test('marks current stage active', () => {
  render(<StageRail current="storyboard" />)
  const current = screen.getByText(/check values/i).closest('li')
  expect(current).toHaveAttribute('aria-current', 'step')
  expect(current).toHaveAttribute('data-state', 'active')
})
test('marks earlier stages done', () => {
  render(<StageRail current="storyboard" />)
  expect(screen.getByText(/upload deck/i).closest('li')).toHaveAttribute('data-state', 'done')
})
