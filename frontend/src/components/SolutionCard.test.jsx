import { render, screen } from '@testing-library/react'
import { describe, test, expect } from 'vitest'
import SolutionCard from './SolutionCard'

describe('SolutionCard', () => {
  test('renders nothing when null', () => {
    const { container } = render(<SolutionCard answer={null} />)
    expect(container).toBeEmptyDOMElement()
  })

  test('renders value and expression when present', () => {
    render(<SolutionCard answer={{ value: '= 28', expression: '4 × 7 = 28' }} />)
    expect(screen.getByText('= 28')).toBeInTheDocument()
    expect(screen.getByText('4 × 7 = 28')).toBeInTheDocument()
  })
})
