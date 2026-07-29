import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import MetaReviewPanel from './MetaReviewPanel'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

beforeEach(() => {
  sessionStorage.setItem('metaReviewerToken', 'test-token')
  URL.createObjectURL = vi.fn((blob) => `blob:${blob.__sourceUrl}`)
  URL.revokeObjectURL = vi.fn()
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

function installFetchMock({ fixtureResponse } = {}) {
  const fetchMock = vi.fn(async (url, init = {}) => {
    if (url === '/meta/drafts?status=pending_review') {
      return { ok: true, json: async () => [draftSummary] }
    }
    if (url === '/meta/drafts?status=failed_validation') {
      return { ok: true, json: async () => [] }
    }
    if (url === '/meta/drafts/draft-1') {
      return { ok: true, json: async () => draftDetail }
    }
    if (url === '/meta/drafts/draft-1/reject' && init.method === 'POST') {
      return { ok: true, json: async () => ({ new_draft: null, needs_manual_authoring: false }) }
    }
    if (url === '/meta/drafts/draft-1/fixtures/fx-1' && init.method === 'POST') {
      return fixtureResponse || {
        ok: true,
        json: async () => ({
          ...draftDetail.fixtures[0], params: { n: 6 }, expected_result: { answer: '6' },
        }),
      }
    }
    if (url === draftDetail.preview_url) {
      return { ok: true, blob: async () => ({ __sourceUrl: url }) }
    }
    throw new Error(`Unexpected fetch: ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function _qualifyingFixture(id) {
  return {
    id, kind: 'positive', expected_outcome: 'accept', generation_method: 'proposed',
    params: { n: 5 }, expected_result: { answer: '5' },
    structural_check_passed: true, structural_check_detail: 'ok', source_excerpt: '5 apples',
  }
}

// A draft with enough qualifying fixtures and full predicate coverage to
// satisfy every client-side Approve gate.
const approvableDraftDetail = {
  ...draftDetail,
  guard_document: { guard_version: 1, predicates: [{ predicate: 'positive', value: { node: 'field_ref', field: 'n' } }] },
  validation_report: { passed: true, negative_predicate_coverage: [0] },
  fixtures: [
    _qualifyingFixture('fx-1'),
    _qualifyingFixture('fx-2'),
    _qualifyingFixture('fx-3'),
    _qualifyingFixture('fx-4'),
    _qualifyingFixture('fx-5'),
  ],
}

function installApprovableFetchMock({ approveResponse } = {}) {
  const fetchMock = vi.fn(async (url, init = {}) => {
    if (url === '/meta/drafts?status=pending_review') {
      return { ok: true, json: async () => [draftSummary] }
    }
    if (url === '/meta/drafts?status=failed_validation') {
      return { ok: true, json: async () => [] }
    }
    if (url === '/meta/drafts/draft-1') {
      return { ok: true, json: async () => approvableDraftDetail }
    }
    if (url === '/meta/drafts/draft-1/approve' && init.method === 'POST') {
      return approveResponse || {
        ok: true,
        json: async () => ({ template_version_id: 'ver-1', template_name: 'apples_count', status: 'enabled' }),
      }
    }
    if (url === approvableDraftDetail.preview_url) {
      return { ok: true, blob: async () => ({ __sourceUrl: url }) }
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

it('lists failed-validation drafts for repair', async () => {
  const failedValidationDraft = {
    ...draftSummary,
    id: 'draft-2',
    fingerprint_key: 'needs-repair',
    status: 'failed_validation',
  }
  vi.stubGlobal('fetch', vi.fn(async (url) => {
    if (url === '/meta/drafts?status=pending_review') {
      return { ok: true, json: async () => [draftSummary] }
    }
    if (url === '/meta/drafts?status=failed_validation') {
      return { ok: true, json: async () => [failedValidationDraft] }
    }
    throw new Error(`Unexpected fetch: ${url}`)
  }))

  render(<MetaReviewPanel />)

  await waitFor(() => expect(screen.getByText('needs-repair')).not.toBeNull())
})

it('submits reject feedback and returns to the list', async () => {
  const fetchMock = installFetchMock()
  render(<MetaReviewPanel />)
  await waitFor(() => expect(screen.getByText(/k1/)).not.toBeNull())
  fireEvent.click(screen.getByText('Review'))
  await waitFor(() => expect(screen.getByText(/use for fraction-of-whole bars/)).not.toBeNull())

  fireEvent.change(screen.getByRole('textbox', { name: 'Feedback' }), { target: { value: 'tighten the guard' } })
  fireEvent.click(screen.getByText('Reject and request refinement'))

  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      '/meta/drafts/draft-1/reject',
      expect.objectContaining({ method: 'POST' }),
    ),
  )
  await waitFor(() => expect(screen.getByRole('heading', { name: 'Pending drafts' })).not.toBeNull())
})

it('sends the stored reviewer token as a bearer header on every call', async () => {
  const fetchMock = installFetchMock()
  render(<MetaReviewPanel />)
  await waitFor(() => expect(screen.getByText(/k1/)).not.toBeNull())

  expect(fetchMock).toHaveBeenCalledWith(
    '/meta/drafts?status=pending_review',
    expect.objectContaining({ headers: expect.objectContaining({ Authorization: 'Bearer test-token' }) }),
  )

  fireEvent.click(screen.getByText('Review'))
  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      '/meta/drafts/draft-1',
      expect.objectContaining({ headers: expect.objectContaining({ Authorization: 'Bearer test-token' }) }),
    ),
  )
})

it('retries loading drafts once a valid token is entered after an unauthenticated load', async () => {
  sessionStorage.removeItem('metaReviewerToken')
  const fetchMock = vi.fn(async (url, init = {}) => {
    if (url.startsWith('/meta/drafts')) {
      if (init.headers?.Authorization !== 'Bearer good-token') {
        return { ok: false, status: 401, json: async () => ({ detail: 'Invalid or missing reviewer token' }) }
      }
      if (url === '/meta/drafts?status=pending_review') return { ok: true, json: async () => [draftSummary] }
      if (url === '/meta/drafts?status=failed_validation') return { ok: true, json: async () => [] }
    }
    throw new Error(`Unexpected fetch: ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)

  render(<MetaReviewPanel />)
  await waitFor(() => expect(screen.getByText('Invalid or missing reviewer token')).not.toBeNull())

  fireEvent.change(screen.getByLabelText('Reviewer token'), { target: { value: 'good-token' } })
  fireEvent.click(screen.getByText('Load drafts'))

  await waitFor(() => expect(screen.getByText(/k1/)).not.toBeNull())
})

it('edits and saves a fixture', async () => {
  const fetchMock = installFetchMock()
  render(<MetaReviewPanel />)
  await waitFor(() => expect(screen.getByText(/k1/)).not.toBeNull())
  fireEvent.click(screen.getByText('Review'))
  await waitFor(() => expect(screen.getByLabelText('Fixture fx-1 params')).not.toBeNull())

  fireEvent.change(screen.getByLabelText('Fixture fx-1 params'), { target: { value: '{"n":6}' } })
  fireEvent.change(screen.getByLabelText('Fixture fx-1 expected result'), { target: { value: '{"answer":"6"}' } })
  fireEvent.click(screen.getByText('Save fixture'))

  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      '/meta/drafts/draft-1/fixtures/fx-1',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ params: { n: 6 }, expected_result: { answer: '6' } }),
      }),
    ),
  )
})

it('shows fixture save errors', async () => {
  installFetchMock({
    fixtureResponse: {
      ok: false,
      json: async () => ({ detail: 'Expected result does not match answer expression' }),
    },
  })
  render(<MetaReviewPanel />)
  await waitFor(() => expect(screen.getByText(/k1/)).not.toBeNull())
  fireEvent.click(screen.getByText('Review'))
  await waitFor(() => expect(screen.getByLabelText('Fixture fx-1 params')).not.toBeNull())

  fireEvent.click(screen.getByText('Save fixture'))

  await waitFor(() =>
    expect(screen.getByText('Expected result does not match answer expression')).not.toBeNull(),
  )
})

it('reloads fresh draft detail after saving a fixture instead of patching locally', async () => {
  const reloadedDetail = {
    ...draftDetail,
    preview_url: '/meta/preview/sha256:after-edit',
    fixtures: [
      { ...draftDetail.fixtures[0], params: { n: 6 }, expected_result: { answer: '6' } },
    ],
  }
  let draftDetailCalls = 0
  const fetchMock = vi.fn(async (url, init = {}) => {
    if (url === '/meta/drafts?status=pending_review') {
      return { ok: true, json: async () => [draftSummary] }
    }
    if (url === '/meta/drafts?status=failed_validation') {
      return { ok: true, json: async () => [] }
    }
    if (url === '/meta/drafts/draft-1') {
      draftDetailCalls += 1
      return { ok: true, json: async () => (draftDetailCalls === 1 ? draftDetail : reloadedDetail) }
    }
    if (url === '/meta/drafts/draft-1/fixtures/fx-1' && init.method === 'POST') {
      return {
        ok: true,
        json: async () => ({ ...draftDetail.fixtures[0], params: { n: 6 }, expected_result: { answer: '6' } }),
      }
    }
    if (url === draftDetail.preview_url || url === reloadedDetail.preview_url) {
      return { ok: true, blob: async () => ({ __sourceUrl: url }) }
    }
    throw new Error(`Unexpected fetch: ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)

  render(<MetaReviewPanel />)
  await waitFor(() => expect(screen.getByText(/k1/)).not.toBeNull())
  fireEvent.click(screen.getByText('Review'))
  await waitFor(() => expect(screen.getByLabelText('Fixture fx-1 params')).not.toBeNull())

  fireEvent.change(screen.getByLabelText('Fixture fx-1 params'), { target: { value: '{"n":6}' } })
  fireEvent.change(screen.getByLabelText('Fixture fx-1 expected result'), { target: { value: '{"answer":"6"}' } })
  fireEvent.click(screen.getByText('Save fixture'))

  await waitFor(() => expect(screen.getByAltText('preview').src).toContain('sha256:after-edit'))
  // The refreshed detail is a full re-fetch (draft detail requested twice),
  // not a locally patched copy of the previously-loaded fixture list.
  expect(draftDetailCalls).toBe(2)
})

it('keeps Approve disabled until confirmation and the fixture threshold are met', async () => {
  installFetchMock()
  render(<MetaReviewPanel />)
  await waitFor(() => expect(screen.getByText(/k1/)).not.toBeNull())
  fireEvent.click(screen.getByText('Review'))
  await waitFor(() => expect(screen.getByLabelText('Fixture fx-1 params')).not.toBeNull())

  // Only one qualifying fixture is present (below the threshold), so Approve
  // must stay disabled even after filling in a valid name and confirming.
  fireEvent.change(screen.getByLabelText('Template name'), { target: { value: 'apples_count' } })
  fireEvent.click(screen.getByLabelText('I confirm the mathematical semantics and preview are correct'))

  expect(screen.getByRole('button', { name: 'Approve and publish' }).disabled).toBe(true)
})

it('leaves Approve disabled when the confirmation checkbox is unchecked, even with enough fixtures', async () => {
  installApprovableFetchMock()
  render(<MetaReviewPanel />)
  await waitFor(() => expect(screen.getByText(/k1/)).not.toBeNull())
  fireEvent.click(screen.getByText('Review'))
  await waitFor(() => expect(screen.getByLabelText('Fixture fx-1 params')).not.toBeNull())

  fireEvent.change(screen.getByLabelText('Template name'), { target: { value: 'apples_count' } })

  expect(screen.getByRole('button', { name: 'Approve and publish' }).disabled).toBe(true)
})

it('posts the exact approve body once enabled and returns to the pending list', async () => {
  const fetchMock = installApprovableFetchMock()
  render(<MetaReviewPanel />)
  await waitFor(() => expect(screen.getByText(/k1/)).not.toBeNull())
  fireEvent.click(screen.getByText('Review'))
  await waitFor(() => expect(screen.getByLabelText('Fixture fx-1 params')).not.toBeNull())

  fireEvent.change(screen.getByLabelText('Template name'), { target: { value: 'apples_count' } })
  fireEvent.click(screen.getByLabelText('I confirm the mathematical semantics and preview are correct'))

  const approveButton = screen.getByRole('button', { name: 'Approve and publish' })
  await waitFor(() => expect(approveButton.disabled).toBe(false))
  fireEvent.click(approveButton)

  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      '/meta/drafts/draft-1/approve',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ template_name: 'apples_count', math_semantics_confirmed: true }),
      }),
    ),
  )
  await waitFor(() => expect(screen.getByRole('heading', { name: 'Pending drafts' })).not.toBeNull())
})

it('revokes the previous preview blob URL when a fresh preview replaces it', async () => {
  const reloadedDetail = {
    ...draftDetail,
    preview_url: '/meta/preview/sha256:after-edit',
    fixtures: [
      { ...draftDetail.fixtures[0], params: { n: 6 }, expected_result: { answer: '6' } },
    ],
  }
  let draftDetailCallCount = 0
  const fetchMock = vi.fn(async (url, init = {}) => {
    if (url === '/meta/drafts?status=pending_review') {
      return { ok: true, json: async () => [draftSummary] }
    }
    if (url === '/meta/drafts?status=failed_validation') {
      return { ok: true, json: async () => [] }
    }
    if (url === '/meta/drafts/draft-1') {
      draftDetailCallCount += 1
      return { ok: true, json: async () => (draftDetailCallCount === 1 ? draftDetail : reloadedDetail) }
    }
    if (url === '/meta/drafts/draft-1/fixtures/fx-1' && init.method === 'POST') {
      return {
        ok: true,
        json: async () => ({ ...draftDetail.fixtures[0], params: { n: 6 }, expected_result: { answer: '6' } }),
      }
    }
    if (url === draftDetail.preview_url || url === reloadedDetail.preview_url) {
      return { ok: true, blob: async () => ({ __sourceUrl: url }) }
    }
    throw new Error(`Unexpected fetch: ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)

  render(<MetaReviewPanel />)
  await waitFor(() => expect(screen.getByText(/k1/)).not.toBeNull())
  fireEvent.click(screen.getByText('Review'))
  await waitFor(() => expect(screen.getByAltText('preview').src).toContain('sha256:abc'))

  fireEvent.click(screen.getByText('Save fixture'))

  await waitFor(() => expect(screen.getByAltText('preview').src).toContain('sha256:after-edit'))
  // The first draft's blob URL must be revoked once the fresh preview
  // replaces it, not merely dropped (which would leak it).
  expect(URL.revokeObjectURL).toHaveBeenCalledWith(`blob:${draftDetail.preview_url}`)
})

it('discards an out-of-order preview resolution and revokes its now-stale blob URL instead of leaking it or clobbering the newer preview', async () => {
  const staleUrl = draftDetail.preview_url
  const freshDraftDetail = { ...draftDetail, preview_url: '/meta/preview/sha256:fresh' }

  let resolveStalePreview
  const stalePreviewPromise = new Promise((resolve) => { resolveStalePreview = resolve })

  let draftDetailCallCount = 0
  const fetchMock = vi.fn(async (url, init = {}) => {
    if (url === '/meta/drafts?status=pending_review') {
      return { ok: true, json: async () => [draftSummary] }
    }
    if (url === '/meta/drafts?status=failed_validation') {
      return { ok: true, json: async () => [] }
    }
    if (url === '/meta/drafts/draft-1') {
      draftDetailCallCount += 1
      return { ok: true, json: async () => (draftDetailCallCount === 1 ? draftDetail : freshDraftDetail) }
    }
    if (url === '/meta/drafts/draft-1/fixtures/fx-1' && init.method === 'POST') {
      return { ok: true, json: async () => ({ ...draftDetail.fixtures[0] }) }
    }
    if (url === staleUrl) {
      // Deliberately left pending: this preview fetch was issued first but
      // must resolve *after* the second (fresh) preview load below has
      // already completed and won, exercising the out-of-order case.
      return stalePreviewPromise
    }
    if (url === freshDraftDetail.preview_url) {
      return { ok: true, blob: async () => ({ __sourceUrl: url }) }
    }
    throw new Error(`Unexpected fetch: ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)

  render(<MetaReviewPanel />)
  await waitFor(() => expect(screen.getByText(/k1/)).not.toBeNull())
  fireEvent.click(screen.getByText('Review'))
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(staleUrl, expect.anything()))

  // Trigger a second preview load for the same draft before the first has
  // resolved. "Save fixture" has no loading guard, so a fast double
  // interaction can reach this exact interleaving in the running app.
  fireEvent.click(screen.getByText('Save fixture'))

  await waitFor(() => expect(screen.getByAltText('preview').src).toContain('fresh'))
  const freshBlobSrc = screen.getByAltText('preview').src

  // Now let the first (stale) preview fetch resolve.
  resolveStalePreview({ ok: true, blob: async () => ({ __sourceUrl: staleUrl }) })

  await waitFor(() => expect(URL.revokeObjectURL).toHaveBeenCalledWith(`blob:${staleUrl}`))
  // The late-arriving stale result must not have clobbered the fresh preview.
  expect(screen.getByAltText('preview').src).toBe(freshBlobSrc)
})

it('revokes the preview blob URL when rejecting a draft returns to the list', async () => {
  const fetchMock = installFetchMock()
  render(<MetaReviewPanel />)
  await waitFor(() => expect(screen.getByText(/k1/)).not.toBeNull())
  fireEvent.click(screen.getByText('Review'))
  await waitFor(() => expect(screen.getByAltText('preview').src).toContain('sha256:abc'))

  fireEvent.change(screen.getByRole('textbox', { name: 'Feedback' }), { target: { value: 'tighten the guard' } })
  fireEvent.click(screen.getByText('Reject and request refinement'))

  await waitFor(() => expect(screen.getByRole('heading', { name: 'Pending drafts' })).not.toBeNull())
  expect(URL.revokeObjectURL).toHaveBeenCalledWith(`blob:${draftDetail.preview_url}`)
})

it('revokes the preview blob URL when approving a draft returns to the list', async () => {
  const fetchMock = installApprovableFetchMock()
  render(<MetaReviewPanel />)
  await waitFor(() => expect(screen.getByText(/k1/)).not.toBeNull())
  fireEvent.click(screen.getByText('Review'))
  await waitFor(() => expect(screen.getByAltText('preview').src).toContain('sha256:abc'))

  fireEvent.change(screen.getByLabelText('Template name'), { target: { value: 'apples_count' } })
  fireEvent.click(screen.getByLabelText('I confirm the mathematical semantics and preview are correct'))
  const approveButton = screen.getByRole('button', { name: 'Approve and publish' })
  await waitFor(() => expect(approveButton.disabled).toBe(false))
  fireEvent.click(approveButton)

  await waitFor(() => expect(screen.getByRole('heading', { name: 'Pending drafts' })).not.toBeNull())
  expect(URL.revokeObjectURL).toHaveBeenCalledWith(`blob:${approvableDraftDetail.preview_url}`)
})

it('revokes the preview blob URL when clicking Back to list', async () => {
  installFetchMock()
  render(<MetaReviewPanel />)
  await waitFor(() => expect(screen.getByText(/k1/)).not.toBeNull())
  fireEvent.click(screen.getByText('Review'))
  await waitFor(() => expect(screen.getByAltText('preview').src).toContain('sha256:abc'))

  fireEvent.click(screen.getByText('Back to list'))

  await waitFor(() => expect(screen.getByRole('heading', { name: 'Pending drafts' })).not.toBeNull())
  expect(URL.revokeObjectURL).toHaveBeenCalledWith(`blob:${draftDetail.preview_url}`)
})

it('revokes a preview blob URL created by a fetch that resolves after the component unmounts', async () => {
  let resolvePreviewFetch
  const previewFetchPromise = new Promise((resolve) => { resolvePreviewFetch = resolve })

  const fetchMock = vi.fn(async (url) => {
    if (url === '/meta/drafts?status=pending_review') {
      return { ok: true, json: async () => [draftSummary] }
    }
    if (url === '/meta/drafts?status=failed_validation') {
      return { ok: true, json: async () => [] }
    }
    if (url === '/meta/drafts/draft-1') {
      return { ok: true, json: async () => draftDetail }
    }
    if (url === draftDetail.preview_url) {
      // Deliberately left pending: the fetch/blob() resolution must land
      // after the component has already unmounted below.
      return previewFetchPromise
    }
    throw new Error(`Unexpected fetch: ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)

  const { unmount } = render(<MetaReviewPanel />)
  await waitFor(() => expect(screen.getByText(/k1/)).not.toBeNull())
  fireEvent.click(screen.getByText('Review'))
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(draftDetail.preview_url, expect.anything()))

  unmount()

  // Let the in-flight preview fetch resolve only now, after unmount. Nothing
  // was in previewBlobUrlRef for the unmount cleanup to revoke, so the mount
  // guard in loadPreview must revoke the just-created blob URL itself.
  resolvePreviewFetch({ ok: true, blob: async () => ({ __sourceUrl: draftDetail.preview_url }) })

  await waitFor(() => expect(URL.revokeObjectURL).toHaveBeenCalledWith(`blob:${draftDetail.preview_url}`))
})

it('revokes a preview blob URL whose fetch was still in flight when Back to list was clicked before it resolved', async () => {
  let resolvePreviewFetch
  const previewFetchPromise = new Promise((resolve) => { resolvePreviewFetch = resolve })

  const fetchMock = vi.fn(async (url) => {
    if (url === '/meta/drafts?status=pending_review') {
      return { ok: true, json: async () => [draftSummary] }
    }
    if (url === '/meta/drafts?status=failed_validation') {
      return { ok: true, json: async () => [] }
    }
    if (url === '/meta/drafts/draft-1') {
      return { ok: true, json: async () => draftDetail }
    }
    if (url === draftDetail.preview_url) {
      // Deliberately left pending: "Back to list" must be clicked (and
      // navigate away) before this preview fetch resolves. `selected` is
      // set by openDraft before it awaits loadPreview, so the button is
      // clickable at this point in the real app.
      return previewFetchPromise
    }
    throw new Error(`Unexpected fetch: ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)

  render(<MetaReviewPanel />)
  await waitFor(() => expect(screen.getByText(/k1/)).not.toBeNull())
  fireEvent.click(screen.getByText('Review'))
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(draftDetail.preview_url, expect.anything()))

  // Navigate away before the pending preview fetch resolves.
  fireEvent.click(screen.getByText('Back to list'))
  await waitFor(() => expect(screen.getByRole('heading', { name: 'Pending drafts' })).not.toBeNull())

  // Now let the in-flight preview fetch resolve. It must recognize it was
  // superseded by the navigation and revoke its blob URL instead of
  // committing it to state (there is no preview <img> to commit into
  // anyway, since the list view is showing).
  resolvePreviewFetch({ ok: true, blob: async () => ({ __sourceUrl: draftDetail.preview_url }) })

  await waitFor(() => expect(URL.revokeObjectURL).toHaveBeenCalledWith(`blob:${draftDetail.preview_url}`))
  expect(screen.queryByAltText('preview')).toBeNull()
})

it('shows approve errors from the server', async () => {
  installApprovableFetchMock({
    approveResponse: {
      ok: false,
      json: async () => ({ detail: 'Draft has too few verified real fixtures to publish' }),
    },
  })
  render(<MetaReviewPanel />)
  await waitFor(() => expect(screen.getByText(/k1/)).not.toBeNull())
  fireEvent.click(screen.getByText('Review'))
  await waitFor(() => expect(screen.getByLabelText('Fixture fx-1 params')).not.toBeNull())

  fireEvent.change(screen.getByLabelText('Template name'), { target: { value: 'apples_count' } })
  fireEvent.click(screen.getByLabelText('I confirm the mathematical semantics and preview are correct'))
  const approveButton = screen.getByRole('button', { name: 'Approve and publish' })
  await waitFor(() => expect(approveButton.disabled).toBe(false))
  fireEvent.click(approveButton)

  await waitFor(() =>
    expect(screen.getByText('Draft has too few verified real fixtures to publish')).not.toBeNull(),
  )
})
