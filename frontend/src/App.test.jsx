import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import App from './App'

describe('App routes', () => {
  it('renders SiteHeader wordmark on every route', () => {
    render(<MemoryRouter initialEntries={['/']}><App /></MemoryRouter>)
    expect(screen.getByRole('banner')).toBeInTheDocument()
    expect(screen.getByLabelText(/doodlesum home/i)).toBeInTheDocument()
  })

  it('renders Landing at /', () => {
    render(<MemoryRouter initialEntries={['/']}><App /></MemoryRouter>)
    expect(
      screen.getByRole('heading', { name: /verified animation for every math slide/i })
    ).toBeInTheDocument()
  })

  it('renders demo shell at /demo', () => {
    render(<MemoryRouter initialEntries={['/demo']}><App /></MemoryRouter>)
    expect(screen.getByTestId('demo-shell')).toBeInTheDocument()
  })
})
