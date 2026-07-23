// Resolve a { "$ref": "#/$defs/Name" } node against the root schema's $defs.
function resolveRef(node, root) {
  if (node && node.$ref) {
    const name = node.$ref.replace('#/$defs/', '')
    return root.$defs?.[name] ?? {}
  }
  return node
}

function blankValue(schema, root) {
  const resolved = resolveRef(schema, root)
  if (resolved.enum) return resolved.enum[0]
  if (resolved.type === 'integer' || resolved.type === 'number') return 0
  if (resolved.type === 'array') return []
  if (resolved.type === 'object' || resolved.properties) {
    return Object.fromEntries(
      Object.entries(resolved.properties || {}).map(([name, property]) => [
        name,
        blankValue(property, root),
      ]),
    )
  }
  return ''
}

function Field({ name, schema, root, value, onChange, disabled }) {
  const resolved = resolveRef(schema, root)
  const label = resolved.title || name

  // Enum (Literal) -> dropdown
  if (resolved.enum) {
    return (
      <label style={{ display: 'block', margin: '0.3rem 0' }}>
        {label}:{' '}
        <select value={value ?? ''} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
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
          disabled={disabled}
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
    const itemIsObject = itemSchema.type === 'object' || !!itemSchema.properties

    return (
      <fieldset style={{ margin: '0.4rem 0' }} disabled={disabled}>
        <legend>{label}</legend>
        {rows.map((row, i) => (
          <div key={i} style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
            {itemIsObject ? (
              <SchemaForm
                schema={itemSchema}
                root={root}
                value={row}
                disabled={disabled}
                onChange={(nextRow) => {
                  const next = rows.slice()
                  next[i] = nextRow
                  onChange(next)
                }}
              />
            ) : (
              <Field
                name={`${label} ${i + 1}`}
                schema={itemSchema}
                root={root}
                value={row}
                disabled={disabled}
                onChange={(nextValue) => {
                  const next = rows.slice()
                  next[i] = nextValue
                  onChange(next)
                }}
              />
            )}
            {rows.length > minItems && (
              <button
                type="button"
                disabled={disabled}
                onClick={() => onChange(rows.filter((_, j) => j !== i))}
              >
                remove
              </button>
            )}
          </div>
        ))}
        {rows.length < maxItems && (
          <button
            type="button"
            disabled={disabled}
            onClick={() => onChange([...rows, blankValue(itemSchema, root)])}
          >
            add item
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
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  )
}

export default function SchemaForm({ schema, root, value, onChange, disabled }) {
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
          disabled={disabled}
          onChange={(fieldValue) => onChange({ ...value, [name]: fieldValue })}
        />
      ))}
    </div>
  )
}
