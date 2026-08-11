import { GATES } from '../gates'

function iconFor(status) {
  if (status === 'passed') return '✓'
  if (status === 'failed') return '✕'
  return '·'
}

export default function GatesDisclosure({ gates }) {
  const total = gates.length
  const failed = gates.filter(g => g.status === 'failed').length
  const passed = gates.filter(g => g.status === 'passed').length
  const summary = failed ? `${failed} failed · ${passed} / ${total} checks`
                         : passed === total ? `all passed · ${total} / ${total} checks`
                         : `pending · ${passed} / ${total} checks`
  return (
    <details className="gates" open={failed > 0}>
      <summary>
        <span className={`gates__status gates__status--${failed?'warn':'ok'}`}>{summary}</span>
      </summary>
      <ul className="gates__list">
        {gates.map(g => (
          <li key={g.name} className="gate" data-status={g.status}>
            <span className="gate__icon" aria-hidden="true">{iconFor(g.status)}</span>
            <span className="gate__name">{g.name}</span>
            <span className="gate__category">{g.category}</span>
            <button type="button" className="gate__tip"
              aria-label={`What does ${g.name} mean`}
              title={GATES[g.name] ?? 'No description available.'}>what?</button>
          </li>
        ))}
      </ul>
    </details>
  )
}
