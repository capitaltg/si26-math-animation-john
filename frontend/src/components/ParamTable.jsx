import { Fragment, useMemo, useState } from 'react'

function getAtPath(obj, path) {
  const parts = path.replace(/\[(\d+)\]/g, '.$1').split('.').filter(Boolean)
  return parts.reduce((acc, k) => acc?.[k], obj)
}

function setAtPath(obj, path, value) {
  const parts = path.replace(/\[(\d+)\]/g, '.$1').split('.').filter(Boolean)
  const clone = Array.isArray(obj) ? [...obj] : { ...obj }
  let cursor = clone
  for (let i = 0; i < parts.length - 1; i++) {
    const k = parts[i]
    const nextIsIndex = /^\d+$/.test(parts[i + 1])
    const src = cursor[k]
    cursor[k] = Array.isArray(src) ? [...src] : nextIsIndex ? [] : { ...(src ?? {}) }
    cursor = cursor[k]
  }
  cursor[parts[parts.length - 1]] = value
  return clone
}

function* paramRows(params, schema, prefix = '') {
  if (!schema) return
  if (schema.type === 'object' || schema.properties) {
    for (const key of Object.keys(schema.properties ?? {})) {
      const childSchema = schema.properties[key]
      const childValue = params?.[key]
      const path = prefix ? `${prefix}.${key}` : key
      yield* paramRows(childValue, childSchema, path)
    }
    return
  }
  if (schema.type === 'array' || schema.items) {
    const arr = Array.isArray(params) ? params : []
    for (let i = 0; i < arr.length; i++) {
      const path = `${prefix}[${i}]`
      yield* paramRows(arr[i], schema.items, path)
    }
    return
  }
  // leaf: integer, number, boolean, string
  yield { path: prefix, value: params, type: schema.type }
}

function errKey(loc) {
  // Convert ['a', '0', 'b'] -> 'a[0].b'
  return loc
    .map(String)
    .reduce((acc, part, i) => {
      if (i === 0) return part
      return /^\d+$/.test(part) ? `${acc}[${part}]` : `${acc}.${part}`
    }, '')
}

function coerce(type, raw) {
  if (type === 'integer') {
    const n = parseInt(raw, 10)
    return Number.isFinite(n) ? n : NaN
  }
  if (type === 'number') {
    const n = parseFloat(raw)
    return Number.isFinite(n) ? n : NaN
  }
  return raw
}

export default function ParamTable({ params, schema, errors, original, onChange, onRevert }) {
  const rows = useMemo(() => Array.from(paramRows(params, schema)), [params, schema])
  const errByPath = useMemo(() => {
    const map = new Map()
    for (const e of errors ?? []) map.set(errKey(e.loc), e.msg)
    return map
  }, [errors])
  const [rowErr, setRowErr] = useState({})

  function handleBlurNumeric(row) {
    return (e) => {
      const coerced = coerce(row.type, e.target.value)
      if (Number.isNaN(coerced)) {
        setRowErr((prev) => ({ ...prev, [row.path]: `${row.path} must be a valid ${row.type}` }))
        return
      }
      setRowErr((prev) => {
        if (!(row.path in prev)) return prev
        const next = { ...prev }
        delete next[row.path]
        return next
      })
      onChange(setAtPath(params, row.path, coerced))
    }
  }

  function handleCheckbox(row) {
    return (e) => {
      onChange(setAtPath(params, row.path, e.target.checked))
    }
  }

  function handleRevert(row) {
    return () => {
      const restored = getAtPath(original, row.path)
      onRevert(setAtPath(params, row.path, restored))
    }
  }

  function renderInput(row) {
    if (row.type === 'boolean') {
      return (
        <input
          type="checkbox"
          aria-label={row.path}
          defaultChecked={!!row.value}
          onChange={handleCheckbox(row)}
        />
      )
    }
    const inputType = row.type === 'integer' || row.type === 'number' ? 'number' : 'text'
    return (
      <input
        type={inputType}
        aria-label={row.path}
        defaultValue={row.value}
        onBlur={row.type === 'string' ? (e) => onChange(setAtPath(params, row.path, e.target.value)) : handleBlurNumeric(row)}
      />
    )
  }

  return (
    <table className="paramtable">
      <thead>
        <tr>
          <th>name</th>
          <th>value</th>
          <th>type</th>
          <th aria-label="revert"></th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => {
          const original_ = getAtPath(original, row.path)
          const unchanged = row.value === original_
          const message = rowErr[row.path] ?? errByPath.get(row.path)
          // Array-item rows get an explicit row-level label so assistive tech (and
          // getByRole('row', {name})) can disambiguate siblings by index; a
          // top-level scalar/object leaf is already uniquely identified by its
          // header cell, so we don't duplicate that text onto the <tr> (doing so
          // unconditionally would make the row's own label collide with its
          // input's label for single-field tables).
          const isArrayItem = row.path.includes('[')
          return (
            <Fragment key={row.path}>
              <tr aria-label={isArrayItem ? row.path : undefined}>
                <th scope="row">{row.path}</th>
                <td>{renderInput(row)}</td>
                <td className="paramtable__type">{row.type}</td>
                <td>
                  <button type="button" disabled={unchanged} onClick={handleRevert(row)}>
                    Revert
                  </button>
                </td>
              </tr>
              {message && (
                <tr className="paramtable__errrow">
                  <td colSpan={4}>
                    <span className="paramtable__err">{message}</span>
                  </td>
                </tr>
              )}
            </Fragment>
          )
        })}
      </tbody>
    </table>
  )
}
