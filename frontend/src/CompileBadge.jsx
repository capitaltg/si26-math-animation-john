import { useState } from 'react'

// Surfaces the deterministic params → scene-program compile step. Same params
// in → same hash out; audiences can rerun a scene and confirm the hash matches.
export default function CompileBadge({ scene }) {
  const [expanded, setExpanded] = useState(false)
  const hash = scene.scene_program_hash
  if (!hash) return null
  const short = `sha256:${hash.slice(0, 8)}…`
  const compileMs = scene.compile_ms
  const programSize = scene.program_size
  return (
    <div className="compile-badge" data-testid="compile-badge">
      <div className="compile-badge__row">
        <code className="compile-badge__hash" title={`sha256:${hash}`}>{short}</code>
        {compileMs != null && (
          <span className="compile-badge__meta">{compileMs.toFixed(2)} ms</span>
        )}
        {programSize != null && (
          <span className="compile-badge__meta">{programSize} B</span>
        )}
        <button
          type="button"
          className="compile-badge__toggle"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
        >
          {expanded ? 'Hide compiled program' : 'View compiled program'}
        </button>
      </div>
      {expanded && (
        <pre className="compile-badge__program" aria-label="Compiled scene program">
          {JSON.stringify(scene.scene_program, null, 2)}
        </pre>
      )}
    </div>
  )
}
