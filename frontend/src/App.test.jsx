import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import App from './App'

const candidate = {
  candidate_id: 'c1',
  source_excerpt: 'Sarah has 4 apples and buys 3 more.',
  slide_index: 0,
  one_line_summary: 'Detected: 4 + 3',
}

const pendingScene = {
  scene_id: 's1',
  candidate_id: 'c1',
  template: 'number_line',
  grade_level: 1,
  grade_overridden: false,
  params: {
    start: 4,
    steps: [{ operation: 'add', amount: 3 }],
  },
  params_schema: {
    type: 'object',
    properties: {
      start: { title: 'Start', type: 'integer' },
      steps: {
        title: 'Steps',
        type: 'array',
        minItems: 1,
        maxItems: 3,
        items: { $ref: '#/$defs/NumberLineStep' },
      },
    },
    $defs: {
      NumberLineStep: {
        type: 'object',
        properties: {
          operation: { title: 'Operation', enum: ['add', 'subtract'], type: 'string' },
          amount: { title: 'Amount', type: 'integer' },
        },
      },
    },
  },
  status: 'pending_review',
  fallback_reason: null,
  thumbnail_url: null,
  source_excerpt: candidate.source_excerpt,
  detected_summary: candidate.one_line_summary,
}

const pendingScene2 = {
  ...pendingScene,
  scene_id: 's2',
  candidate_id: 'c2',
  source_excerpt: 'Nine minus two.',
  detected_summary: 'Detected: 9 - 2',
  params: {
    start: 9,
    steps: [{ operation: 'subtract', amount: 2 }],
  },
}

const chainedScene = {
  ...pendingScene,
  scene_id: 'chain-1',
  candidate_id: null,
  candidate_ids: ['c1', 'c2'],
  params: {
    items: [pendingScene.params, pendingScene2.params],
  },
  params_schema: {
    type: 'object',
    properties: {
      items: {
        title: 'Items',
        type: 'array',
        minItems: 2,
        maxItems: 4,
        items: { $ref: '#/$defs/NumberLineParams' },
      },
    },
    $defs: {
      NumberLineParams: pendingScene.params_schema,
      ...pendingScene.params_schema.$defs,
    },
  },
  source_excerpt: `${pendingScene.source_excerpt} / ${pendingScene2.source_excerpt}`,
  detected_summary: `${pendingScene.detected_summary} / ${pendingScene2.detected_summary}`,
}

const manualSourceScene = {
  ...pendingScene2,
  scene_id: 'manual-1',
  candidate_id: null,
  candidate_ids: null,
  source_excerpt: 'A manually entered problem.',
  detected_summary: '',
}

function jsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  }
}

function installFetchMock({
  secondUpload = false,
  clipStatus = 'approved',
  clipUrl = clipStatus === 'approved' ? '/clips/clip1' : null,
  fallbackReason = null,
  patchStatus = 'ok',
  storyboardScenes = [pendingScene],
  renderFails = false,
} = {}) {
  let uploadCount = 0
  const fetchMock = vi.fn(async (url, init = {}) => {
    if (url === '/meta/my/capabilities') return jsonResponse({ enabled: false })
    if (url === '/upload') {
      uploadCount += 1
      if (secondUpload && uploadCount === 2) {
        return jsonResponse({
          candidates: [{
            candidate_id: 'c2',
            source_excerpt: 'Nine minus two.',
            slide_index: 0,
            one_line_summary: 'Detected: 9 - 2',
          }],
        })
      }
      return jsonResponse({ candidates: [candidate] })
    }
    if (url === '/options') {
      const requested = JSON.parse(init.body).candidate_ids
      return jsonResponse({
        options: requested.map((candidateId) => ({
          candidate_id: candidateId,
          grade_level: 1,
          ambiguous: false,
          templates: [{
            template: 'number_line',
            rationale: 'shows addition as a jump',
          }],
        })),
      })
    }
    if (url === '/storyboard') {
      return jsonResponse({ scenes: storyboardScenes })
    }
    if (url === '/storyboard/chain' && init.method === 'POST') {
      return jsonResponse(chainedScene)
    }
    if (url === '/storyboard/chain-1/ungroup' && init.method === 'POST') {
      return jsonResponse({ scenes: [pendingScene, pendingScene2] })
    }
    if (url === '/storyboard/s1' && init.method === 'PATCH') {
      if (patchStatus === '422') {
        return jsonResponse(
          { detail: { errors: [{ loc: ['start'], msg: 'must be non-negative' }] } },
          422,
        )
      }
      if (patchStatus === 'malformed422') {
        return jsonResponse({ detail: 'start must be non-negative' }, 422)
      }
      const body = JSON.parse(init.body)
      return jsonResponse({
        ...pendingScene,
        params: body.params ?? pendingScene.params,
        grade_level: body.grade_level ?? pendingScene.grade_level,
        grade_overridden: body.grade_level !== undefined ? true : pendingScene.grade_overridden,
      })
    }
    if (url === '/storyboard/s1/approve') {
      return jsonResponse({ ...pendingScene, status: 'approved' })
    }
    if (url === '/storyboard/s1/reject') {
      return jsonResponse({ ...pendingScene, status: 'rejected' })
    }
    if (url === '/render') {
      if (renderFails) {
        return jsonResponse({ detail: 'Render timed out after 600s' }, 500)
      }
      return jsonResponse({
        clips: [{
          scene_id: 's1',
          candidate_id: 'c1',
          status: clipStatus,
          clip_url: clipUrl,
          fallback_reason: fallbackReason,
        }],
      })
    }
    throw new Error(`Unexpected request: ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

async function reachStoryboard() {
  const { container } = render(<App />)
  const fileInput = container.querySelector('input[type="file"]')
  const form = container.querySelector('form')
  Object.defineProperty(form, 'file', {
    configurable: true,
    value: fileInput,
  })
  fireEvent.change(fileInput, {
    target: { files: [new File(['deck'], 'deck.pptx')] },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Upload' }))

  const checkbox = await screen.findByRole('checkbox')
  fireEvent.click(checkbox)
  fireEvent.click(screen.getByRole('button', { name: 'Get visualizations' }))

  await screen.findByRole('heading', { name: 'Choose visualizations' })
  fireEvent.click(screen.getByRole('button', { name: 'Build storyboard' }))
  await screen.findByRole('heading', { name: 'Storyboard review' })
  return { container, fileInput }
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  window.history.pushState({}, '', '/')
})

it('blocks rendering when an approved scene has unsaved edits', async () => {
  installFetchMock()
  await reachStoryboard()

  fireEvent.click(screen.getByRole('button', { name: 'Approve' }))
  const renderButton = screen.getByRole('button', { name: 'Render approved' })
  await waitFor(() => expect(renderButton.disabled).toBe(false))

  fireEvent.change(screen.getByLabelText('Start'), { target: { value: '5' } })

  expect(renderButton.disabled).toBe(true)
})

it('does not combine selected scenes while one has unsaved edits', async () => {
  installFetchMock({ storyboardScenes: [pendingScene, pendingScene2] })
  await reachStoryboard()

  for (const checkbox of screen.getAllByLabelText('Combine with other selected scenes')) {
    fireEvent.click(checkbox)
  }
  expect(screen.getByRole('button', { name: 'Combine 2 into one scene' })).not.toBeNull()

  fireEvent.change(screen.getAllByLabelText('Start')[0], { target: { value: '5' } })

  expect(screen.queryByRole('button', { name: 'Combine 2 into one scene' })).toBeNull()
})

it('removes a selected scene from combine eligibility after approval', async () => {
  installFetchMock({ storyboardScenes: [pendingScene, pendingScene2] })
  await reachStoryboard()

  for (const checkbox of screen.getAllByLabelText('Combine with other selected scenes')) {
    fireEvent.click(checkbox)
  }
  fireEvent.click(screen.getAllByRole('button', { name: 'Approve' })[0])

  await waitFor(() => {
    expect(screen.queryByRole('button', { name: 'Combine 2 into one scene' })).toBeNull()
  })
})

it('combines eligible scenes and ungroups them back into their original position', async () => {
  const fetchMock = installFetchMock({
    patchStatus: '422',
    storyboardScenes: [pendingScene, manualSourceScene, pendingScene2],
  })
  await reachStoryboard()

  fireEvent.click(screen.getAllByRole('button', { name: 'Save edits' })[0])
  await screen.findByText('Start: must be non-negative')

  for (const checkbox of screen.getAllByLabelText('Combine with other selected scenes')) {
    fireEvent.click(checkbox)
  }
  fireEvent.click(screen.getByRole('button', { name: 'Combine 2 into one scene' }))

  await screen.findByText(chainedScene.detected_summary)
  const chainCall = fetchMock.mock.calls.find(([url]) => url === '/storyboard/chain')
  expect(JSON.parse(chainCall[1].body)).toEqual({ scene_ids: ['s1', 's2'] })
  expect(screen.queryByText(pendingScene.detected_summary)).toBeNull()
  expect(screen.queryByText(pendingScene2.detected_summary)).toBeNull()
  expect(screen.getByRole('button', { name: 'Ungroup' })).not.toBeNull()
  expect(
    within(screen.getByText(chainedScene.detected_summary).parentElement)
      .queryByRole('button', { name: 'Retry' }),
  ).toBeNull()
  expect(screen.queryByText('Start: must be non-negative')).toBeNull()
  expect(
    screen.getByText(chainedScene.detected_summary).compareDocumentPosition(
      screen.getByText(manualSourceScene.source_excerpt),
    ) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy()

  fireEvent.click(screen.getByRole('button', { name: 'Ungroup' }))

  await screen.findByText(pendingScene.detected_summary)
  expect(screen.getByText(pendingScene2.detected_summary)).not.toBeNull()
  expect(
    within(screen.getByText(pendingScene.detected_summary).parentElement)
      .getByRole('button', { name: 'Retry' }),
  ).not.toBeNull()
  expect(
    within(screen.getByText(pendingScene2.detected_summary).parentElement)
      .getByRole('button', { name: 'Retry' }),
  ).not.toBeNull()
  expect(screen.queryByRole('button', { name: 'Ungroup' })).toBeNull()
  expect(screen.queryByText('Start: must be non-negative')).toBeNull()
  expect(
    screen.getByText(pendingScene2.detected_summary).compareDocumentPosition(
      screen.getByText(manualSourceScene.source_excerpt),
    ) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy()
  expect(fetchMock).toHaveBeenCalledWith(
    '/storyboard/chain-1/ungroup',
    expect.objectContaining({ method: 'POST', credentials: 'include' }),
  )
})

it('does not offer manual-source pending scenes for combining', async () => {
  installFetchMock({ storyboardScenes: [pendingScene, manualSourceScene] })
  await reachStoryboard()

  expect(screen.getAllByLabelText('Combine with other selected scenes')).toHaveLength(1)
  expect(screen.queryByRole('button', { name: /Combine 2 into one scene/ })).toBeNull()
})

it('clears the prior storyboard when a new deck is uploaded', async () => {
  installFetchMock({ secondUpload: true })
  const { fileInput } = await reachStoryboard()

  fireEvent.change(fileInput, {
    target: { files: [new File(['second deck'], 'second.pptx')] },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Upload' }))

  await screen.findByText('Detected: 9 - 2')
  expect(screen.queryByRole('heading', { name: 'Storyboard review' })).toBeNull()
})

it('shows a useful upload error when the server returns non-JSON', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({
    ok: false,
    status: 500,
    json: async () => {
      throw new SyntaxError('Unexpected token I in JSON')
    },
  })))
  const { container } = render(<App />)
  const fileInput = container.querySelector('input[type="file"]')
  const form = container.querySelector('form')
  Object.defineProperty(form, 'file', {
    configurable: true,
    value: fileInput,
  })
  fireEvent.change(fileInput, {
    target: { files: [new File(['deck'], 'g1-fractions.pptx')] },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Upload' }))

  await screen.findByText('Upload failed')
  expect(screen.queryByText(/Unexpected token/)).toBeNull()
})

it('shows an explicit message when one approved scene fails to render', async () => {
  installFetchMock({ clipStatus: 'error' })
  await reachStoryboard()
  fireEvent.click(screen.getByRole('button', { name: 'Approve' }))

  const renderButton = screen.getByRole('button', { name: 'Render approved' })
  await waitFor(() => expect(renderButton.disabled).toBe(false))
  fireEvent.click(renderButton)

  await screen.findByRole('heading', { name: 'Results' })
  expect(screen.getByText('Render failed for c1')).not.toBeNull()
})

it('plays a successful render inline and keeps the download link', async () => {
  installFetchMock()
  await reachStoryboard()
  fireEvent.click(screen.getByRole('button', { name: 'Approve' }))

  const renderButton = screen.getByRole('button', { name: 'Render approved' })
  await waitFor(() => expect(renderButton.disabled).toBe(false))
  fireEvent.click(renderButton)

  const player = await screen.findByLabelText('Rendered clip c1')
  const downloadLink = screen.getByRole('link', { name: 'Download clip (c1)' })

  expect(player.tagName).toBe('VIDEO')
  expect(player.getAttribute('src')).toBe('/clips/clip1')
  expect(player.getAttribute('controls')).not.toBeNull()
  expect(player.getAttribute('preload')).toBe('metadata')
  expect(downloadLink.getAttribute('href')).toBe('/clips/clip1')
  expect(downloadLink.getAttribute('download')).not.toBeNull()
})

it('plays a fallback render inline while preserving its reason and download', async () => {
  installFetchMock({
    clipStatus: 'fallback',
    clipUrl: '/clips/fallback-clip',
    fallbackReason: 'Used a labeled text card',
  })
  await reachStoryboard()
  fireEvent.click(screen.getByRole('button', { name: 'Approve' }))

  const renderButton = screen.getByRole('button', { name: 'Render approved' })
  await waitFor(() => expect(renderButton.disabled).toBe(false))
  fireEvent.click(renderButton)

  const player = await screen.findByLabelText('Rendered clip c1')
  const downloadLink = screen.getByRole('link', { name: 'Download clip (c1)' })

  expect(player.getAttribute('src')).toBe('/clips/fallback-clip')
  expect(downloadLink.getAttribute('href')).toBe('/clips/fallback-clip')
  expect(screen.getByText('Fallback: Used a labeled text card')).not.toBeNull()
})

it('saves edits and clears the dirty flag', async () => {
  installFetchMock()
  await reachStoryboard()

  fireEvent.change(screen.getByLabelText('Start'), { target: { value: '5' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save edits' }))

  await waitFor(() => expect(screen.queryByText('Unsaved edits — Save first')).toBeNull())
})

it('rejects a scene', async () => {
  installFetchMock()
  await reachStoryboard()

  const sceneContainer = screen.getByText(pendingScene.detected_summary).parentElement
  fireEvent.click(screen.getByRole('button', { name: 'Reject' }))

  await waitFor(() => expect(sceneContainer.getAttribute('data-status')).toBe('rejected'))
})

it('updates the grade level', async () => {
  installFetchMock()
  await reachStoryboard()

  fireEvent.change(screen.getByLabelText('Grade'), { target: { value: '3' } })

  await waitFor(() => expect(document.body.textContent).toContain('(overridden)'))
})

it('surfaces 422 field errors from a PATCH without crashing', async () => {
  installFetchMock({ patchStatus: '422' })
  await reachStoryboard()

  fireEvent.click(screen.getByRole('button', { name: 'Save edits' }))

  await screen.findByText('Start: must be non-negative')
})

it('shows a save error when a 422 response has no field errors array', async () => {
  installFetchMock({ patchStatus: 'malformed422' })
  await reachStoryboard()

  fireEvent.click(screen.getByRole('button', { name: 'Save edits' }))

  await screen.findByText('start must be non-negative')
})

it('returns from results to visualization options', async () => {
  installFetchMock()
  await reachStoryboard()
  fireEvent.click(screen.getByRole('button', { name: 'Approve' }))

  const renderButton = screen.getByRole('button', { name: 'Render approved' })
  await waitFor(() => expect(renderButton.disabled).toBe(false))
  fireEvent.click(renderButton)

  await screen.findByRole('heading', { name: 'Results' })
  fireEvent.click(screen.getByRole('button', { name: 'Back to options' }))

  expect(screen.getByRole('heading', { name: 'Choose visualizations' })).not.toBeNull()
})

it('renders the dev review panel when ?meta-review is present', async () => {
  window.history.pushState({}, '', '/?meta-review')
  vi.stubGlobal('fetch', vi.fn(async (url) => {
    if (url === '/meta/drafts?status=pending_review') return jsonResponse([])
    throw new Error(`Unexpected request: ${url}`)
  }))

  render(<App />)

  await screen.findByRole('heading', { name: 'Meta-template review (dev only)' })
  expect(screen.getByText('No drafts pending review.')).not.toBeNull()
})

function installTextCardOnlyFetchMock() {
  const fetchMock = vi.fn(async (url) => {
    // The template workshop asks whether it is available as soon as a deck
    // loads. Off here: this file tests the pipeline, not the workshop.
    if (url === '/meta/my/capabilities') return jsonResponse({ enabled: false })
    if (url === '/upload') return jsonResponse({ candidates: [candidate] })
    if (url === '/options') {
      return jsonResponse({
        options: [{
          candidate_id: 'c1',
          grade_level: 3,
          ambiguous: false,
          templates: [{ template: 'text_card', rationale: 'no structural template fits' }],
        }],
      })
    }
    throw new Error(`Unexpected request: ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

async function reachOptions() {
  const { container } = render(<App />)
  const fileInput = container.querySelector('input[type="file"]')
  const form = container.querySelector('form')
  Object.defineProperty(form, 'file', { configurable: true, value: fileInput })
  fireEvent.change(fileInput, { target: { files: [new File(['deck'], 'deck.pptx')] } })
  fireEvent.click(screen.getByRole('button', { name: 'Upload' }))
  const checkbox = await screen.findByRole('checkbox')
  fireEvent.click(checkbox)
  fireEvent.click(screen.getByRole('button', { name: 'Get visualizations' }))
  await screen.findByRole('heading', { name: 'Choose visualizations' })
}

it('tells the user a new template may be learned when only the text card fits', async () => {
  installTextCardOnlyFetchMock()
  await reachOptions()
  expect(screen.getByText(/You can have one built from this problem/)).not.toBeNull()
})

it('does not show the new-template hint when a structural template is offered', async () => {
  installFetchMock()
  await reachOptions()
  expect(screen.queryByText(/You can have one built from this problem/)).toBeNull()
})

it('clears a failed render alert once a new storyboard is built', async () => {
  installFetchMock({ secondUpload: true, renderFails: true })
  const { fileInput } = await reachStoryboard()

  fireEvent.click(screen.getByRole('button', { name: 'Approve' }))
  const renderButton = screen.getByRole('button', { name: 'Render approved' })
  await waitFor(() => expect(renderButton.disabled).toBe(false))
  fireEvent.click(renderButton)
  await screen.findByText(/The render did not finish/)

  // Upload alone only unmounts the alert. The failure must not survive into the
  // next storyboard, or a fresh pipeline opens under a stale alarm.
  fireEvent.change(fileInput, {
    target: { files: [new File(['deck2'], 'deck2.pptx')] },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Upload' }))
  // Click the label text, not the input: the input sits inside the label, so a
  // direct click double-toggles and nets no selection.
  await screen.findByRole('checkbox')
  fireEvent.click(screen.getByText('Detected: 9 - 2'))
  fireEvent.click(screen.getByRole('button', { name: 'Get visualizations' }))
  await screen.findByRole('heading', { name: 'Choose visualizations' })
  fireEvent.click(screen.getByRole('button', { name: 'Build storyboard' }))
  await screen.findByRole('heading', { name: 'Storyboard review' })

  expect(screen.queryByText(/The render did not finish/)).toBeNull()
})
