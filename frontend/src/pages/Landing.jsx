import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'

export default function Landing() {
  const videoRef = useRef(null)
  const [sampleFailed, setSampleFailed] = useState(false)

  return (
    <main className="landing">
      {/* Hero */}
      <section className="landing__hero">
        <h1>Math Animation Generator</h1>
        <p>Turn example problems from a teacher's slide deck into short, mathematically-correct animation clips.</p>
        <Link to="/demo" className="btn btn--primary">Open demo</Link>
      </section>

      {/* The claim */}
      <section className="landing__claim">
        <h2>The claim</h2>
        <p>The LLM finds problems and classifies them. Python computes the values and validates every scene. That split is the one thing a neighboring product cannot truthfully copy — everything the animation shows is Python-verified before it renders.</p>
      </section>

      {/* Live sample */}
      <section className="landing__sample">
        <h2>Sample</h2>
        {sampleFailed
          ? <div className="landing__sample-placeholder">Sample clip coming soon.</div>
          : <video
              ref={videoRef}
              src="/media/perimeter.mp4"
              controls
              loop
              muted
              playsInline
              preload="metadata"
              onError={() => setSampleFailed(true)}
              onMouseEnter={() => videoRef.current?.play().catch(() => {})}
              onMouseLeave={() => videoRef.current?.pause()}
              className="landing__sample-video"
            />}
      </section>

      {/* How it works */}
      <section className="landing__how">
        <h2>How it works</h2>
        <ol>
          <li>Candidate — the LLM finds problem statements in the deck's text.</li>
          <li>Visual — a template with a known compiler is picked per problem.</li>
          <li>Storyboard — parameters are extracted and validated in Python.</li>
          <li>Render — Manim + ffmpeg produce a short MP4 per scene.</li>
          <li>Clip — you download each clip and drop it into your own deck.</li>
        </ol>
      </section>

      {/* Honest limits */}
      <section className="landing__limits">
        <h2>Honest limits</h2>
        <ul>
          <li>Math only (K–8 arithmetic, geometry, fractions).</li>
          <li>2D visualizations.</li>
          <li>PPTX in — nothing else, and no OCR of image-only slides.</li>
          <li>No accounts, no persistence, no async — everything ends when you close the tab.</li>
        </ul>
      </section>

      {/* CTA footer */}
      <section className="landing__cta">
        <h3>Ready to try it?</h3>
        <Link to="/demo" className="btn btn--primary">Open demo</Link>
      </section>
    </main>
  )
}
