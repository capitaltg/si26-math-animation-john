import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import Landing from './Landing'

function mount() {
  return render(<MemoryRouter><Landing /></MemoryRouter>)
}

test('renders the six landing sections', () => {
  mount()
  ;[/Math Animation Generator/i, /The claim/i, /Sample/i, /How it works/i, /Honest limits/i, /Ready to try it/i].forEach(t =>
    expect(screen.getByText(t)).toBeInTheDocument()
  )
})

test('lists PPTX-only, K-8, no-OCR under honest limits', () => {
  mount()
  expect(screen.getByText(/pptx in/i)).toBeInTheDocument()
  expect(screen.getByText(/k.?8/i)).toBeInTheDocument()
  expect(screen.getByText(/no ocr/i)).toBeInTheDocument()
})

test('cta link points to /demo', () => {
  mount()
  expect(screen.getAllByRole('link', { name: /open demo/i })[0]).toHaveAttribute('href', '/demo')
})
