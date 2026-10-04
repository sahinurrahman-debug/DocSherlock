import { useEffect, useState } from 'react'
import { useWorkspace } from '../context/workspace'
import { api, ApiError } from '../lib/api'
import type { CaseFileData, EvidenceRef, Finding, FindingType } from '../lib/types'
import { EmptyState } from './EmptyState'
import { BalanceIllustration, PapersIllustration } from './illustrations'
import { RichText } from './RichText'
import { Skeleton, SkeletonCard } from './Skeleton'

const TYPE_META: Record<FindingType, { label: string; icon: string }> = {
  injection: { label: 'Security', icon: 'M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3zM12 8v5M12 16h.01' },
  conflict: { label: 'Disagreement', icon: 'M12 3l9 16H3L12 3zM12 10v4M12 17h.01' },
  superseded: { label: 'Superseded', icon: 'M4 7h12l-3-3M20 17H8l3 3' },
  stale: { label: 'Possibly out of date', icon: 'M12 7v5l3 2M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z' },
  unreadable: { label: 'Unreadable', icon: 'M4 4l16 16M7 4h8l4 4v8M5 8v12h12' },
  ocr: { label: 'Scan quality', icon: 'M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3M4 12h16' },
  undated: { label: 'No date', icon: 'M7 3v3M17 3v3M4 9h16M5 5h14a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z' },
}

const SEVERITY = {
  high: { stripe: 'border-l-bad', chip: 'bg-bad-soft text-bad', label: 'High' },
  medium: { stripe: 'border-l-warn', chip: 'bg-warn-soft text-warn', label: 'Medium' },
  low: { stripe: 'border-l-none', chip: 'bg-none-soft text-none', label: 'Low' },
} as const

function Icon({ d, className = '' }: { d: string; className?: string }) {
  return <svg viewBox="0 0 24 24" className={`h-5 w-5 shrink-0 ${className}`} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={d} /></svg>
}

function Evidence({ e, onOpen }: { e: EvidenceRef; onOpen: (e: EvidenceRef) => void }) {
  return (
    <button type="button" onClick={() => onOpen(e)} className="group block w-full rounded-xl border border-line bg-surface-2/60 px-3.5 py-2.5 text-left transition duration-200 hover:border-brand/50 hover:bg-surface-2">
      <span className="flex flex-wrap items-center gap-x-2 text-xs text-muted">
        <span className="font-semibold text-ink group-hover:text-brand">{e.doc_name}</span>
        {e.doc_date && <span>{e.doc_date}</span>}
        {e.page ? <span>p.{e.page}</span> : null}
        {e.ocr_conf != null && e.ocr_conf < 0.9 && <span className="rounded-full bg-warn-soft px-2 py-0.5 text-warn">OCR {Math.round(e.ocr_conf * 100)}%</span>}
      </span>
      <span className="mt-1 block border-l-[3px] border-lamp/60 pl-3 text-sm leading-relaxed text-ink/90">“{e.quote}”</span>
    </button>
  )
}

function FindingCard({ f, i, onAsk, onBoard }: { f: Finding; i: number; onAsk: (q: string) => void; onBoard?: (clusterId: string) => void }) {
  const { openSource } = useWorkspace()
  const [open, setOpen] = useState(i < 3)
  const meta = TYPE_META[f.type]
  const sev = SEVERITY[f.severity]
  const open_ = (e: EvidenceRef) => openSource({ docId: e.doc_id, docName: e.doc_name, page: e.page ?? 1, start: e.start, end: e.end, quote: e.quote })
  return (
    <article className={`card rise border-l-4 ${sev.stripe} p-5`} style={{ '--i': Math.min(i, 8) } as React.CSSProperties} data-testid="finding" data-type={f.type} data-severity={f.severity}>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 font-semibold ${sev.chip}`}><Icon d={meta.icon} className="!h-4 !w-4" />{meta.label}</span>
        <span className="text-muted">{sev.label} priority</span>
      </div>
      <h3 className="mt-2.5 font-display text-xl font-semibold leading-snug">{f.title}</h3>
      <div className="mt-2 text-muted"><RichText text={f.detail} /></div>
      {f.evidence.length > 0 && (
        <div className="mt-3">
          <button className="text-sm font-medium text-brand underline-offset-4 hover:underline" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
            {open ? 'Hide evidence' : `Show evidence (${f.evidence.length})`}
          </button>
          {open && <div className="fade mt-2 grid gap-2 md:grid-cols-2">{f.evidence.map((e, k) => <Evidence key={k} e={e} onOpen={open_} />)}</div>}
        </div>
      )}
      {(f.question || f.cluster_id) && (
        <div className="mt-4 flex flex-wrap gap-2">
          {f.question && <button className="btn btn-sm" onClick={() => onAsk(f.question as string)}>Ask about this</button>}
          {f.cluster_id && onBoard && <button className="btn btn-sm btn-ghost" onClick={() => onBoard(f.cluster_id as string)}>See on the case board</button>}
        </div>
      )}
    </article>
  )
}

export function CaseFile({ onAsk, onBoard, onConflicts }: { onAsk: (q: string) => void; onBoard?: (clusterId: string) => void; onConflicts?: () => void }) {
  const { scopeIds, documents, readyDocs, loadDemo } = useWorkspace()
  const [data, setData] = useState<CaseFileData | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const key = JSON.stringify(scopeIds) + documents.map((d) => `${d.id}${d.status}${d.doc_date ?? ''}`).join()

  useEffect(() => {
    let alive = true
    if (!readyDocs.length) { setData(null); return }
    api.casefile(scopeIds ?? undefined).then((d) => { if (alive) { setData(d); setErr(null) } }).catch((e: unknown) => alive && setErr(e instanceof ApiError ? e.message : 'Could not build the case file'))
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  if (!readyDocs.length) {
    return (
      <div className="mx-auto max-w-5xl px-4 py-8 sm:px-6">
        <div className="card"><EmptyState art={<PapersIllustration />} title="Your case file starts with documents"
          actions={<button className="btn btn-primary" onClick={() => void loadDemo()}>Load the sample set</button>}>
          As soon as documents are read, DocSherlock reports what needs attention - disagreements, superseded or out-of-date files, poor scans - without you asking anything.
        </EmptyState></div>
      </div>
    )
  }
  const s = data?.stats
  return (
    <div className="mx-auto max-w-5xl space-y-5 px-4 py-6 sm:px-6">
      <header>
        <h2 className="text-3xl font-semibold">Case file</h2>
        {data ? <p className="mt-2 max-w-3xl text-lg leading-relaxed text-muted" data-testid="briefing">{data.briefing}</p> : <div className="mt-3 max-w-3xl space-y-2"><Skeleton className="h-5 w-full" /><Skeleton className="h-5 w-2/3" /></div>}
        {s && (
          <div className="mt-4 flex flex-wrap gap-2 text-sm">
            <span className="chip">{s.documents} documents</span><span className="chip">{s.claims} claims</span>
            <span className={`chip ${s.disputed_points ? '!bg-bad-soft !text-bad' : ''}`}>{s.disputed_points} disputed</span>
            {s.superseded_documents > 0 && <span className="chip !bg-warn-soft !text-warn">{s.superseded_documents} superseded / stale</span>}
            {s.corroborated_points > 0 && <span className="chip !bg-ok-soft !text-ok">{s.corroborated_points} corroborated</span>}
            {s.scans > 0 && <span className="chip">{s.scans} scans</span>}
          </div>
        )}
      </header>

      {err && <p className="text-sm text-bad">{err}</p>}
      {!data && !err && <div className="space-y-4"><SkeletonCard /><SkeletonCard /></div>}
      {data && data.findings.length === 0 && (
        <div className="card"><EmptyState art={<BalanceIllustration />} title="Nothing needs attention">The documents agree wherever they overlap, every file was readable, and all of them carry a date.</EmptyState></div>
      )}
      {data?.findings.map((f, i) => <FindingCard key={f.id} f={f} i={i} onAsk={onAsk} onBoard={onBoard} />)}
      {data && data.omitted_conflicts > 0 && (
        <p className="text-sm text-muted">+ {data.omitted_conflicts} more disputed point{data.omitted_conflicts === 1 ? '' : 's'} of lower priority - {onConflicts ? <button className="link" onClick={onConflicts}>see them all on the Conflict board</button> : 'see the Conflict board'}.</p>
      )}

      {data && data.suggested_questions.length > 0 && (
        <section className="card p-5" aria-label="Questions worth asking">
          <h3 className="font-display text-xl font-semibold">Questions worth asking</h3>
          <div className="mt-3 flex flex-wrap gap-2.5">
            {data.suggested_questions.map((q) => <button key={q} className="rounded-full border border-line bg-surface px-4 py-2 text-sm transition duration-200 hover:-translate-y-0.5 hover:border-brand hover:text-brand active:scale-[.98]" onClick={() => onAsk(q)}>{q}</button>)}
          </div>
        </section>
      )}
    </div>
  )
}
