// Authored icons for the Bright Board world: one 2px stroke weight, square
// caps to echo the rod-block geometry, currentColor throughout. No emoji.

function Svg({ size = 20, children, className }) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="square"
      strokeLinejoin="miter"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  )
}

export function IconCheck({ size }) {
  return (
    <Svg size={size}>
      <path d="M4 13l5 5L20 6" />
    </Svg>
  )
}

export function IconCross({ size }) {
  return (
    <Svg size={size}>
      <path d="M6 6l12 12M18 6L6 18" />
    </Svg>
  )
}

export function IconRedo({ size }) {
  return (
    <Svg size={size}>
      <path d="M20 5v6h-6" />
      <path d="M20 11a8 8 0 10-2.6 5.9" />
    </Svg>
  )
}

export function IconDownload({ size }) {
  return (
    <Svg size={size}>
      <path d="M12 4v11" />
      <path d="M7 10l5 5 5-5" />
      <path d="M4 20h16" />
    </Svg>
  )
}

export function IconPending({ size }) {
  return (
    <Svg size={size}>
      <rect x="5" y="5" width="14" height="14" rx="2" />
    </Svg>
  )
}

export function IconWorking({ size }) {
  return (
    <Svg size={size} className="spin">
      <path d="M12 3a9 9 0 019 9" />
      <path d="M12 21a9 9 0 01-9-9" opacity="0.35" />
    </Svg>
  )
}

// The fallback is a record, not an error: a filled card with a written line.
export function IconCard({ size }) {
  return (
    <Svg size={size}>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="M7 11h10M7 15h6" />
    </Svg>
  )
}

export function IconAlert({ size }) {
  return (
    <Svg size={size}>
      <path d="M12 4l9 16H3l9-16z" />
      <path d="M12 10v4" />
      <path d="M12 17h.01" strokeLinecap="round" />
    </Svg>
  )
}

// Checked arithmetic: a tally column with a rule under it.
export function IconChecked({ size }) {
  return (
    <Svg size={size}>
      <path d="M5 4v9M9 4v9M13 4v9" />
      <path d="M3 16h18" />
      <path d="M14 20l3 2 4-6" />
    </Svg>
  )
}

// A new template being learned: a rod block with growth marks, not a sparkle.
export function IconSeedling({ size }) {
  return (
    <Svg size={size}>
      <rect x="8" y="13" width="8" height="7" rx="1" />
      <path d="M12 13V8" />
      <path d="M12 8c0-2 1.6-3.5 3.5-3.5C15.5 6.4 14 8 12 8z" />
      <path d="M12 9c0-1.6-1.3-3-3-3 0 1.6 1.3 3 3 3z" />
    </Svg>
  )
}
