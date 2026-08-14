export default function SiteFooter() {
  return (
    <footer className="site-footer" role="contentinfo">
      <div className="site-footer__inner">
        <span className="site-footer__mark">
          <img src="/brand/doodlesum-wordmark-mono-graphite.png" alt="DoodleSum" />
        </span>
        <span className="site-footer__lockup">
          Math problems in — verified animations out. Built for teachers.
        </span>
        <span className="site-footer__credit">
          Created by{' '}
          <a
            href="https://www.linkedin.com/in/johnn05/"
            target="_blank"
            rel="noopener noreferrer"
          >
            John Ng
          </a>
        </span>
      </div>
    </footer>
  )
}
