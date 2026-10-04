import { useState } from 'react'
import { LEVELS, TONE_CLASS } from '../lib/format'
import type { Level, Reason } from '../lib/types'

const ICON: Record<Level, string> = { HIGH: '●', MEDIUM: '◐', LOW: '◔', CONFLICTED: '⚠', INSUFFICIENT: '?' }

export function ConfidenceBadge({ level, size = 'md' }: { level: Level; size?: 'sm' | 'md' }) {
  const m = LEVELS[level]
  return (
    <span title={m.hint} className={`inline-flex items-center gap-1.5 rounded-full font-semibold ${TONE_CLASS[m.tone]} ${size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-3 py-1 text-xs'}`}>
      <span aria-hidden>{ICON[level]}</span>{level === 'LOW' || level === 'MEDIUM' || level === 'HIGH' ? level : level === 'CONFLICTED' ? 'CONFLICTED' : 'INSUFFICIENT'}
      <span className="sr-only">{m.label}</span>
    </span>
  )
}

const EFFECT = { '+': 'text-ok', '-': 'text-bad', '=': 'text-muted' } as const

export function WhyPanel({ level, reasons }: { level: Level; reasons: Reason[] }) {
  const [open, setOpen] = useState(false)
  if (!reasons.length) return null
  return (
    <div>
      <button className="text-xs font-medium text-brand underline-offset-2 hover:underline" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {open ? 'Hide reasoning' : `Why ${level === 'CONFLICTED' ? 'conflicted' : level === 'INSUFFICIENT' ? 'insufficient' : level.toLowerCase()}?`}
      </button>
      {open && (
        <ul className="mt-2 space-y-1 rounded-lg bg-surface-2 p-3 text-sm">
          {reasons.map((r, i) => (
            <li key={i} className="flex gap-2"><span className={`w-3 shrink-0 text-center font-bold ${EFFECT[r.effect]}`}>{r.effect === '=' ? '·' : r.effect}</span><span>{r.text}</span></li>
          ))}
          <li className="pt-1 text-xs text-muted">The level reflects evidence strength (term coverage, semantic match, corroboration, OCR quality, conflicts) - it is not a probability.</li>
        </ul>
      )}
    </div>
  )
}
