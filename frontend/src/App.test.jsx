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

function jsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  }
}

function installFetchMock({ secondUpload = false, clipStatus = 'approved' } = {}) {
  let uploadCount = 0
  const fetchMock = vi.fn(async (url) => {
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
      return jsonResponse({ scenes: [pendingScene] })
    }
    if (url === '/storyboard/s1/approve') {
      return jsonResponse({ ...pendingScene, status: 'approved' })
    }
    if (url === '/render') {
      return jsonResponse({
        clips: [{
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
