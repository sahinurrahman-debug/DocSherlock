import type { ReactNode } from 'react'

/** A deliberate "nothing here yet" moment: a quiet illustration, a plain-language headline, one line of help, and the next step. */
export function EmptyState({ art, title, children, actions, compact = false, className = '' }: {
  art?: ReactNode; title: string; children?: ReactNode; actions?: ReactNode; compact?: boolean; className?: string
}) {
  return (
    <div className={`rise mx-auto flex max-w-md flex-col items-center text-center ${compact ? 'gap-1 py-4' : 'gap-2 py-10'} ${className}`}>
      {art && <div className={compact ? 'w-28' : 'w-44'} aria-hidden={false}>{art}</div>}
      <h3 className={`font-display font-semibold tracking-tight ${compact ? 'text-base' : 'text-xl'}`}>{title}</h3>
      {children && <p className="text-sm leading-relaxed text-muted">{children}</p>}
      {actions && <div className="mt-2 flex flex-wrap justify-center gap-2">{actions}</div>}
    </div>
  )
}
