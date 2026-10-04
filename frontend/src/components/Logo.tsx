export function LogoMark({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" className="shrink-0">
      <rect width="32" height="32" rx="8" fill="var(--color-brand)" />
      <circle cx="14" cy="14" r="6.5" fill="none" stroke="var(--color-brand-ink)" strokeWidth="2.6" />
      <path d="M19 19l6 6" stroke="#f2a900" strokeWidth="3" strokeLinecap="round" />
      <path d="M11 14h6M14 11v6" stroke="var(--color-brand-ink)" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  )
}

export function Logo({ tagline = false }: { tagline?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <LogoMark />
      <div className="leading-tight">
        <div className="text-[15px] font-bold tracking-tight">DocSherlock</div>
        {tagline && <div className="text-[11px] text-muted">Evidence-grounded document investigation</div>}
      </div>
    </div>
  )
}
