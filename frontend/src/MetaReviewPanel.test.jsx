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
  teaching_plan: {
    plan_version: 3,
    learning_objective: 'Show a fraction of a whole.',
    beats: [
      { id: 'reveal', kind: 'reveal', intent: 'show the whole and its parts' },
      { id: 'conclude', kind: 'conclude', intent: 'state the fraction shown' },
    ],
  },
  // Each timed action's duration_seconds must stay <= MAX_ACTION_SECONDS
  // (2.0, backend/app/meta/dsl/scene_program.py) -- a real compiled scene
  // program can never have a single 6-second action. total_duration_seconds
  // is declared separately and deliberately does not equal the timeline's
  // own max end (0 + 2, then 2 + 1.5 = 3.5), the same way a real compiled
  // scene's declared total is a beat-budget sum, not a max-end derivation.
  timeline: [
    { at_seconds: 0, duration_seconds: 2, beat_id: 'reveal' },
    { at_seconds: 2, duration_seconds: 1.5, beat_id: 'conclude' },
  ],
  total_duration_seconds: 6,
  // artifact_hash matches the draft's own artifact_hash below -- approval
  // precondition 5 refuses a mismatch as "quality report is stale".
  quality_report: { passed: true, checks: [], artifact_hash: 'sha256:abc' },
  classifier_bullet: 'use for fraction-of-whole bars',
  artifact_hash: 'sha256:abc',
  validation_report: { passed: true },
  preview_url: '/meta/preview/sha256:abc',
  required_fixture_count: 1,
  fixtures: [
    {
      id: 'fx-1', kind: 'positive', expected_outcome: 'accept', generation_method: 'proposed',
      observation_id: 'obs-1',
      params: { n: 5 }, expected_result: { answer: '5' },
      structural_check_passed: true, structural_check_detail: 'ok', source_excerpt: '5 apples',
    },
  ],
  reviewer_feedback: null,
}

// A draft whose teaching plan/timeline/quality-report evidence exercises the
// v3 review panels: a realistic beat, an adaptive compiled duration, and a
// quality report whose checks span both label-mapped categories (Pacing,
// Anchor alignment).
const v3DraftDetail = {
  ...draftDetail,
  teaching_plan: {
    plan_version: 3,
    learning_objective: 'Compare three numbers to find the largest.',
    beats: [
      { id: 'reveal_values', kind: 'reveal', intent: 'show the ordered values together' },
      { id: 'focus_largest', kind: 'focus', intent: 'focus on the largest value' },
      { id: 'conclude', kind: 'conclude', intent: 'state the largest value' },
    ],
  },
  // Three schema-legal actions (each <= MAX_ACTION_SECONDS = 2.0) whose max
  // end (0 + 2, 2 + 2, 4 + 1.5 = 5.5) is deliberately different from the
  // declared total_duration_seconds below (7.5) -- this is the case that
  // catches a panel that derives the total from timeline entries instead of
  // reading the field the backend declares (Task 12 review finding #1).
  timeline: [
    { at_seconds: 0, duration_seconds: 2, beat_id: 'reveal_values' },
    { at_seconds: 2, duration_seconds: 2, beat_id: 'focus_largest' },
    { at_seconds: 4, duration_seconds: 1.5, beat_id: 'conclude' },
  ],
  total_duration_seconds: 7.5,
  quality_report: {
    passed: true,
    artifact_hash: 'sha256:abc',
    checks: [
      { code: 'timeline_duration', passed: true, path: 'total_duration_seconds', detail: 'passed' },
      { code: 'serial_simple_reveal', passed: true, path: 'timeline', detail: 'passed' },
      { code: 'premature_answer_emphasis', passed: true, path: 'visuals.evaluated_answer', detail: 'passed' },
      { code: 'conclusion_hold_too_short', passed: true, path: 'timeline', detail: 'passed' },
      { code: 'unexplained_idle_time', passed: true, path: 'timeline', detail: 'passed' },
      { code: 'static_process_visual', passed: true, path: 'strategy', detail: 'passed' },
      { code: 'collection_anchor_for_item', passed: true, path: 'relations', detail: 'passed' },
      { code: 'dimension_anchor_mismatch', passed: true, path: 'relations', detail: 'passed' },
      { code: 'callout_collision', passed: true, path: 'timeline', detail: 'passed' },
    ],
  },
}

function installV3FetchMock() {
  const fetchMock = vi.fn(async (url) => {
    if (url === '/meta/versions') return { ok: true, json: async () => [] }
    if (url === '/meta/drafts') {
      return { ok: true, json: async () => [draftSummary] }
    }
    if (url === '/meta/drafts/draft-1') {
      return { ok: true, json: async () => v3DraftDetail }
    }
    if (url === v3DraftDetail.preview_url) {
      return { ok: true, blob: async () => ({ __sourceUrl: url }) }
    }
    throw new Error(`Unexpected fetch: ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function installFetchMock({ fixtureResponse } = {}) {
  const fetchMock = vi.fn(async (url, init = {}) => {
    if (url === '/meta/versions') return { ok: true, json: async () => [] }
    if (url === '/meta/drafts') {
      return { ok: true, json: async () => [draftSummary] }
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
    observation_id: `obs-${id}`,
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
    if (url === '/meta/versions') return { ok: true, json: async () => [] }
    if (url === '/meta/drafts') {
      return { ok: true, json: async () => [draftSummary] }
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

it('shows teaching beats, adaptive duration, and passing quality evidence', async () => {
  installV3FetchMock()
  render(<MetaReviewPanel />)
  fireEvent.click(await screen.findByText('Review'))
  expect(await screen.findByRole('heading', { name: 'Teaching plan' })).not.toBeNull()
  expect(screen.getByText('Reveal · show the ordered values together')).not.toBeNull()
  expect(screen.getByText('7.5 seconds')).not.toBeNull()
  expect(screen.getByText('Pacing passed')).not.toBeNull()
  expect(screen.getByText('Anchor alignment passed')).not.toBeNull()
})

// The same v3 draft, but with one Pacing check FAILING. No fixture in this
// file previously contained `passed: false`, which is why nothing here could
// tell `.every` from `.some` in passingQualityCategoryLabels, and why nothing
// asserted that raw check codes/paths/details stay out of the DOM.
const failingPacingCheck = {
  code: 'timeline_over_budget',
  passed: false,
  path: 'total_duration_seconds',
  detail: 'scene duration exceeds the 12-second budget',
}

const failingQualityDraftDetail = {
  ...v3DraftDetail,
  quality_report: {
    passed: false,
    checks: [...v3DraftDetail.quality_report.checks, failingPacingCheck],
  },
}

it('suppresses a category label when any check in that category failed', async () => {
  // MetaReviewPanel returns a category label only when EVERY matching check
  // passed. Changing that `.every` to `.some` would show "Pacing passed" beside
  // a failed pacing check -- the checklist's whole claim is that it is
  // pass-only. Anchor alignment (all passing) must still be labelled, so this
  // proves per-category suppression rather than a blanket hide.
  vi.stubGlobal('fetch', vi.fn(async (url) => {
    if (url === '/meta/drafts') return { ok: true, json: async () => [draftSummary] }
    if (url === '/meta/drafts/draft-1') return { ok: true, json: async () => failingQualityDraftDetail }
    if (url === failingQualityDraftDetail.preview_url) {
      return { ok: true, blob: async () => ({ __sourceUrl: url }) }
    }
    throw new Error(`Unexpected fetch: ${url}`)
  }))

  render(<MetaReviewPanel />)
  fireEvent.click(await screen.findByText('Review'))
  await screen.findByRole('heading', { name: 'Teaching plan' })

  expect(screen.queryByText('Pacing passed')).toBeNull()
  expect(screen.getByText('Anchor alignment passed')).not.toBeNull()
})

it('never renders a raw quality-check code, path, or detail string', async () => {
  // The reviewer-facing checklist promises human-readable category labels only.
  // Rendering `{check.code}: {check.detail}` beside each label would otherwise
  // pass every test in this file.
  vi.stubGlobal('fetch', vi.fn(async (url) => {
    if (url === '/meta/drafts') return { ok: true, json: async () => [draftSummary] }
    if (url === '/meta/drafts/draft-1') return { ok: true, json: async () => failingQualityDraftDetail }
    if (url === failingQualityDraftDetail.preview_url) {
      return { ok: true, blob: async () => ({ __sourceUrl: url }) }
    }
    throw new Error(`Unexpected fetch: ${url}`)
  }))

  const { container } = render(<MetaReviewPanel />)
  fireEvent.click(await screen.findByText('Review'))
  await screen.findByRole('heading', { name: 'Teaching plan' })

  // Derived from the fixture itself, so a newly-added check cannot slip past.
  const rendered = container.textContent
  failingQualityDraftDetail.quality_report.checks.forEach((check) => {
    expect(rendered).not.toContain(check.code)
    // Structured paths only: bare one-word paths like "timeline" are ordinary
    // English, so asserting their absence would be brittle rather than
    // meaningful. Every path that identifies an internal location does contain
    // a "." or "_".
    if (/[._]/.test(check.path)) expect(rendered).not.toContain(check.path)
  })
  // The passing checks' detail is the word "passed", which legitimately appears
  // in the category labels; the failing check's detail is the interesting one.
  expect(rendered).not.toContain(failingPacingCheck.detail)
})

it('keeps Approve disabled when the validation report has not passed, even with every other gate satisfied', async () => {
  // `canApprove`'s `&& validationPassed` conjunct: without it the panel offers
  // a button that can only ever 422 at the server's precondition 3.
  const unvalidatedDraftDetail = {
    ...approvableDraftDetail,
    validation_report: { passed: false, negative_predicate_coverage: [0] },
  }
  vi.stubGlobal('fetch', vi.fn(async (url) => {
    if (url === '/meta/drafts') return { ok: true, json: async () => [draftSummary] }
    if (url === '/meta/drafts/draft-1') return { ok: true, json: async () => unvalidatedDraftDetail }
    if (url === unvalidatedDraftDetail.preview_url) {
      return { ok: true, blob: async () => ({ __sourceUrl: url }) }
    }
    throw new Error(`Unexpected fetch: ${url}`)
  }))

  render(<MetaReviewPanel />)
  fireEvent.click(await screen.findByText('Review'))
  await screen.findByLabelText('Fixture fx-1 params')

  fireEvent.change(screen.getByLabelText('Template name'), { target: { value: 'apples_count' } })
  fireEvent.click(screen.getByLabelText('I confirm the mathematical semantics and preview are correct'))

  // Every other client-side gate is satisfied: 5 qualifying fixtures against a
  // required count of 1, full predicate coverage, a valid slug and the
  // confirmation checked.
  expect(
    screen.getByRole('heading', { name: 'Approve' }).nextElementSibling.textContent,
  ).toContain('Verified fixtures: 5 / 1 required.')
  expect(screen.getByRole('button', { name: 'Approve and publish' }).disabled).toBe(true)
})

it('keeps Approve disabled when a guard predicate has no negative witness, even with every other gate satisfied', async () => {
  // `canApprove`'s `&& hasFullPredicateCoverage` conjunct: the server refuses
  // at precondition 7, so without this the button 422s.
  const uncoveredDraftDetail = {
    ...approvableDraftDetail,
    guard_document: {
      guard_version: 1,
      predicates: [
        { predicate: 'positive', value: { node: 'field_ref', field: 'n' } },
        { predicate: 'positive', value: { node: 'field_ref', field: 'm' } },
      ],
    },
    validation_report: { passed: true, negative_predicate_coverage: [0] },
  }
  vi.stubGlobal('fetch', vi.fn(async (url) => {
    if (url === '/meta/drafts') return { ok: true, json: async () => [draftSummary] }
    if (url === '/meta/drafts/draft-1') return { ok: true, json: async () => uncoveredDraftDetail }
    if (url === uncoveredDraftDetail.preview_url) {
      return { ok: true, blob: async () => ({ __sourceUrl: url }) }
    }
    throw new Error(`Unexpected fetch: ${url}`)
  }))

  render(<MetaReviewPanel />)
  fireEvent.click(await screen.findByText('Review'))
  await screen.findByLabelText('Fixture fx-1 params')

  fireEvent.change(screen.getByLabelText('Template name'), { target: { value: 'apples_count' } })
  fireEvent.click(screen.getByLabelText('I confirm the mathematical semantics and preview are correct'))

  expect(screen.getByRole('button', { name: 'Approve and publish' }).disabled).toBe(true)
})

it('keeps Approve disabled when the quality report is missing, even with every other gate satisfied', async () => {
  // `canApprove`'s quality-report conjunct: without it the panel offers a
  // button the server refuses at approval precondition 5.
  const noQualityDraftDetail = { ...approvableDraftDetail, quality_report: null }
  vi.stubGlobal('fetch', vi.fn(async (url) => {
    if (url === '/meta/drafts') return { ok: true, json: async () => [draftSummary] }
    if (url === '/meta/drafts/draft-1') return { ok: true, json: async () => noQualityDraftDetail }
    if (url === noQualityDraftDetail.preview_url) return { ok: true, blob: async () => ({ __sourceUrl: url }) }
    throw new Error(`Unexpected fetch: ${url}`)
  }))

  render(<MetaReviewPanel />)
  fireEvent.click(await screen.findByText('Review'))
  await screen.findByLabelText('Fixture fx-1 params')

  fireEvent.change(screen.getByLabelText('Template name'), { target: { value: 'apples_count' } })
  fireEvent.click(screen.getByLabelText('I confirm the mathematical semantics and preview are correct'))

  expect(screen.getByRole('button', { name: 'Approve and publish' }).disabled).toBe(true)
})

it('keeps Approve disabled when the quality report is stale (artifact hash mismatch)', async () => {
  // Approval precondition 5 refuses a quality report whose artifact_hash does
  // not equal the draft's own, and the client must too.
  const staleQualityDraftDetail = {
    ...approvableDraftDetail,
    quality_report: { passed: true, checks: [], artifact_hash: 'sha256:earlier' },
  }
  vi.stubGlobal('fetch', vi.fn(async (url) => {
    if (url === '/meta/drafts') return { ok: true, json: async () => [draftSummary] }
    if (url === '/meta/drafts/draft-1') return { ok: true, json: async () => staleQualityDraftDetail }
    if (url === staleQualityDraftDetail.preview_url) return { ok: true, blob: async () => ({ __sourceUrl: url }) }
    throw new Error(`Unexpected fetch: ${url}`)
  }))

  render(<MetaReviewPanel />)
  fireEvent.click(await screen.findByText('Review'))
  await screen.findByLabelText('Fixture fx-1 params')

  fireEvent.change(screen.getByLabelText('Template name'), { target: { value: 'apples_count' } })
  fireEvent.click(screen.getByLabelText('I confirm the mathematical semantics and preview are correct'))

  expect(screen.getByRole('button', { name: 'Approve and publish' }).disabled).toBe(true)
})

it('shows a Rendered output passed label when every render-gate check passed', async () => {
  // The reviewer needs an in-panel confirmation that the render probe gates
  // actually ran -- a draft that reaches pending_review has already cleared
  // them, but nothing in the UI said so until this category was added.
  const renderedDraftDetail = {
    ...draftDetail,
    quality_report: {
      passed: true,
      artifact_hash: 'sha256:abc',
      checks: [
        { code: 'blank_probe_frame', passed: true, path: 'frames', detail: 'passed' },
        { code: 'frame_out_of_bounds', passed: true, path: 'visual_bounds', detail: 'passed' },
        { code: 'anchor_alignment_mismatch', passed: true, path: 'anchors', detail: 'passed' },
        { code: 'rendered_relation_mismatch', passed: true, path: 'relations', detail: 'passed' },
        { code: 'rendered_state_mismatch', passed: true, path: 'state_events', detail: 'passed' },
        { code: 'state_order_invalid', passed: true, path: 'state_events', detail: 'passed' },
        { code: 'undeclared_path_event', passed: true, path: 'manifest', detail: 'passed' },
        { code: 'final_answer_not_persistent', passed: true, path: 'timeline', detail: 'passed' },
        { code: 'render_probe_contract_invalid', passed: true, path: 'manifest', detail: 'passed' },
      ],
    },
  }
  vi.stubGlobal('fetch', vi.fn(async (url) => {
    if (url === '/meta/drafts') return { ok: true, json: async () => [draftSummary] }
    if (url === '/meta/drafts/draft-1') return { ok: true, json: async () => renderedDraftDetail }
    if (url === renderedDraftDetail.preview_url) return { ok: true, blob: async () => ({ __sourceUrl: url }) }
    throw new Error(`Unexpected fetch: ${url}`)
  }))

  render(<MetaReviewPanel />)
  fireEvent.click(await screen.findByText('Review'))
  await screen.findByRole('heading', { name: 'Teaching plan' })

  expect(screen.getByText('Rendered output passed')).not.toBeNull()
})

it('suppresses the Rendered output label when a render-probe check failed', async () => {
  // A render-probe code that is not in QUALITY_CHECK_CATEGORIES's Rendered
  // output set would never drop the "Rendered output passed" label -- the
  // category filter matches on code, so an unmapped failure is invisible to
  // passingQualityCategoryLabels. This test would fail with the two omitted
  // codes (visual_overlap, dimension_label_missing) before the fix.
  const failingRenderedDraftDetail = {
    ...draftDetail,
    quality_report: {
      passed: false,
      artifact_hash: 'sha256:abc',
      checks: [
        { code: 'blank_probe_frame', passed: true, path: 'frames', detail: 'passed' },
        { code: 'visual_overlap', passed: false, path: 'visual_bounds.rect_a', detail: 'unrelated visuals overlap' },
      ],
    },
  }
  vi.stubGlobal('fetch', vi.fn(async (url) => {
    if (url === '/meta/drafts') return { ok: true, json: async () => [draftSummary] }
    if (url === '/meta/drafts/draft-1') return { ok: true, json: async () => failingRenderedDraftDetail }
    if (url === failingRenderedDraftDetail.preview_url) {
      return { ok: true, blob: async () => ({ __sourceUrl: url }) }
    }
    throw new Error(`Unexpected fetch: ${url}`)
  }))

  render(<MetaReviewPanel />)
  fireEvent.click(await screen.findByText('Review'))
  await screen.findByRole('heading', { name: 'Teaching plan' })

  expect(screen.queryByText('Rendered output passed')).toBeNull()
})

it('does not crash when teaching_plan is a minimal plan_version-only document', async () => {
  // The review API declares teaching_plan as an arbitrary dict, so a minimal
  // {plan_version: 3} can reach the panel even though the backend's own
  // validation would normally require a learning_objective and beats. Guarding
  // the accessors keeps a shape-poor draft from erasing the whole page.
  const minimalDraftDetail = {
    ...draftDetail,
    teaching_plan: { plan_version: 3 },
  }
  vi.stubGlobal('fetch', vi.fn(async (url) => {
    if (url === '/meta/drafts') return { ok: true, json: async () => [draftSummary] }
    if (url === '/meta/drafts/draft-1') return { ok: true, json: async () => minimalDraftDetail }
    if (url === minimalDraftDetail.preview_url) return { ok: true, blob: async () => ({ __sourceUrl: url }) }
    throw new Error(`Unexpected fetch: ${url}`)
  }))

  render(<MetaReviewPanel />)
  fireEvent.click(await screen.findByText('Review'))

  expect(await screen.findByRole('heading', { name: 'Teaching plan' })).not.toBeNull()
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
    '/meta/drafts',
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
      if (url === '/meta/drafts') return { ok: true, json: async () => [draftSummary] }
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

it('explains why a draft with a failing validation report cannot be approved', async () => {
  // The draft stays pending_review -- only pending_review drafts are ever
  // fetchable at all (Task 12's privacy rule) -- but its most recent
  // validation report has not passed yet, so Approve must stay blocked with
  // an explanation.
  const failedDraftDetail = {
    ...draftDetail,
    guard_document: { guard_version: 1, predicates: [{ predicate: 'positive' }, { predicate: 'ordered' }] },
    validation_report: {
      passed: false,
      negative_predicate_coverage: [0],
    },
  }
  vi.stubGlobal('fetch', vi.fn(async (url) => {
    if (url === '/meta/drafts') return { ok: true, json: async () => [draftSummary] }
    if (url === '/meta/drafts/draft-1') return { ok: true, json: async () => failedDraftDetail }
    if (url === failedDraftDetail.preview_url) return { ok: true, blob: async () => ({ __sourceUrl: url }) }
    throw new Error(`Unexpected fetch: ${url}`)
  }))

  render(<MetaReviewPanel />)
  await waitFor(() => expect(screen.getByText(/k1/)).not.toBeNull())
  fireEvent.click(screen.getByText('Review'))

  await waitFor(() =>
    expect(screen.getByText("This draft failed automatic validation and can't be approved yet.")).not.toBeNull(),
  )
  expect(screen.getByText('1 of 2 guard predicates (#1) have no guard case proving they correctly reject bad input.')).not.toBeNull()
})

// The reachable no-evidence shape: editing a fixture's params nulls the whole
// validation_report (review_api.update_fixture), leaving a pending_review draft
// with no report at all -- not a failing one.
const clearedDraftDetail = {
  ...draftDetail,
  guard_document: { guard_version: 1, predicates: [{ predicate: 'positive' }, { predicate: 'ordered' }] },
  validation_report: null,
  quality_report: null,
  preview_url: null,
}

function installClearedFetchMock(overrides = {}) {
  const restored = {
    ...clearedDraftDetail,
    validation_report: { passed: true, negative_predicate_coverage: [0, 1] },
    quality_report: { passed: true, checks: [] },
    preview_url: '/meta/preview/sha256:revalidated',
  }
  const fetchMock = vi.fn(async (url, options) => {
    if (url === '/meta/drafts') return { ok: true, json: async () => [draftSummary] }
    if (url === '/meta/drafts/draft-1') return { ok: true, json: async () => clearedDraftDetail }
    if (url === '/meta/drafts/draft-1/revalidate') {
      expect(options.method).toBe('POST')
      return overrides.revalidate ?? { ok: true, json: async () => restored }
    }
    if (url === restored.preview_url) return { ok: true, blob: async () => ({ __sourceUrl: url }) }
    throw new Error(`Unexpected fetch: ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

it('offers to re-validate a draft whose fixture edit cleared the validation evidence', async () => {
  installClearedFetchMock()

  render(<MetaReviewPanel />)
  await waitFor(() => expect(screen.getByText(/k1/)).not.toBeNull())
  fireEvent.click(screen.getByText('Review'))

  await waitFor(() =>
    expect(
      screen.getByText("Your fixture edit cleared this draft's validation evidence, so it can't be approved."),
    ).not.toBeNull(),
  )
  expect(screen.getByText('Re-validate this draft')).not.toBeNull()
  // Rejecting is no longer the only way out, so the copy must not say that.
  expect(screen.queryByText(/Validation cannot be re-run/)).toBeNull()
  // The failure-specific details belong to the other branch -- a cleared
  // report has no guard coverage to report a shortfall against.
  expect(screen.queryByText(/have no guard case proving/)).toBeNull()
  expect(screen.queryByText("This draft failed automatic validation and can't be approved yet.")).toBeNull()
})

it('re-validates a cleared draft and shows the restored evidence', async () => {
  const fetchMock = installClearedFetchMock()

  render(<MetaReviewPanel />)
  await waitFor(() => expect(screen.getByText(/k1/)).not.toBeNull())
  fireEvent.click(screen.getByText('Review'))
  await waitFor(() => expect(screen.getByText('Re-validate this draft')).not.toBeNull())

  fireEvent.click(screen.getByText('Re-validate this draft'))

  // The banner is gone because the route returned the refreshed draft, and the
  // restored preview is displayed.
  await waitFor(() =>
    expect(
      screen.queryByText("Your fixture edit cleared this draft's validation evidence, so it can't be approved."),
    ).toBeNull(),
  )
  await waitFor(() =>
    expect(screen.getByAltText('preview').getAttribute('src')).toBe('blob:/meta/preview/sha256:revalidated'),
  )
  // The route answers with the whole draft, so re-validating must not need a
  // second detail fetch.
  const detailFetches = fetchMock.mock.calls.filter(([url]) => url === '/meta/drafts/draft-1')
  expect(detailFetches).toHaveLength(1)
})

it('surfaces the reason a re-validation failed and keeps the draft open', async () => {
  installClearedFetchMock({
    revalidate: {
      ok: false,
      status: 422,
      json: async () => ({
        detail: 'Revalidation failed at fixtures[fixture-0] (fixture_validation_failed): '
          + 'expected fixture behavior consistent with the proposed template, '
          + 'observed not grounded in source: n -- correct the fixture or candidate documents and regenerate',
      }),
    },
  })

  render(<MetaReviewPanel />)
  await waitFor(() => expect(screen.getByText(/k1/)).not.toBeNull())
  fireEvent.click(screen.getByText('Review'))
  await waitFor(() => expect(screen.getByText('Re-validate this draft')).not.toBeNull())

  fireEvent.click(screen.getByText('Re-validate this draft'))

  await waitFor(() => expect(screen.getByText(/not grounded in source: n/)).not.toBeNull())
  // The reviewer stays on the draft with the banner up, free to correct the
  // fixture and re-run.
  expect(
    screen.getByText("Your fixture edit cleared this draft's validation evidence, so it can't be approved."),
  ).not.toBeNull()
  expect(screen.getByText('Re-validate this draft')).not.toBeNull()
})

it('labels a passing boundary fixture as accepting, not as a rejection guard case', async () => {
  const boundaryDraftDetail = {
    ...draftDetail,
    fixtures: [
      {
        id: 'fx-2', kind: 'boundary', expected_outcome: 'accept', generation_method: 'proposed',
        params: { n: 0 }, expected_result: { answer: '0' },
        structural_check_passed: true, structural_check_detail: 'ok', source_excerpt: '0 apples',
      },
    ],
  }
  vi.stubGlobal('fetch', vi.fn(async (url) => {
    if (url === '/meta/drafts') return { ok: true, json: async () => [draftSummary] }
    if (url === '/meta/drafts/draft-1') return { ok: true, json: async () => boundaryDraftDetail }
    if (url === boundaryDraftDetail.preview_url) return { ok: true, blob: async () => ({ __sourceUrl: url }) }
    throw new Error(`Unexpected fetch: ${url}`)
  }))

  render(<MetaReviewPanel />)
  await waitFor(() => expect(screen.getByText(/k1/)).not.toBeNull())
  fireEvent.click(screen.getByText('Review'))

  await waitFor(() =>
    expect(screen.getByText('Boundary example — edge case that should still compute correctly')).not.toBeNull(),
  )
  expect(screen.queryByText(/should be rejected/)).toBeNull()
  // Boundary fixtures never count toward the requirement (only `kind: positive`
  // does) and are shown read-only under "Guard cases" -- no answer field to fill in.
  expect(screen.queryByLabelText('Fixture fx-2 expected result')).toBeNull()
  expect(screen.queryByText('Save fixture')).toBeNull()
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
    if (url === '/meta/versions') return { ok: true, json: async () => [] }
    if (url === '/meta/drafts') {
      return { ok: true, json: async () => [draftSummary] }
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

it('enables Approve when the configured fixture threshold is met', async () => {
  installFetchMock()
  render(<MetaReviewPanel />)
  await waitFor(() => expect(screen.getByText(/k1/)).not.toBeNull())
  fireEvent.click(screen.getByText('Review'))
  await waitFor(() => expect(screen.getByLabelText('Fixture fx-1 params')).not.toBeNull())

  fireEvent.change(screen.getByLabelText('Template name'), { target: { value: 'apples_count' } })
  fireEvent.click(screen.getByLabelText('I confirm the mathematical semantics and preview are correct'))

  expect(
    screen.getByRole('heading', { name: 'Approve' }).nextElementSibling.textContent,
  ).toContain('Verified fixtures: 1 / 1 required.')
  expect(screen.getByRole('button', { name: 'Approve and publish' }).disabled).toBe(false)
})

it('counts duplicate fixtures from one observation only once', async () => {
  const duplicateDraftDetail = {
    ...approvableDraftDetail,
    required_fixture_count: 2,
    fixtures: [
      _qualifyingFixture('fx-1'),
      { ..._qualifyingFixture('fx-2'), observation_id: 'obs-fx-1' },
    ],
  }
  vi.stubGlobal('fetch', vi.fn(async (url) => {
    if (url === '/meta/drafts') return { ok: true, json: async () => [draftSummary] }
    if (url === '/meta/drafts/draft-1') return { ok: true, json: async () => duplicateDraftDetail }
    if (url === duplicateDraftDetail.preview_url) {
      return { ok: true, blob: async () => ({ __sourceUrl: url }) }
    }
    throw new Error(`Unexpected fetch: ${url}`)
  }))

  render(<MetaReviewPanel />)
  await waitFor(() => expect(screen.getByText(/k1/)).not.toBeNull())
  fireEvent.click(screen.getByText('Review'))
  await waitFor(() => expect(screen.getByLabelText('Fixture fx-1 params')).not.toBeNull())

  fireEvent.change(screen.getByLabelText('Template name'), { target: { value: 'apples_count' } })
  fireEvent.click(screen.getByLabelText('I confirm the mathematical semantics and preview are correct'))

  expect(
    screen.getByRole('heading', { name: 'Approve' }).nextElementSibling.textContent,
  ).toContain('Verified fixtures: 1 / 2 required.')
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
    if (url === '/meta/versions') return { ok: true, json: async () => [] }
    if (url === '/meta/drafts') {
      return { ok: true, json: async () => [draftSummary] }
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
    if (url === '/meta/versions') return { ok: true, json: async () => [] }
    if (url === '/meta/drafts') {
      return { ok: true, json: async () => [draftSummary] }
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
    if (url === '/meta/versions') return { ok: true, json: async () => [] }
    if (url === '/meta/drafts') {
      return { ok: true, json: async () => [draftSummary] }
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
    if (url === '/meta/versions') return { ok: true, json: async () => [] }
    if (url === '/meta/drafts') {
      return { ok: true, json: async () => [draftSummary] }
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

// ------------------------------------------------- shared template library

const ownedVersion = {
  id: 'tv-own', template_name: 'leftover_pair', fingerprint_key: 'k-own',
  owner_session_id: 'session-a1f', created_at: '2026-08-04T00:00:00Z',
}
const sharedVersion = {
  id: 'tv-shared', template_name: 'boundary_trace', fingerprint_key: 'k-shared',
  owner_session_id: null, created_at: '2026-08-03T00:00:00Z',
}

function installLibraryFetchMock({ versions = [ownedVersion, sharedVersion], promoteResponse } = {}) {
  const fetchMock = vi.fn(async (url, init = {}) => {
    if (url === '/meta/drafts') {
      return { ok: true, json: async () => [] }
    }
    if (url === '/meta/versions') return { ok: true, json: async () => versions }
    if (url === '/meta/versions/tv-own/promote' && init.method === 'POST') {
      return promoteResponse || {
        ok: true, json: async () => ({ ...ownedVersion, owner_session_id: null }),
      }
    }
    throw new Error(`Unexpected fetch: ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

it('lists the live template library with who owns each version', async () => {
  installLibraryFetchMock()

  render(<MetaReviewPanel />)

  await screen.findByText('leftover_pair')
  expect(screen.getByText(/session-a1f/)).not.toBeNull()
  expect(screen.getByText('boundary_trace')).not.toBeNull()
})

it('offers to share only the versions still private to one session', async () => {
  installLibraryFetchMock()

  render(<MetaReviewPanel />)

  await screen.findByText('leftover_pair')
  expect(screen.getAllByRole('button', { name: /Share with everyone/ })).toHaveLength(1)
})

it('says a shared version is already shared instead of offering it again', async () => {
  installLibraryFetchMock({ versions: [sharedVersion] })

  render(<MetaReviewPanel />)

  await screen.findByText('boundary_trace')
  expect(screen.getByText('Shared with everyone')).not.toBeNull()
  expect(screen.queryByRole('button', { name: /Share with everyone/ })).toBeNull()
})

it('shares a version with everyone', async () => {
  const fetchMock = installLibraryFetchMock()

  render(<MetaReviewPanel />)
  fireEvent.click(await screen.findByRole('button', { name: /Share with everyone/ }))

  await waitFor(() => {
    const posted = fetchMock.mock.calls.find(
      ([url, init]) => url === '/meta/versions/tv-own/promote' && init?.method === 'POST',
    )
    expect(posted).not.toBeUndefined()
  })
})

it('reports why sharing was refused', async () => {
  installLibraryFetchMock({
    promoteResponse: {
      ok: false,
      status: 422,
      json: async () => ({
        detail: 'This template has too few verified real examples to share (1 of 5)',
      }),
    },
  })

  render(<MetaReviewPanel />)
  fireEvent.click(await screen.findByRole('button', { name: /Share with everyone/ }))

  expect(await screen.findByText(/too few verified real examples/)).not.toBeNull()
})

it('says so when the library is empty', async () => {
  installLibraryFetchMock({ versions: [] })

  render(<MetaReviewPanel />)

  expect(await screen.findByText('No templates are live yet.')).not.toBeNull()
})
