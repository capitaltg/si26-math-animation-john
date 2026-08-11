const STAGES = [
  { key:'upload', name:'Upload deck' },
  { key:'problems', name:'Pick problems' },
  { key:'visuals', name:'Pick visuals' },
  { key:'storyboard', name:'Check values' },
  { key:'clips', name:'Get clips' },
]
export default function StageRail({ current }) {
  const idx = STAGES.findIndex(s => s.key === current)
  return (
    <ol className="rail" aria-label="Pipeline stages">
      {STAGES.map((s, i) => {
        const state = i < idx ? 'done' : i === idx ? 'active' : 'todo'
        return (
          <li key={s.key} className="rail__step" data-state={state}
              aria-current={state === 'active' ? 'step' : undefined}>
            <span className="rail__index" aria-hidden="true">{i + 1}</span>
            <span className="rail__name">{s.name}</span>
          </li>
        )
      })}
    </ol>
  )
}
