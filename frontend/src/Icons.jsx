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

export function IconDownload({ size }) {
  return (
    <Svg size={size}>
      <path d="M12 4v11" />
      <path d="M7 10l5 5 5-5" />
      <path d="M4 20h16" />
    </Svg>
  )
}

