import { IconWorking } from '../Icons'

export default function PreviewStage({ scene, clipUrl, rendering = false }) {
  return (
    <div className="stage" role="region" aria-label="scene preview">
      <div className="stage__frame">
        {clipUrl ? (
          <video controls loop muted playsInline src={clipUrl} className="stage__media" />
        ) : rendering ? (
          // No clip yet and one is being made: say so here, where the teacher is
          // looking, instead of leaving the first-frame still to imply nothing
          // is happening.
          <div className="stage__placeholder">
            <span className="stage__placeholder-title">{scene?.detected_summary || 'Scene'}</span>
            <span className="stage__placeholder-note stage__placeholder-note--working">
              <IconWorking size={16} />
              Rendering the clip…
            </span>
          </div>
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
