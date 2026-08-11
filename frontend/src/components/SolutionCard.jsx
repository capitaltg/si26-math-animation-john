export default function SolutionCard({ answer }) {
  if (!answer) return null
  return (
    <aside className="solution" aria-label="numeric solution">
      <div className="solution__value">{answer.value}</div>
      <div className="solution__k">numeric solution · python-validated</div>
      <div className="solution__expr">{answer.expression}</div>
    </aside>
  )
}
