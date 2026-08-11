import { Link, useLocation } from 'react-router-dom'

export default function SiteHeader() {
  const { pathname } = useLocation()
  const onLanding = pathname === '/'
  return (
    <header className="site-header" role="banner">
      <div className="site-header__inner">
        <Link to="/" className="site-header__brand" aria-label="DoodleSum home">
          <img
            src="/brand/doodlesum-wordmark-light.png"
            alt="DoodleSum"
            className="site-header__wordmark"
          />
        </Link>
        <nav className="site-header__nav" aria-label="Primary">
          <a href="#how-it-works" hidden={!onLanding}>How it works</a>
          <a href="#why" hidden={!onLanding}>Why DoodleSum</a>
          <Link to="/demo" className="btn btn--primary site-header__cta">
            {onLanding ? 'Try the demo' : 'Open demo'}
          </Link>
        </nav>
      </div>
    </header>
  )
}
