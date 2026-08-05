import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import TemplateWorkshop from './TemplateWorkshop'

function jsonResponse(body, status = 200) {
  return { ok: status < 400, status, json: async () => body }
}

const draft = {
  id: 'draft-1',
  revision: 1,
  learning_objective: 'Find the value with no partner.',
  beats: [
    { id: 'reveal', kind: 'reveal', intent: 'show the values together' },
    { id: 'focus', kind: 'focus', intent: 'focus on the unpaired value' },
    { id: 'conclude', kind: 'conclude', intent: 'state the leftover' },
  ],
  total_duration_seconds: 12.5,
  preview_url: '/meta/my/drafts/draft-1/preview',
  suggested_template_name: 'compare_set',
  attempts: [],
  attempts_remaining: 4,
}

function build(overrides = {}) {
  return {
    candidate_id: 'c1',
    fingerprint_key: 'k1',
    stage: 'queued',
    attempt: 0,
    max_attempts: 5,
    elapsed_seconds: 3,
    draft_id: null,
    error: null,
    ...overrides,
  }
}

function installFetchMock({
  enabled = true,
  builds = [],
  draftPayload = draft,
  approveStatus = 200,
} = {}) {
  const fetchMock = vi.fn(async (url, init = {}) => {
    if (url === '/meta/my/capabilities') return jsonResponse({ enabled })
    if (url === '/meta/my/builds' && init.method === 'POST') {
      return jsonResponse({ candidate_id: JSON.parse(init.body).candidate_id }, 202)
    }
    if (url === '/meta/my/builds') return jsonResponse(builds)
    if (url === `/meta/my/drafts/${draftPayload.id}`) return jsonResponse(draftPayload)
    if (url?.endsWith('/approve')) {
      if (approveStatus !== 200) {
        return jsonResponse({ detail: 'Draft has too few verified real fixtures to publish' }, approveStatus)
      }
      return jsonResponse({ template_name: 'leftover_pair', template_version_id: 'tv-1' })
    }
    if (url?.endsWith('/reject')) return jsonResponse({ requeued: true })
    if (url?.startsWith('/meta/my/builds/') && init.method === 'DELETE') {
      return { ok: true, status: 204, json: async () => null }
    }
    throw new Error(`Unexpected request: ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const candidates = [{
  candidate_id: 'c1',
  one_line_summary: 'Detected: odd one out',
  source_excerpt: 'Seven socks are laid out; which one has no pair?',
}]

function renderWorkshop(props = {}) {
  return render(
    <TemplateWorkshop candidates={candidates} unsupportedCandidateIds={['c1']} {...props} />,
  )
}

beforeEach(() => {
  vi.useRealTimers()
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

// ------------------------------------------------------------------ entry

it('offers to build a visual when no template fits the problem', async () => {
  installFetchMock()

  renderWorkshop()

  expect(await screen.findByRole('button', { name: /Build one for this problem/ })).toBeTruthy()
})

it('stays out of the way when the feature is unavailable', async () => {
  installFetchMock({ enabled: false })

  renderWorkshop()

  await waitFor(() => expect(screen.queryByRole('button', { name: /Build one/ })).toBeNull())
})

it('offers nothing when every problem already has a template', async () => {
  installFetchMock()

  renderWorkshop({ unsupportedCandidateIds: [] })

  await waitFor(() => expect(screen.queryByRole('button', { name: /Build one/ })).toBeNull())
})

it('asks the server to build a visual for the chosen problem', async () => {
  const fetchMock = installFetchMock()

  renderWorkshop()
  fireEvent.click(await screen.findByRole('button', { name: /Build one for this problem/ }))

  await waitFor(() => {
    const posted = fetchMock.mock.calls.find(
      ([url, init]) => url === '/meta/my/builds' && init?.method === 'POST',
    )
    expect(JSON.parse(posted[1].body)).toEqual({ candidate_id: 'c1' })
  })
})

// --------------------------------------------------------------- building

it('reports the stages of a build that has been queued', async () => {
  installFetchMock({ builds: [build({ stage: 'queued' })] })

  renderWorkshop()

  await screen.findByRole('heading', { name: 'Teaching a new visual' })
  expect(screen.getByText('2 of 4 stages complete')).toBeTruthy()
  expect(screen.getByText('Problem filed')).toBeTruthy()
  expect(screen.getByText('Ready for your approval')).toBeTruthy()
})

it('counts writing the template as a stage in progress', async () => {
  installFetchMock({ builds: [build({ stage: 'building', elapsed_seconds: 161 })] })

  renderWorkshop()

  await screen.findByText('2 of 4 stages complete')
  const stage = screen.getByText('Writing the template').closest('li')
  expect(stage.dataset.state).toBe('active')
})

it('shows how long a build has been going without pretending to know the rest', async () => {
  installFetchMock({ builds: [build({ stage: 'building', elapsed_seconds: 161 })] })

  renderWorkshop()

  expect(await screen.findByText('2:41')).toBeTruthy()
  expect(screen.queryByRole('progressbar')).toBeNull()
})

it('says when nothing has picked the work up yet', async () => {
  installFetchMock({ builds: [build({ stage: 'queued', elapsed_seconds: 120 })] })

  renderWorkshop()

  expect(await screen.findByText(/has not started on this yet/)).toBeTruthy()
})

it('does not cry stalled while the queue is still fresh', async () => {
  installFetchMock({ builds: [build({ stage: 'queued', elapsed_seconds: 5 })] })

  renderWorkshop()

  await screen.findByRole('heading', { name: 'Teaching a new visual' })
  expect(screen.queryByText(/has not started on this yet/)).toBeNull()
})

// ------------------------------------------------------------------ ready

it('shows what the template teaches once it is built', async () => {
  installFetchMock({ builds: [build({ stage: 'ready', draft_id: 'draft-1' })] })

  renderWorkshop()

  expect(await screen.findByText('Find the value with no partner.')).toBeTruthy()
  expect(screen.getByText(/show the values together/)).toBeTruthy()
  expect(screen.getByText(/12.5 seconds/)).toBeTruthy()
})

it('shows the preview of the built template', async () => {
  installFetchMock({ builds: [build({ stage: 'ready', draft_id: 'draft-1' })] })

  renderWorkshop()

  const preview = await screen.findByRole('img', { name: /first frame/i })
  expect(preview.getAttribute('src')).toBe('/meta/my/drafts/draft-1/preview')
})

it('will not let a template be used before the maths is confirmed', async () => {
  installFetchMock({ builds: [build({ stage: 'ready', draft_id: 'draft-1' })] })

  renderWorkshop()

  const approve = await screen.findByRole('button', { name: /Looks right/ })
  expect(approve.disabled).toBe(true)

  fireEvent.click(screen.getByLabelText(/teaches this correctly/))
  await waitFor(() => expect(approve.disabled).toBe(false))
})

it('will not let a template be used without a name', async () => {
  installFetchMock({ builds: [build({ stage: 'ready', draft_id: 'draft-1' })] })

  renderWorkshop()

  await screen.findByRole('button', { name: /Looks right/ })
  fireEvent.click(screen.getByLabelText(/teaches this correctly/))
  fireEvent.change(screen.getByLabelText('Name this visual'), { target: { value: '   ' } })

  await waitFor(() =>
    expect(screen.getByRole('button', { name: /Looks right/ }).disabled).toBe(true))
})

it('suggests a name drawn from the problem shape', async () => {
  installFetchMock({ builds: [build({ stage: 'ready', draft_id: 'draft-1' })] })

  renderWorkshop()

  const name = await screen.findByLabelText('Name this visual')
  expect(name.value).toBe('compare_set')
})

it('publishes the template for this teacher when they approve it', async () => {
  const fetchMock = installFetchMock({ builds: [build({ stage: 'ready', draft_id: 'draft-1' })] })

  renderWorkshop()
  fireEvent.click(await screen.findByLabelText(/teaches this correctly/))
  fireEvent.click(screen.getByRole('button', { name: /Looks right/ }))

  await waitFor(() => {
    const posted = fetchMock.mock.calls.find(([url]) => url?.endsWith('/approve'))
    expect(JSON.parse(posted[1].body)).toEqual({
      template_name: 'compare_set',
      math_semantics_confirmed: true,
    })
  })
})

it('says the approved template is only available in this session', async () => {
  installFetchMock({ builds: [build({ stage: 'ready', draft_id: 'draft-1' })] })

  renderWorkshop()
  fireEvent.click(await screen.findByLabelText(/teaches this correctly/))
  fireEvent.click(screen.getByRole('button', { name: /Looks right/ }))

  expect(await screen.findByText(/available in this session/)).toBeTruthy()
})

it('tells the parent which candidate to refresh options for after approval', async () => {
  installFetchMock({ builds: [build({ stage: 'ready', draft_id: 'draft-1' })] })
  const onApproved = vi.fn()

  renderWorkshop({ onApproved })
  fireEvent.click(await screen.findByLabelText(/teaches this correctly/))
  fireEvent.click(screen.getByRole('button', { name: /Looks right/ }))

  await waitFor(() => expect(onApproved).toHaveBeenCalledWith('leftover_pair', 'c1'))
})

it('reports why an approval was refused', async () => {
  installFetchMock({
    builds: [build({ stage: 'ready', draft_id: 'draft-1' })],
    approveStatus: 422,
  })

  renderWorkshop()
  fireEvent.click(await screen.findByLabelText(/teaches this correctly/))
  fireEvent.click(screen.getByRole('button', { name: /Looks right/ }))

  expect(await screen.findByText(/too few verified real fixtures/)).toBeTruthy()
})

// ----------------------------------------------------------------- reject

it('asks what is wrong before trying again', async () => {
  installFetchMock({ builds: [build({ stage: 'ready', draft_id: 'draft-1' })] })

  renderWorkshop()
  fireEvent.click(await screen.findByRole('button', { name: /Not right/ }))

  const send = screen.getByRole('button', { name: /Try again/ })
  expect(send.disabled).toBe(true)

  fireEvent.change(screen.getByLabelText(/What is wrong/), {
    target: { value: 'the rows are not labelled' },
  })
  await waitFor(() => expect(send.disabled).toBe(false))
})

it('says what another attempt costs and how many are left', async () => {
  installFetchMock({ builds: [build({ stage: 'ready', draft_id: 'draft-1' })] })

  renderWorkshop()
  fireEvent.click(await screen.findByRole('button', { name: /Not right/ }))

  expect(screen.getByText(/takes a few minutes/)).toBeTruthy()
  expect(screen.getByText(/4 attempts left/)).toBeTruthy()
})

it('sends the reason so the next attempt can act on it', async () => {
  const fetchMock = installFetchMock({ builds: [build({ stage: 'ready', draft_id: 'draft-1' })] })

  renderWorkshop()
  fireEvent.click(await screen.findByRole('button', { name: /Not right/ }))
  fireEvent.change(screen.getByLabelText(/What is wrong/), {
    target: { value: 'the rows are not labelled' },
  })
  fireEvent.click(screen.getByRole('button', { name: /Try again/ }))

  await waitFor(() => {
    const posted = fetchMock.mock.calls.find(([url]) => url?.endsWith('/reject'))
    expect(JSON.parse(posted[1].body)).toEqual({ feedback: 'the rows are not labelled' })
  })
})

// --------------------------------------------------------------- attempts

it('shows each earlier attempt with the reason it was turned down', async () => {
  installFetchMock({
    builds: [build({ stage: 'ready', draft_id: 'draft-1' })],
    draftPayload: {
      ...draft,
      revision: 3,
      attempts: [
        { revision: 1, feedback: 'the rows are not labelled', preview_url: '/p/1' },
        { revision: 2, feedback: 'the total appears too early', preview_url: '/p/2' },
      ],
    },
  })

  renderWorkshop()

  const attempts = await screen.findByRole('list', { name: 'Earlier attempts' })
  const items = within(attempts).getAllByRole('listitem')
  expect(items).toHaveLength(2)
  expect(items[0].textContent).toContain('the rows are not labelled')
  expect(items[1].textContent).toContain('the total appears too early')
})

it('shows no history on a first attempt', async () => {
  installFetchMock({ builds: [build({ stage: 'ready', draft_id: 'draft-1' })] })

  renderWorkshop()

  await screen.findByText('Find the value with no partner.')
  expect(screen.queryByRole('list', { name: 'Earlier attempts' })).toBeNull()
})

// --------------------------------------------------------------- failures

it('says plainly when automatic generation gave up', async () => {
  installFetchMock({
    builds: [build({
      stage: 'needs_manual',
      error: 'Automatic generation could not produce a visual for this problem. The labelled text card still works.',
    })],
  })

  renderWorkshop()

  expect(await screen.findByText(/labelled text card still works/)).toBeTruthy()
})

it('does not dress the surviving text card up as a failure', async () => {
  // The labelled fallback is a success state in this product. Styling it danger
  // would tell a teacher something broke when nothing did.
  installFetchMock({
    builds: [build({ stage: 'needs_manual', error: 'Automatic generation gave up.' })],
  })

  renderWorkshop()

  const notice = (await screen.findByText('Automatic generation gave up.')).closest('.notice')
  expect(notice.className).toContain('notice--fallback')
  expect(screen.queryByRole('alert')).toBeNull()
})

it('does not treat an existing template as a failure either', async () => {
  installFetchMock({
    builds: [build({
      stage: 'already_available',
      error: 'There is already a visual for this kind of problem.',
    })],
  })

  renderWorkshop()

  const notice = (await screen.findByText(/already a visual/)).closest('.notice')
  expect(notice.className).toContain('notice--fallback')
  expect(screen.queryByRole('alert')).toBeNull()
})

it('reports a build that could not start', async () => {
  installFetchMock({
    builds: [build({ stage: 'failed', error: 'We could not work out what kind of problem this is.' })],
  })

  renderWorkshop()

  expect(await screen.findByText(/could not work out what kind of problem/)).toBeTruthy()
})

// ---------------------------------------------------------------- polling

it('stops asking for progress once a build is finished', async () => {
  vi.useFakeTimers()
  const fetchMock = installFetchMock({ builds: [build({ stage: 'ready', draft_id: 'draft-1' })] })

  renderWorkshop()
  await vi.advanceTimersByTimeAsync(1)
  const afterFirstPoll = fetchMock.mock.calls.filter(([url]) => url === '/meta/my/builds').length

  await vi.advanceTimersByTimeAsync(30000)

  expect(fetchMock.mock.calls.filter(([url]) => url === '/meta/my/builds').length).toBe(
    afterFirstPoll,
  )
  vi.useRealTimers()
})

it('keeps asking for progress while a build is still running', async () => {
  vi.useFakeTimers()
  const fetchMock = installFetchMock({ builds: [build({ stage: 'building' })] })

  renderWorkshop()
  await vi.advanceTimersByTimeAsync(1)
  const afterFirstPoll = fetchMock.mock.calls.filter(([url]) => url === '/meta/my/builds').length

  await vi.advanceTimersByTimeAsync(10000)

  expect(
    fetchMock.mock.calls.filter(([url]) => url === '/meta/my/builds').length,
  ).toBeGreaterThan(afterFirstPoll)
  vi.useRealTimers()
})

// -------------------------------------------------- a way back from a dead end

it('offers a way back when a build could not start', async () => {
  installFetchMock({
    builds: [build({ stage: 'failed', error: 'We could not work out what kind of problem this is.' })],
  })

  renderWorkshop()

  expect(await screen.findByRole('button', { name: /Try this problem again/ })).toBeTruthy()
})

it('offers a way back when automatic generation gave up', async () => {
  installFetchMock({
    builds: [build({ stage: 'needs_manual', error: 'Automatic generation gave up.' })],
  })

  renderWorkshop()

  expect(await screen.findByRole('button', { name: /Try this problem again/ })).toBeTruthy()
})

it('clears the finished attempt so the problem can be offered again', async () => {
  const fetchMock = installFetchMock({
    builds: [build({ stage: 'failed', error: 'We could not work out what kind of problem this is.' })],
  })

  renderWorkshop()
  fireEvent.click(await screen.findByRole('button', { name: /Try this problem again/ }))

  await waitFor(() => {
    const cleared = fetchMock.mock.calls.find(
      ([url, init]) => url === '/meta/my/builds/c1' && init?.method === 'DELETE',
    )
    expect(cleared).not.toBeUndefined()
  })
})

it('does not offer to clear a build that is still going', async () => {
  installFetchMock({ builds: [build({ stage: 'building' })] })

  renderWorkshop()

  await screen.findByText('2 of 4 stages complete')
  expect(screen.queryByRole('button', { name: /Try this problem again/ })).toBeNull()
})

it('does not offer to clear a template waiting to be judged', async () => {
  installFetchMock({ builds: [build({ stage: 'ready', draft_id: 'draft-1' })] })

  renderWorkshop()

  await screen.findByText('Find the value with no partner.')
  expect(screen.queryByRole('button', { name: /Try this problem again/ })).toBeNull()
})
