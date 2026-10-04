import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { useWorkspace } from '../context/workspace'

type Tone = 'ok' | 'warn' | 'bad' | 'none'

const DOT: Record<Tone, string> = { ok: 'bg-ok', warn: 'bg-warn', bad: 'bg-bad', none: 'bg-none' }

function Row({ label, value, tone }: { label: string; value: ReactNode; tone: Tone }) {
  return (
    <div className="flex items-center justify-between gap-4 py-2">
      <dt className="text-sm text-muted">{label}</dt>
      <dd className="flex min-w-0 items-center gap-2 text-sm font-medium text-ink"><i className={`h-2 w-2 shrink-0 rounded-full ${DOT[tone]}`} aria-hidden="true" /><span className="truncate">{value}</span></dd>
    </div>
  )
}

/** One compact control for the whole system state (answer engine, database, vector store, search, OCR); the details open in a small panel. */
export function StatusMenu({ extra }: { extra?: ReactNode }) {
  const { health: h } = useWorkspace()
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const id = useId()

  useEffect(() => {
    if (!open) return
    const down = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false) }
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', down)
    document.addEventListener('keydown', key)
    return () => { document.removeEventListener('mousedown', down); document.removeEventListener('keydown', key) }
  }, [open])

  let tone: Tone = 'none'
  let label = 'Connecting…'
  let rows: { label: string; value: ReactNode; tone: Tone }[] = []
  if (h) {
    const dense = h.models.dense
    const search = dense.ready ? { v: 'Semantic search', t: 'ok' as Tone } : dense.loading ? { v: 'Loading models…', t: 'warn' as Tone } : dense.enabled ? { v: 'Models pending', t: 'warn' as Tone } : { v: 'Keyword search', t: 'none' as Tone }
    rows = [
      { label: 'Answer engine', value: h.llm.available ? `Groq · ${h.llm.model?.split('/').pop()}` : 'Rule-based (no LLM key)', tone: h.llm.available ? 'ok' : 'warn' },
      { label: 'Database', value: h.database.engine, tone: h.database.ok ? 'ok' : 'bad' },
      { label: 'Vector store', value: h.vector_store.mode === 'disabled' ? 'Not used' : `Qdrant · ${h.vector_store.mode}`, tone: h.vector_store.mode === 'disabled' ? 'none' : h.vector_store.ok ? 'ok' : 'bad' },
      { label: 'Search', value: search.v, tone: search.t },
      { label: 'OCR', value: h.ocr.available ? 'Available' : 'Off', tone: h.ocr.available ? 'ok' : 'none' },
    ]
    const bad = h.status !== 'healthy' || rows.some((r) => r.tone === 'bad')
    const warn = rows.some((r) => r.tone === 'warn')
    tone = bad ? 'bad' : warn ? 'warn' : 'ok'
    label = bad ? 'Degraded' : warn ? 'Limited' : 'Ready'
  }

  return (
    <div ref={box} className="relative">
      <button type="button" aria-expanded={open} aria-controls={id} aria-haspopup="true" onClick={() => setOpen((o) => !o)} title="System status"
        className="inline-flex h-10 items-center gap-2.5 rounded-xl border border-line bg-surface px-3.5 text-sm font-medium text-ink transition duration-200 hover:border-brand/50 hover:bg-surface-2 active:scale-[.98]">
        <i className={`h-2.5 w-2.5 rounded-full ${DOT[tone]} ${h ? '' : 'animate-pulse'}`} aria-hidden="true" />
        <span>{label}</span>
        <span className="sr-only">- system status</span>
        <svg viewBox="0 0 20 20" className={`h-4 w-4 text-muted transition duration-200 ${open ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M5 8l5 5 5-5" /></svg>
      </button>
      {open && (
        <div id={id} role="group" aria-label="System status" className="pop absolute right-0 top-full z-40 mt-2 w-80 max-w-[calc(100vw-2rem)] rounded-2xl border border-line bg-surface p-4 shadow-[var(--shadow-lift)]">
          <div className="eyebrow mb-1">System status</div>
          {h ? <dl className="divide-y divide-line">{rows.map((r) => <Row key={r.label} {...r} />)}</dl> : <p className="py-2 text-sm text-muted">Connecting to the API…</p>}
          {extra && <div className="mt-2 border-t border-line pt-3">{extra}</div>}
        </div>
      )}
    </div>
  )
}
