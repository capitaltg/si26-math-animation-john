import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
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
  patchStatus = 'ok',
  storyboardScenes = [pendingScene],
} = {}) {
  let uploadCount = 0
  const fetchMock = vi.fn(async (url, init = {}) => {
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
      return jsonResponse({
        options: [{
          candidate_id: 'c1',
          grade_level: 1,
          ambiguous: false,
          templates: [{
            template: 'number_line',
            rationale: 'shows addition as a jump',
          }],
        }],
      })
    }
    if (url === '/storyboard') {
      return jsonResponse({ scenes: storyboardScenes })
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
      return jsonResponse({
        clips: [{
          scene_id: 's1',
          candidate_id: 'c1',
          status: clipStatus,
          clip_url: clipStatus === 'approved' ? '/clips/clip1' : null,
          fallback_reason: null,
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
  fireEvent.click(screen.getByRole('button', { name: 'Get options.' }))

  await screen.findByRole('heading', { name: 'Choose visualizations' })
  fireEvent.click(screen.getByRole('button', { name: 'Review storyboard.' }))
  await screen.findByRole('heading', { name: 'Storyboard review' })
  return { container, fileInput }
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

it('blocks rendering when an approved scene has unsaved edits', async () => {
  installFetchMock()
  await reachStoryboard()

  fireEvent.click(screen.getByRole('button', { name: 'Approve' }))
  const renderButton = screen.getByRole('button', { name: 'Render approved' })
  await waitFor(() => expect(renderButton.disabled).toBe(false))

  fireEvent.change(screen.getByLabelText('Start:'), { target: { value: '5' } })

  expect(renderButton.disabled).toBe(true)
})

it('does not combine selected scenes while one has unsaved edits', async () => {
  installFetchMock({ storyboardScenes: [pendingScene, pendingScene2] })
  await reachStoryboard()

  for (const checkbox of screen.getAllByLabelText('Combine with other selected scenes')) {
    fireEvent.click(checkbox)
  }
  expect(screen.getByRole('button', { name: 'Combine 2 into one scene' })).not.toBeNull()

  fireEvent.change(screen.getAllByLabelText('Start:')[0], { target: { value: '5' } })

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

it('saves edits and clears the dirty flag', async () => {
  installFetchMock()
  await reachStoryboard()

  fireEvent.change(screen.getByLabelText('Start:'), { target: { value: '5' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save edits' }))

  await waitFor(() => expect(screen.queryByText('Unsaved edits — Save first')).toBeNull())
})

it('rejects a scene', async () => {
  installFetchMock()
  await reachStoryboard()

  const sceneContainer = screen.getByText(pendingScene.detected_summary).parentElement
  fireEvent.click(screen.getByRole('button', { name: 'Reject' }))

  await waitFor(() => expect(sceneContainer.style.background).toContain('254, 242, 242'))
})

it('updates the grade level', async () => {
  installFetchMock()
  await reachStoryboard()

  fireEvent.change(screen.getByLabelText('Grade:'), { target: { value: '3' } })

  await waitFor(() => expect(document.body.textContent).toContain('(overridden)'))
})

it('surfaces 422 field errors from a PATCH without crashing', async () => {
  installFetchMock({ patchStatus: '422' })
  await reachStoryboard()

  fireEvent.click(screen.getByRole('button', { name: 'Save edits' }))

  await screen.findByText('start: must be non-negative')
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
