import { useContext } from 'react'
import { DemoContext } from './DemoShell'

export default function Queue() {
  const { candidates, handleUpload } = useContext(DemoContext)
  if (!candidates) {
    return (
      <form onSubmit={handleUpload}>
        <label>
          <span>Upload a PPTX</span>
          <input type="file" name="file" aria-label="Upload a PPTX" />
        </label>
      </form>
    )
  }
  return null
}
