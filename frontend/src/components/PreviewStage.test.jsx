import { render, screen } from '@testing-library/react'
import PreviewStage from './PreviewStage'

test('prefers clip when both clip and thumb present', () => {
  render(<PreviewStage scene={{thumbnail_url:'/t.png', detected_summary:'x'}} clipUrl="/c.mp4" />)
  const region = screen.getByRole('region', { name: /scene preview/i })
  expect(region.querySelector('video')).toBeInTheDocument()
  expect(region.querySelector('img')).not.toBeInTheDocument()
})

test('falls back to thumbnail when no clip', () => {
  render(<PreviewStage scene={{thumbnail_url:'/t.png', detected_summary:'triangle area'}} clipUrl={null} />)
  const img = screen.getByAltText(/first frame — triangle area/i)
  expect(img).toHaveAttribute('src', '/t.png')
})

test('shows placeholder text with Compiling when pending and no thumb/clip', () => {
  render(<PreviewStage scene={{status:'pending_review', detected_summary:'perimeter'}} clipUrl={null} />)
  expect(screen.getByText('perimeter')).toBeInTheDocument()
  expect(screen.getByText(/compiling/i)).toBeInTheDocument()
})

test('placeholder without Compiling when not pending', () => {
  render(<PreviewStage scene={{status:'rendered', detected_summary:'perimeter'}} clipUrl={null} />)
  expect(screen.queryByText(/compiling/i)).not.toBeInTheDocument()
})

test('says the clip is being rendered instead of showing a still that implies nothing is happening', () => {
  const { container } = render(
    <PreviewStage scene={{status:'approved', thumbnail_url:'/t.png', detected_summary:'perimeter'}} clipUrl={null} rendering />
  )
  expect(screen.getByText(/rendering the clip/i)).toBeInTheDocument()
  expect(container.querySelector('.spin')).not.toBeNull()
  expect(container.querySelector('img')).toBeNull()
})

test('a finished clip wins over the rendering placeholder', () => {
  const { container } = render(
    <PreviewStage scene={{status:'rendered', detected_summary:'perimeter'}} clipUrl="/c.mp4" rendering />
  )
  expect(container.querySelector('video')).toBeInTheDocument()
  expect(screen.queryByText(/rendering the clip/i)).not.toBeInTheDocument()
})
