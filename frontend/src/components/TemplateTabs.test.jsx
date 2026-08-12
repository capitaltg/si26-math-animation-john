import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'
import TemplateTabs from './TemplateTabs'

test('renders three tabs with counts', () => {
  render(<TemplateTabs
    templates={[{template:'number_line',matched:true},{template:'array_grid',matched:false}]}
    rejected={[{template:'text_card',reason:'unsupported'}]}
    activeTemplate="number_line"
    onSwitch={() => {}}
  />)
  const picked = screen.getByRole('tab', { name: /picked/i })
  const alts = screen.getByRole('tab', { name: /alternatives/i })
  const rej = screen.getByRole('tab', { name: /rejected/i })
  expect(picked).toHaveAttribute('aria-selected', 'true')
  expect(alts).toHaveTextContent('1')
  expect(rej).toHaveTextContent('1')
})

test('clicking an alternative row calls onSwitch', async () => {
  const onSwitch = vi.fn()
  render(<TemplateTabs
    templates={[{template:'number_line',matched:true},{template:'array_grid',matched:false}]}
    rejected={[]}
    activeTemplate="number_line"
    onSwitch={onSwitch}
  />)
  await userEvent.click(screen.getByRole('tab', { name: /alternatives/i }))
  await userEvent.click(screen.getByRole('button', { name: /array/i }))
  expect(onSwitch).toHaveBeenCalledWith('array_grid')
})

test('rejected panel shows reason per row', async () => {
  render(<TemplateTabs
    templates={[{template:'number_line',matched:true}]}
    rejected={[{template:'text_card',reason:'unsupported'},{template:'array_grid',reason:'missing values'}]}
    activeTemplate="number_line"
    onSwitch={() => {}}
  />)
  await userEvent.click(screen.getByRole('tab', { name: /rejected/i }))
  expect(screen.getByText('unsupported')).toBeInTheDocument()
  expect(screen.getByText('missing values')).toBeInTheDocument()
})
