// Resolve a { "$ref": "#/$defs/Name" } node against the root schema's $defs.
function resolveRef(node, root) {
  if (node && node.$ref) {
    const name = node.$ref.replace('#/$defs/', '')
    return root.$defs?.[name] ?? {}
  }
  return node
}

function Field({ name, schema, root, value, onChange }) {
  const resolved = resolveRef(schema, root)
  const label = resolved.title || name

  // Enum (Literal) -> dropdown
  if (resolved.enum) {
    return (
      <label style={{ display: 'block', margin: '0.3rem 0' }}>
        {label}:{' '}
        <select value={value ?? ''} onChange={(e) => onChange(e.target.value)}>
          {resolved.enum.map((opt) => (
            <option key={opt} value={opt}>{opt}</option>
          ))}
        </select>
      </label>
    )
  }

  // Number
  if (resolved.type === 'integer' || resolved.type === 'number') {
    return (
      <label style={{ display: 'block', margin: '0.3rem 0' }}>
        {label}:{' '}
        <input
          type="number"
          value={value ?? ''}
          onChange={(e) => {
            const raw = e.target.value
            onChange(raw === '' ? '' : Number(raw))
          }}
        />
      </label>
    )
  }

  // Array of objects -> repeatable rows
  if (resolved.type === 'array') {
    const itemSchema = resolveRef(resolved.items, root)
    const rows = Array.isArray(value) ? value : []
    const minItems = resolved.minItems ?? 0
    const maxItems = resolved.maxItems ?? Infinity

    const blankRow = () =>
      Object.fromEntries(
        Object.entries(itemSchema.properties || {}).map(([k, s]) => {
          const rs = resolveRef(s, root)
          if (rs.enum) return [k, rs.enum[0]]
          if (rs.type === 'integer' || rs.type === 'number') return [k, 0]
          return [k, '']
        }),
      )

    return (
      <fieldset style={{ margin: '0.4rem 0' }}>
        <legend>{label}</legend>
        {rows.map((row, i) => (
          <div key={i} style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
            <SchemaForm
              schema={itemSchema}
              root={root}
              value={row}
              onChange={(nextRow) => {
                const next = rows.slice()
                next[i] = nextRow
                onChange(next)
              }}
            />
            {rows.length > minItems && (
              <button
                type="button"
                onClick={() => onChange(rows.filter((_, j) => j !== i))}
              >
                remove
              </button>
            )}
          </div>
        ))}
        {rows.length < maxItems && (
          <button type="button" onClick={() => onChange([...rows, blankRow()])}>
            add step
          </button>
        )}
      </fieldset>
    )
  }

  // String fallback
  return (
    <label style={{ display: 'block', margin: '0.3rem 0' }}>
      {label}:{' '}
      <input
        type="text"
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  )
}

export default function SchemaForm({ schema, root, value, onChange }) {
  const rootSchema = root || schema
  const properties = schema.properties || {}
  return (
    <div>
      {Object.entries(properties).map(([name, propSchema]) => (
        <Field
          key={name}
          name={name}
          schema={propSchema}
          root={rootSchema}
          value={value?.[name]}
          onChange={(fieldValue) => onChange({ ...value, [name]: fieldValue })}
        />
      ))}
    </div>
  )
}
