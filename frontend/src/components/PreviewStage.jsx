export default function PreviewStage({ scene, clipUrl }) {
  return (
    <div className="stage" role="region" aria-label="scene preview">
      <div className="stage__frame">
        {clipUrl ? (
          <video controls loop muted playsInline src={clipUrl} className="stage__media" />
        ) : scene?.thumbnail_url ? (
          <img
            src={scene.thumbnail_url}
            alt={`First frame — ${scene?.detected_summary || 'scene'}`}
            className="stage__media"
          />
        ) : (
          <div className="stage__placeholder">
            <span className="stage__placeholder-title">{scene?.detected_summary || 'No preview yet'}</span>
            {scene?.status === 'pending_review' && (
              <span className="stage__placeholder-note">Compiling…</span>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
