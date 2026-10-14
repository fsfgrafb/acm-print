const iconProps = {
  width: 19, height: 19, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor',
  strokeWidth: 1.8, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const,
  'aria-hidden': true as const,
}

export function SubmitPrintIcon() {
  return <svg {...iconProps}>
    <path d="M7 8V3.5h10V8M6 17H4.5A1.5 1.5 0 0 1 3 15.5v-6A1.5 1.5 0 0 1 4.5 8h15A1.5 1.5 0 0 1 21 9.5v6a1.5 1.5 0 0 1-1.5 1.5H18" />
    <rect x="6.5" y="14" width="11" height="7" rx="1" />
    <path d="M9.5 17.5h5M17.5 11h.5" />
  </svg>
}

export function TaskQueueIcon() {
  return <svg {...iconProps}>
    <path d="M4 6h.01M4 12h.01M4 18h.01M9 6h11M9 12h11M9 18h11" />
  </svg>
}
