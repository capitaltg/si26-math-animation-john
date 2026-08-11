import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import App from './App'

describe('App routes', () => {
  it('renders Landing at /', () => {
    render(<MemoryRouter initialEntries={['/']}><App /></MemoryRouter>)
    expect(screen.getByRole('link', { name: /open demo/i })).toBeInTheDocument()
  })

  it('renders demo shell at /demo', () => {
    render(<MemoryRouter initialEntries={['/demo']}><App /></MemoryRouter>)
    expect(screen.getByTestId('demo-shell')).toBeInTheDocument()
  })
})
