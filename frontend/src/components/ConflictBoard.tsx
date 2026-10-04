import { useEffect, useState } from 'react'
import { api, ApiError } from '../lib/api'
import { useWorkspace } from '../context/workspace'
import type { ConflictCluster } from '../lib/types'
import { ConflictAlert } from './ConflictAlert'
import { EmptyState } from './EmptyState'
import { BalanceIllustration, PapersIllustration } from './illustrations'
import { SkeletonCard } from './Skeleton'

/** Every disputed point across the documents in scope - found at upload time, whether or not anyone has asked about it. */
export function ConflictBoard({ onAsk }: { onAsk?: (q: string) => void }) {
  const { scopeIds, documents, readyDocs } = useWorkspace()
  const [data, setData] = useState<{ conflicts: ConflictCluster[]; documents: number; claims: number } | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [sev, setSev] = useState<'all' | 'high' | 'medium' | 'low'>('all')
  const key = JSON.stringify(scopeIds) + documents.map((d) => `${d.id}${d.status}${d.doc_date ?? ''}`).join()

  useEffect(() => {
    let alive = true
    api.conflicts(scopeIds ?? undefined).then((d) => { if (alive) { setData(d); setErr(null) } }).catch((e: unknown) => alive && setErr(e instanceof ApiError ? e.message : 'Could not load conflicts'))
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  const list = (data?.conflicts ?? []).filter((c) => sev === 'all' || c.severity === sev)
  return (
    <div className="mx-auto max-w-5xl space-y-5 px-4 py-6 sm:px-6">
      <div>
        <h2 className="text-3xl font-semibold">Conflict board</h2>
        <p className="mt-2 max-w-2xl text-base leading-relaxed text-muted">Every disputed point found across your documents: statements about the same subject with incompatible values. Differences explained by scope (different quarters, entities, as-of dates) are deliberately not flagged.</p>
      </div>
      {data && <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="chip">{data.conflicts.length} disputed points</span><span className="chip">{data.documents} documents</span><span className="chip">{data.claims} claims checked</span>
        <span className="ml-auto flex gap-1">{(['all', 'high', 'medium', 'low'] as const).map((s) => <button key={s} className={`btn btn-sm ${sev === s ? '!border-brand !text-brand' : ''}`} onClick={() => setSev(s)}>{s}</button>)}</span>
      </div>}
      {err && <p className="text-sm text-bad">{err}</p>}
      {!data && !err && <div className="space-y-4"><SkeletonCard /><SkeletonCard /></div>}
      {data && list.length === 0 && (readyDocs.length < 2
        ? <div className="card"><EmptyState art={<PapersIllustration />} title="Add a second document to compare">Conflicts appear when two documents say different things about the same subject.</EmptyState></div>
        : <div className="card"><EmptyState art={<BalanceIllustration />} title="No disagreements found">{sev === 'all' ? 'The documents in scope agree wherever they overlap.' : `No ${sev}-severity conflicts - try another filter.`}</EmptyState></div>)}
      {list.map((c) => (
        <section key={c.id} className="card rise space-y-4 p-5" style={{ '--i': Math.min(list.indexOf(c), 6) } as React.CSSProperties}>
          <ConflictAlert cluster={c} showHeader />
          {onAsk && <button className="btn btn-sm" onClick={() => onAsk(`What does the documentation say about ${c.topic.slice(0, 3).join(' ')}?`)}>Investigate in Ask →</button>}
        </section>
      ))}
    </div>
  )
}
