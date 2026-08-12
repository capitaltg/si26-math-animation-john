import { useContext, useState } from 'react'
import { DemoContext } from '../pages/DemoShell'

function ClipModal({ open, onClose, clipUrl, title }) {
  if (!open) return null
  return (
    <div className="modal" role="dialog" aria-modal="true" aria-label={`Watch ${title}`}>
      <div className="modal__scrim" onClick={onClose} />
      <div className="modal__body">
        <button type="button" className="modal__close btn btn--ghost" onClick={onClose} aria-label="Close">Close</button>
        <video controls autoPlay src={clipUrl} className="modal__video" />
        <a className="btn btn--primary" href={clipUrl} download>Download</a>
      </div>
    </div>
  )
}

export default function RenderToast() {
  const { toasts, dismissToast } = useContext(DemoContext)
  const [watching, setWatching] = useState(null) // {clipUrl, title} or null
  return (
    <>
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map(t => (
          <div key={t.id} className={`toast toast--${t.kind ?? 'ok'}`}>
            <div className="toast__body">
              <div className="toast__title">{t.title}</div>
              {t.message && <div className="toast__meta">{t.message}</div>}
            </div>
            <div className="toast__actions">
              {t.clipUrl && (
                <button type="button" className="btn btn--ghost" onClick={() => setWatching({clipUrl: t.clipUrl, title: t.title})}>
                  Watch &amp; download
                </button>
              )}
              <button type="button" className="btn btn--ghost" aria-label={`Dismiss ${t.title}`} onClick={() => dismissToast(t.id)}>×</button>
            </div>
          </div>
        ))}
      </div>
      <ClipModal open={!!watching} onClose={() => setWatching(null)} clipUrl={watching?.clipUrl} title={watching?.title} />
    </>
  )
}
