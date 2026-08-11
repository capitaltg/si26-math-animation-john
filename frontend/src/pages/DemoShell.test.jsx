import { render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
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
