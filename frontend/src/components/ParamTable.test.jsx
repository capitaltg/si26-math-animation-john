import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ParamTable from './ParamTable'

test('flattens arrays into indexed rows', () => {
  render(
    <ParamTable
      params={{ values: [2, 5, 7] }}
      schema={{ properties: { values: { type: 'array', items: { type: 'integer' } } } }}
      original={{ values: [2, 5, 7] }}
      onChange={() => {}}
      onRevert={() => {}}
    />
  )
  expect(screen.getByRole('row', { name: 'values[0]' })).toBeInTheDocument()
  expect(screen.getByRole('row', { name: 'values[2]' })).toBeInTheDocument()
})

test('editing a value calls onChange with the mutated tree', async () => {
  const onChange = vi.fn()
  render(
    <ParamTable
      params={{ w: 4 }}
      schema={{ properties: { w: { type: 'integer' } } }}
      original={{ w: 4 }}
      onChange={onChange}
      onRevert={() => {}}
    />
  )
  await userEvent.clear(screen.getByLabelText('w'))
  await userEvent.type(screen.getByLabelText('w'), '5')
  await userEvent.tab()
  expect(onChange).toHaveBeenCalledWith({ w: 5 })
})

test('shows validation error under offending row', () => {
  render(
    <ParamTable
      params={{ w: 4 }}
      schema={{ properties: { w: { type: 'integer' } } }}
      original={{ w: 4 }}
      errors={[{ loc: ['w'], msg: 'w must be positive' }]}
      onChange={() => {}}
      onRevert={() => {}}
    />
  )
  expect(screen.getByText(/w must be positive/i)).toBeInTheDocument()
})

test('revert restores from original snapshot', async () => {
  const onRevert = vi.fn()
  render(
    <ParamTable
      params={{ w: 5 }}
      schema={{ properties: { w: { type: 'integer' } } }}
      original={{ w: 4 }}
      onChange={() => {}}
      onRevert={onRevert}
    />
  )
  await userEvent.click(screen.getByRole('button', { name: /revert/i }))
  expect(onRevert).toHaveBeenCalledWith({ w: 4 })
})

test('does not call onChange and shows local error when blur value is not numeric', async () => {
  const onChange = vi.fn()
  render(
    <ParamTable
      params={{ w: 4 }}
      schema={{ properties: { w: { type: 'integer' } } }}
      original={{ w: 4 }}
      onChange={onChange}
      onRevert={() => {}}
    />
  )
  await userEvent.clear(screen.getByLabelText('w'))
  await userEvent.type(screen.getByLabelText('w'), 'abc')
  await userEvent.tab()
  expect(onChange).not.toHaveBeenCalled()
  expect(screen.getByText(/w must be a valid integer/i)).toBeInTheDocument()
})

test('disables revert when value already matches original', () => {
  render(
    <ParamTable
      params={{ w: 4 }}
      schema={{ properties: { w: { type: 'integer' } } }}
      original={{ w: 4 }}
      onChange={() => {}}
      onRevert={() => {}}
    />
  )
  expect(screen.getByRole('button', { name: /revert/i })).toBeDisabled()
})
