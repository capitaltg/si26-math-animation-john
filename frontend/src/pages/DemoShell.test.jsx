import { render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import DemoShell from './DemoShell'

test('renders stage rail and upload input on entry', () => {
  render(
    <MemoryRouter initialEntries={['/demo']}>
      <Routes><Route path="/demo/*" element={<DemoShell />} /></Routes>
    </MemoryRouter>
  )
  expect(screen.getByRole('list', { name: /pipeline stages/i })).toBeInTheDocument()
  expect(screen.getByLabelText(/upload a pptx/i)).toBeInTheDocument()
})

// A DemoShell-level integration test for the Task 12 render effect (upload ->
// options -> storyboard -> approve -> POST /render -> toast) was attempted
// here and dropped: jsdom does not implement HTMLFormElement's "supported
// property names" behavior, so `event.target.file` in DemoShell's
// `handleUpload` (a pre-existing pattern, not introduced by this task)
// resolves to `undefined` in tests even though it works in real browsers,
// making the upload step — the only way to reach a state where
// `pendingRenders` becomes non-empty — unreachable via jsdom form
// submission. Per the task brief's explicit escape hatch, this is dropped
// in favor of `RenderToast.test.jsx`'s three component-level tests; see
// the Task 12 report/ledger for the gap.
