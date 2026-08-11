import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import Landing from './Landing'

function mount() {
  return render(<MemoryRouter><Landing /></MemoryRouter>)
}

test('renders the primary landing sections', () => {
  mount()
  ;[
    { level: 1, name: /Turn a math slide into a verified animation/i },
    { level: 2, name: /Why DoodleSum/i },
    { level: 2, name: /See a clip/i },
    { level: 2, name: /How it works/i },
    { level: 3, name: /Who it's for/i },
    { level: 3, name: /Honest limits/i },
    { level: 2, name: /Ready to try it/i },
  ].forEach(({ level, name }) =>
    expect(screen.getByRole('heading', { level, name })).toBeInTheDocument()
  )
})

test('lists PPTX-only, no-OCR, and no-account under honest limits', () => {
  mount()
  expect(screen.getByText(/pptx in/i)).toBeInTheDocument()
  expect(screen.getByText(/no ocr/i)).toBeInTheDocument()
  expect(screen.getByText(/no accounts/i)).toBeInTheDocument()
})

test('primary CTAs link to /demo', () => {
  mount()
  const demoLinks = screen.getAllByRole('link', { name: /demo/i })
    .filter((el) => el.getAttribute('href') === '/demo')
  expect(demoLinks.length).toBeGreaterThanOrEqual(2)
})
