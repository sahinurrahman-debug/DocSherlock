/**
 * The one DocSherlock logo: a lens over a plus sign on a rounded teal tile, with an amber handle, next to a serif wordmark.
 * Every place that shows the brand (top bar, hero, footer ...) uses <Logo />; nothing else may draw its own. The static copy used outside the app
 * (favicon, README, PDF cover, home-screen icon) is `public/favicon.svg` - a test keeps its geometry and colours identical to this component.
 */
export function LogoMark({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" role="img" aria-label="DocSherlock logo" className="shrink-0" data-testid="logo-mark">
      <rect width="32" height="32" rx="9" fill="var(--color-brand)" />
      <circle cx="14" cy="14" r="6.5" fill="none" stroke="var(--color-brand-ink)" strokeWidth="2.4" />
      <path d="M19.2 19.2l6 6" stroke="var(--color-lamp)" strokeWidth="3.2" strokeLinecap="round" />
      <path d="M11.4 14h5.2M14 11.4v5.2" stroke="var(--color-brand-ink)" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  )
}

const SIZES = { md: { mark: 30, word: 'text-lg', gap: 'gap-2.5' }, lg: { mark: 44, word: 'text-3xl', gap: 'gap-3.5' } } as const

export function Logo({ tagline = false, size = 'md' }: { tagline?: boolean; size?: keyof typeof SIZES }) {
  const s = SIZES[size]
  return (
    <div className={`flex items-center ${s.gap}`} data-testid="logo">
      <LogoMark size={s.mark} />
      <div className="leading-tight">
        <div className={`font-display ${s.word} font-semibold tracking-tight`}>DocSherlock</div>
        {tagline && <div className="text-sm text-muted">Evidence-grounded document investigation</div>}
      </div>
    </div>
  )
}
