import { useState } from 'react'
import { api, ApiError } from '../lib/api'
import { useWorkspace } from '../context/workspace'
import type { Change, Comparison, SourceRef } from '../lib/types'
import { EmptyState } from './EmptyState'
import { PapersIllustration } from './illustrations'
import { CiteChip } from './RichText'
import { SkeletonCard } from './Skeleton'

const DIR_STYLE: Record<string, string> = {
  increased: 'bg-warn-soft text-warn', decreased: 'bg-brand-soft text-brand', later: 'bg-warn-soft text-warn', earlier: 'bg-brand-soft text-brand',
  changed: 'bg-bad-soft text-bad', unchanged: 'bg-none-soft text-none',
}
const ARROW: Record<string, string> = { increased: '▲', decreased: '▼', later: '⟶', earlier: '⟵', changed: '⇄' }

export function ChangeList({ comparison }: { comparison: Comparison }) {
  const { openSource } = useWorkspace()
  const open = (s: Omit<SourceRef, 'cite'>) => openSource({ docId: s.doc_id, docName: s.doc_name, page: s.page ?? 1, start: s.start, end: s.end, quote: s.sentence })
  if (!comparison.changes.length) return <p className="text-sm text-muted">No differing values were found between the two documents.</p>
  const side = (label: string, name: string, c: Change['old'], tone: string) => (
    <div className={`min-w-0 flex-1 rounded-xl border border-line border-t-[3px] bg-surface p-3 ${tone}`}>
      <div className="truncate text-xs text-muted" title={name}>{label} · {name}{c.source.page ? ` · p.${c.source.page}` : ''}</div>
      <div className="mt-0.5 flex flex-wrap items-center gap-1">
        <button className="break-words text-left font-display text-xl font-semibold leading-snug hover:text-brand hover:underline" onClick={() => open(c.source)}>{c.value}</button>
        {c.cite && <CiteChip id={c.cite} onClick={() => open(c.source)} />}
      </div>
    </div>
  )
  return (
    <ul className="space-y-2.5">
      {comparison.changes.map((c: Change, i) => (
        <li key={i} className="rise rounded-2xl border border-line bg-surface-2/50 p-4" style={{ '--i': Math.min(i, 6) } as React.CSSProperties}>
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold capitalize">{c.topic}</span><span className="chip">{c.kind}</span>
            <span className={`ml-auto inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold ${DIR_STYLE[c.direction] ?? DIR_STYLE.changed}`}>{ARROW[c.direction] ?? '⇄'} {c.description}</span>
          </div>
          <div className="flex flex-col items-stretch gap-2 sm:flex-row sm:items-center">
            {side('Older', comparison.old.name, c.old, 'border-t-muted')}
            <span className="self-center text-lg text-muted" aria-hidden>→</span>
            {side('Newer', comparison.new.name, c.new, 'border-t-brand')}
          </div>
          {c.time_scoped && <div className="mt-1.5 text-xs text-warn">time-scoped statement - values may describe different periods</div>}
        </li>
      ))}
    </ul>
  )
}

export function ComparisonView({ result }: { result: Comparison }) {
  const { openSource } = useWorkspace()
  const open = (s: SourceRef) => openSource({ docId: s.doc_id, docName: s.doc_name, page: s.page ?? 1, start: s.start, end: s.end, quote: s.sentence })
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="chip !text-ink">{result.old.name}{result.old.doc_date ? ` · ${result.old.doc_date}` : ''}</span>
        <span className="text-muted">→</span>
        <span className="chip !text-ink">{result.new.name}{result.new.doc_date ? ` · ${result.new.doc_date}` : ''}</span>
        <span className="chip">{result.changes.length} changes</span><span className="chip">{result.unchanged.length} unchanged</span>
        {result.engine && result.engine !== 'rules' && <span className="chip !bg-brand-soft !text-brand">summary by {result.engine}</span>}
      </div>
      <p className="rounded-xl bg-surface-2 p-4 text-[1.0625rem] leading-8">{result.summary}</p>
      <ChangeList comparison={result} />
      {result.unchanged.length > 0 && (
        <details className="rounded-lg border border-line p-3"><summary className="cursor-pointer text-sm font-semibold">Unchanged ({result.unchanged.length})</summary>
          <ul className="mt-2 space-y-1 text-sm">{result.unchanged.map((u, i) => <li key={i}><button className="text-left hover:text-brand hover:underline" onClick={() => open(u.old)}><b>{u.value}</b> · {u.topic}</button></li>)}</ul>
        </details>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        {([['Only in the older document', result.only_in_old], ['Only in the newer document', result.only_in_new]] as const).map(([title, list]) => (
          <details key={title} className="rounded-lg border border-line p-3" open={list.length > 0 && list.length <= 4}><summary className="cursor-pointer text-sm font-semibold">{title} ({list.length})</summary>
            <ul className="mt-2 space-y-1.5 text-sm">{list.map((x, i) => <li key={i}><button className="text-left hover:text-brand hover:underline" onClick={() => open(x.source)}><b>{x.value}</b> — {x.claim}</button></li>)}</ul>
          </details>
        ))}
      </div>
      {result.caveats.map((c) => <p key={c} className="text-xs text-muted">ⓘ {c}</p>)}
    </div>
  )
}

export function ComparePanel() {
  const { readyDocs, toast } = useWorkspace()
  const [a, setA] = useState('')
  const [b, setB] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<Comparison | null>(null)

  const run = async () => {
    setBusy(true)
    try { setResult(await api.compare(a, b)) } catch (e) { toast(e instanceof ApiError ? e.message : 'Comparison failed'); setResult(null) } finally { setBusy(false) }
  }
  const sel = (v: string, set: (s: string) => void, label: string) => (
    <label className="flex min-w-[200px] flex-1 flex-col gap-1.5 text-sm text-muted">{label}
      <select value={v} onChange={(e) => set(e.target.value)} className="field !py-2.5 text-sm">
        <option value="">Choose a document…</option>
        {readyDocs.map((d) => <option key={d.id} value={d.id}>{d.filename}{d.doc_date ? ` (${d.doc_date})` : ''}</option>)}
      </select>
    </label>
  )
  return (
    <div className="mx-auto max-w-5xl space-y-5 px-4 py-6 sm:px-6">
      <div>
        <h2 className="text-3xl font-semibold">Compare two documents</h2>
        <p className="mt-2 max-w-2xl text-base leading-relaxed text-muted">See what changed between two versions - an amendment and its original, this year's policy and last year's. Differences are read from typed claims (amounts, percentages, periods, dates, counts) and ordered by document date, so the direction of change is reliable when both documents are dated.</p>
      </div>
      <div className="card flex flex-wrap items-end gap-4 p-5">
        {sel(a, setA, 'Document A')}{sel(b, setB, 'Document B')}
        <button className="btn btn-primary" disabled={!a || !b || a === b || busy} onClick={() => void run()}>{busy ? 'Comparing…' : 'Compare'}</button>
      </div>
      {readyDocs.length < 2 && <div className="card"><EmptyState art={<PapersIllustration />} title="You need two documents to compare">Add another document - an amendment, a newer policy - and the differences will show up here.</EmptyState></div>}
      {busy && <SkeletonCard />}
      {!busy && result && <div className="card fade p-5"><ComparisonView result={result} /></div>}
    </div>
  )
}
