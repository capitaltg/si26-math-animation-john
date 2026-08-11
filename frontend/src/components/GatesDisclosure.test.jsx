import { render, screen } from '@testing-library/react'
import { describe, test, expect } from 'vitest'
import GatesDisclosure from './GatesDisclosure'

describe('GatesDisclosure', () => {
  test('collapsed when all gates pass', () => {
    render(<GatesDisclosure gates={[{name:'Schema check', category:'Fixture', status:'passed'}]} />)
    expect(screen.getByRole('group')).not.toHaveAttribute('open')
    expect(screen.getByText(/all passed/i)).toBeInTheDocument()
  })

  test('open when a gate has failed', () => {
    render(<GatesDisclosure gates={[
      {name:'Semantic check', category:'Anchor alignment', status:'failed'},
      {name:'Schema check', category:'Fixture', status:'passed'},
    ]} />)
    expect(screen.getByRole('group')).toHaveAttribute('open')
    expect(screen.getByText(/1 failed/i)).toBeInTheDocument()
  })

  test('each gate row has a tooltip mapping', () => {
    render(<GatesDisclosure gates={[{name:'Schema check', category:'Fixture', status:'passed'}]} />)
    const trigger = screen.getByRole('button', { name: /what does schema check mean/i })
    expect(trigger).toHaveAttribute('title', expect.stringMatching(/expected type and range/i))
  })
})
