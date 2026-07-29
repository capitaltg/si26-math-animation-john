import { describe, expect, it } from 'vitest'

import { developmentProxy } from '../vite.proxy'

describe('Vite development proxy', () => {
  it('forwards the meta-template review API to the backend', () => {
    expect(developmentProxy['/meta']).toBe('http://localhost:8000')
  })
})
