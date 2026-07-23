import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import SchemaForm from './SchemaForm'

afterEach(cleanup)

describe('SchemaForm primitive arrays', () => {
  it('renders and edits integer array items', () => {
    const onChange = vi.fn()
    const schema = {
      type: 'object',
      properties: {
        left_terms: {
          title: 'Left Terms',
          type: 'array',
          minItems: 2,
          maxItems: 2,
          items: { type: 'integer' },
        },
      },
    }

    render(<SchemaForm schema={schema} value={{ left_terms: [4, 3] }} onChange={onChange} />)

    const inputs = screen.getAllByRole('spinbutton')
    expect(inputs.map((input) => input.value)).toEqual(['4', '3'])
    fireEvent.change(inputs[1], { target: { value: '5' } })
    expect(onChange).toHaveBeenLastCalledWith({ left_terms: [4, 5] })
  })

  it('renders and edits string array items', () => {
    const onChange = vi.fn()
    const schema = {
      type: 'object',
      properties: {
        lines: {
          title: 'Lines',
          type: 'array',
          minItems: 1,
          items: { type: 'string' },
        },
      },
    }

    render(<SchemaForm schema={schema} value={{ lines: ['Original line'] }} onChange={onChange} />)

    const input = screen.getByDisplayValue('Original line')
    fireEvent.change(input, { target: { value: 'Updated line' } })
    expect(onChange).toHaveBeenLastCalledWith({ lines: ['Updated line'] })
  })

  it('adds a type-appropriate primitive value', () => {
    const onChange = vi.fn()
    const schema = {
      type: 'object',
      properties: {
        values: {
          title: 'Values',
          type: 'array',
          items: { type: 'integer' },
        },
      },
    }

    render(<SchemaForm schema={schema} value={{ values: [4] }} onChange={onChange} />)

    fireEvent.click(screen.getByRole('button', { name: /add/i }))
    expect(onChange).toHaveBeenLastCalledWith({ values: [4, 0] })
  })
})
