export function LogoMark({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" className="shrink-0">
      <rect width="32" height="32" rx="9" fill="var(--color-brand)" />
      <circle cx="14" cy="14" r="6.5" fill="none" stroke="var(--color-brand-ink)" strokeWidth="2.4" />
      <path d="M19.2 19.2l6 6" stroke="var(--color-lamp)" strokeWidth="3.2" strokeLinecap="round" />
      <path d="M11.4 14h5.2M14 11.4v5.2" stroke="var(--color-brand-ink)" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  )
}

export function Logo({ tagline = false }: { tagline?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <LogoMark />
      <div className="leading-tight">
        <div className="font-display text-lg font-semibold tracking-tight">DocSherlock</div>
        {tagline && <div className="text-xs text-muted">Evidence-grounded document investigation</div>}
      </div>
    </div>
  )
}
