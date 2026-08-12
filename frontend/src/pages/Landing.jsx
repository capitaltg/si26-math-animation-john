import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'

const WHY_CARDS = [
  {
    title: 'Every value is verified',
    body:
      "The LLM only spots problems. Python does the math and validates every scene before it renders — so a '4 × 7' animation actually shows 28, not whatever the model felt like drawing.",
  },
  {
    title: 'Made for teacher slides',
    body:
      'Upload a PPTX you already made. DoodleSum finds solvable problems, offers visual options, and hands back short clips you drop back into the same deck.',
  },
  {
    title: 'Playful, not childish',
    body:
      'Number-line hops, array grids, fraction bars — the look kids remember, drawn with restraint you can put on the projector.',
  },
]

const HOW_STEPS = [
  {
    title: 'Upload a deck',
    body: 'Drop in a PPTX. We only read the text of slides that look like problems.',
  },
  {
    title: 'Pick problems',
    body: 'DoodleSum lists candidates. Tick the ones worth animating.',
  },
  {
    title: 'Pick visuals + check values',
    body: 'Choose the template per problem. Python computes the answer and shows it before render.',
  },
  {
    title: 'Get clips',
    body: 'Short verified MP4s, one per problem. Download and paste back into your deck.',
  },
]

export default function Landing() {
  const videoRef = useRef(null)
  const [sampleFailed, setSampleFailed] = useState(false)

  return (
    <div className="landing">
      <section className="landing__hero">
        <div className="landing__hero-copy">
          <h1>A verified animation for every math slide you teach.</h1>
          <p className="landing__lede">
            DoodleSum finds solvable problems in your PowerPoint deck and hands back
            short, Python-verified animation clips you can drop straight back in.
          </p>
          <div className="landing__hero-actions">
            <Link to="/demo" className="btn btn--primary btn--big">Try the demo</Link>
            <a href="#how-it-works" className="btn btn--ghost">See how it works</a>
          </div>
          <span className="landing__hero-note">
            No account. No upload storage. Nothing leaves the tab when you close it.
          </span>
        </div>
        <div className="landing__hero-art" aria-hidden="true">
          <img src="/brand/doodlesum-icon-light.png" alt="" />
        </div>
      </section>

      <section id="why" className="landing__why">
        <h2>Why DoodleSum</h2>
        <div className="landing__why-grid">
          {WHY_CARDS.map((card) => (
            <article key={card.title} className="landing__why-card">
              <h3>{card.title}</h3>
              <p>{card.body}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="landing__sample">
        <h2>See a clip</h2>
        {sampleFailed ? (
          <div className="landing__sample-placeholder">Sample clip coming soon.</div>
        ) : (
          <video
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
          />
        )}
        <p className="landing__sample-caption">
          One clip, one problem, ~10 seconds. Every number on screen was computed in
          Python before Manim drew it.
        </p>
      </section>

      <section id="how-it-works" className="landing__how">
        <h2>How it works</h2>
        <ol className="landing__how-steps">
          {HOW_STEPS.map((step) => (
            <li key={step.title} className="landing__how-step">
              <h3>{step.title}</h3>
              <p>{step.body}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="landing__audience">
        <article className="landing__audience-card">
          <h3>Who it's for</h3>
          <ul>
            <li>K–8 math teachers building lesson decks in PowerPoint.</li>
            <li>Coaches and tutors making one-off explainer clips.</li>
            <li>Anyone who wants a math visual they can trust on the projector.</li>
          </ul>
        </article>
        <article className="landing__audience-card">
          <h3>Honest limits</h3>
          <ul>
            <li>Math only — arithmetic, geometry, and fractions to start.</li>
            <li>2D visualizations. No 3D and no free-form graphing.</li>
            <li>PPTX in — no OCR of image-only slides.</li>
            <li>No accounts, no persistence — everything ends when you close the tab.</li>
          </ul>
        </article>
      </section>

      <section className="landing__cta">
        <h2>Ready to try it?</h2>
        <p>Bring a deck. Get clips. Same lesson plan, verified visuals.</p>
        <div className="landing__cta-actions">
          <Link to="/demo" className="btn btn--primary btn--big">Open the demo</Link>
          <a href="#how-it-works" className="btn btn--ghost">Read the walkthrough</a>
        </div>
      </section>
    </div>
  )
}
