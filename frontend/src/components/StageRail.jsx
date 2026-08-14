const STAGES = [
  { key:'upload', name:'Upload deck' },
  { key:'problems', name:'Pick problems' },
  { key:'visuals', name:'Pick visuals' },
  { key:'storyboard', name:'Check values' },
  { key:'clips', name:'Get clips' },
]
export default function StageRail({ current }) {
  const currentIndex = STAGES.findIndex((stage) => stage.key === current)
  return (
    <ol className="rail" aria-label="Pipeline stages">
      {STAGES.map((stage, index) => {
        const state = index < currentIndex ? 'done' : index === currentIndex ? 'active' : 'todo'
        return (
          <li key={stage.key} className="rail__step" data-state={state}
              aria-current={state === 'active' ? 'step' : undefined}>
            <span className="rail__index" aria-hidden="true">{index + 1}</span>
            <span className="rail__name">{stage.name}</span>
          </li>
        )
      })}
    </ol>
  )
}
