import { Link } from 'react-router-dom'

export default function Landing() {
  return (
    <main className="landing">
      <h1>Math Animation Generator</h1>
      <p>Turn example problems from a teacher's slide deck into short, mathematically-correct animation clips.</p>
      <Link to="/demo" className="btn btn--primary">Open demo</Link>
    </main>
  )
}
