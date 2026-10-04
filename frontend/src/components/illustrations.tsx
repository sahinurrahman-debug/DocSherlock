/** Small, calm line illustrations for empty states. They only use theme tokens, so they follow light/dark automatically. */

const stroke = { fill: 'none', strokeWidth: 2.2, strokeLinecap: 'round', strokeLinejoin: 'round' } as const

/** A little stack of papers with a magnifying glass resting on it - "nothing here yet, but here is where your documents go". */
export function PapersIllustration({ className = '' }: { className?: string }) {
  return (
    <svg viewBox="0 0 180 130" className={className} role="img" aria-label="A stack of papers with a magnifying glass">
      <ellipse cx="90" cy="118" rx="62" ry="6" fill="var(--color-ink)" opacity=".07" />
      <g {...stroke} stroke="var(--color-line)">
        <rect x="38" y="34" width="84" height="72" rx="8" fill="var(--color-surface-2)" transform="rotate(-6 80 70)" />
        <rect x="50" y="26" width="84" height="76" rx="8" fill="var(--color-surface)" transform="rotate(3 92 64)" />
      </g>
      <g {...stroke} stroke="var(--color-muted)" opacity=".7">
        <path d="M66 52h44M66 64h52M66 76h34" />
      </g>
      <g className="drift">
        <circle cx="122" cy="74" r="20" fill="var(--color-brand-soft)" fillOpacity=".75" stroke="var(--color-brand)" strokeWidth="3.4" />
        <path d="M137 89l16 16" stroke="var(--color-lamp)" strokeWidth="6" strokeLinecap="round" />
        <path d="M113 70h18M122 61v18" stroke="var(--color-brand)" strokeWidth="2.4" strokeLinecap="round" opacity=".7" />
      </g>
    </svg>
  )
}

/** A speech bubble holding a lens - "ask anything". */
export function AskIllustration({ className = '' }: { className?: string }) {
  return (
    <svg viewBox="0 0 180 130" className={className} role="img" aria-label="A speech bubble with a magnifying glass">
      <ellipse cx="90" cy="118" rx="54" ry="5" fill="var(--color-ink)" opacity=".07" />
      <g {...stroke}>
        <path d="M34 30a14 14 0 0 1 14-14h84a14 14 0 0 1 14 14v46a14 14 0 0 1-14 14H80l-24 18v-18H48a14 14 0 0 1-14-14z" fill="var(--color-surface)" stroke="var(--color-line)" />
      </g>
      <g className="drift">
        <circle cx="88" cy="50" r="15" fill="var(--color-brand-soft)" stroke="var(--color-brand)" strokeWidth="3.2" />
        <path d="M99 61l11 11" stroke="var(--color-lamp)" strokeWidth="5.5" strokeLinecap="round" />
      </g>
      <g {...stroke} stroke="var(--color-muted)" opacity=".5"><path d="M52 36h14M114 36h12M54 70h12" /></g>
    </svg>
  )
}

/** Balanced scales - "no disagreements found". */
export function BalanceIllustration({ className = '' }: { className?: string }) {
  return (
    <svg viewBox="0 0 180 130" className={className} role="img" aria-label="Balanced scales">
      <ellipse cx="90" cy="118" rx="48" ry="5" fill="var(--color-ink)" opacity=".07" />
      <g {...stroke} stroke="var(--color-muted)">
        <path d="M90 24v84M64 108h52" />
        <path d="M48 44h84" stroke="var(--color-brand)" strokeWidth="3" />
        <path d="M48 44L34 76h28zM132 44l-14 32h28z" fill="var(--color-brand-soft)" stroke="var(--color-brand)" />
        <path d="M32 76a16 10 0 0 0 32 0M116 76a16 10 0 0 0 32 0" stroke="var(--color-brand)" />
      </g>
      <circle cx="90" cy="22" r="6" fill="var(--color-lamp)" />
    </svg>
  )
}

/** A page with a pin - "pick something to see its source". */
export function SourceIllustration({ className = '' }: { className?: string }) {
  return (
    <svg viewBox="0 0 180 130" className={className} role="img" aria-label="A page with a highlighted passage">
      <ellipse cx="90" cy="118" rx="44" ry="5" fill="var(--color-ink)" opacity=".07" />
      <rect x="52" y="14" width="76" height="98" rx="9" fill="var(--color-surface)" stroke="var(--color-line)" strokeWidth="2.2" />
      <g {...stroke} stroke="var(--color-muted)" opacity=".55"><path d="M66 36h48M66 78h48M66 90h30" /></g>
      <rect x="62" y="48" width="56" height="20" rx="5" fill="var(--color-mark)" opacity=".85" />
      <g {...stroke} stroke="var(--color-ink)" opacity=".7"><path d="M68 55h42M68 62h30" /></g>
    </svg>
  )
}
