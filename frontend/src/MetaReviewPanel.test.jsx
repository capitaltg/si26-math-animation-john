import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import MetaReviewPanel from './MetaReviewPanel'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const draftSummary = {
  id: 'draft-1', fingerprint_key: 'k1', revision: 1,
  status: 'pending_review', created_at: '2026-07-28T00:00:00Z',
}

const draftDetail = {
  ...draftSummary,
  params_document: { params_version: 1, fields: [] },
  guard_document: { guard_version: 1, predicates: [] },
  answer_expression: { node: 'literal', value: 1 },
  animation_document: { animation_version: 1, root: { kind: 'label', text: 'x' } },
  classifier_bullet: 'use for fraction-of-whole bars',
  artifact_hash: 'sha256:abc',
  validation_report: { passed: true },
  preview_url: '/meta/preview/sha256:abc',
  fixtures: [
    {
      id: 'fx-1', kind: 'positive', expected_outcome: 'accept', generation_method: 'proposed',
      params: { n: 5 }, expected_result: null,
      structural_check_passed: true, structural_check_detail: 'ok', source_excerpt: '5 apples',
    },
  ],
  reviewer_feedback: null,
}

function installFetchMock() {
  const fetchMock = vi.fn(async (url, init = {}) => {
    if (url === '/meta/drafts?status=pending_review') {
      return { ok: true, json: async () => [draftSummary] }
    }
    if (url === '/meta/drafts/draft-1') {
      return { ok: true, json: async () => draftDetail }
    }
    if (url === '/meta/drafts/draft-1/reject' && init.method === 'POST') {
      return { ok: true, json: async () => ({ new_draft: null, needs_manual_authoring: false }) }
    }
    throw new Error(`Unexpected fetch: ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

it('lists pending drafts and opens one for review', async () => {
  installFetchMock()
  render(<MetaReviewPanel />)
  await waitFor(() => expect(screen.getByText(/k1/)).not.toBeNull())
  fireEvent.click(screen.getByText('Review'))
  await waitFor(() => expect(screen.getByText(/use for fraction-of-whole bars/)).not.toBeNull())
  expect(screen.getByText(/5 apples/)).not.toBeNull()
})

it('submits reject feedback and returns to the list', async () => {
  const fetchMock = installFetchMock()
  render(<MetaReviewPanel />)
  await waitFor(() => expect(screen.getByText(/k1/)).not.toBeNull())
  fireEvent.click(screen.getByText('Review'))
  await waitFor(() => expect(screen.getByText(/use for fraction-of-whole bars/)).not.toBeNull())

  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'tighten the guard' } })
  fireEvent.click(screen.getByText('Reject and request refinement'))

  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      '/meta/drafts/draft-1/reject',
      expect.objectContaining({ method: 'POST' }),
    ),
  )
  await waitFor(() => expect(screen.getByRole('heading', { name: 'Pending drafts' })).not.toBeNull())
})
