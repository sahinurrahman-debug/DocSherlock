import { useEffect, useState } from 'react'
import { api, ApiError } from '../lib/api'
import { useWorkspace } from '../context/workspace'
import type { ConflictCluster } from '../lib/types'
import { ConflictAlert } from './ConflictAlert'

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
    <div className="mx-auto max-w-5xl space-y-4 p-4">
      <div>
        <h2 className="text-lg font-bold">Conflict board</h2>
        <p className="mt-1 max-w-2xl text-[13px] text-muted">Every disputed point found across your documents: statements about the same subject with incompatible values. Differences explained by scope (different quarters, entities, as-of dates) are deliberately not flagged.</p>
      </div>
      {data && <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="chip">{data.conflicts.length} disputed points</span><span className="chip">{data.documents} documents</span><span className="chip">{data.claims} claims checked</span>
        <span className="ml-auto flex gap-1">{(['all', 'high', 'medium', 'low'] as const).map((s) => <button key={s} className={`btn btn-sm ${sev === s ? '!border-brand !text-brand' : ''}`} onClick={() => setSev(s)}>{s}</button>)}</span>
      </div>}
      {err && <p className="text-[13px] text-bad">{err}</p>}
      {data && list.length === 0 && <div className="card p-6 text-center text-[13px] text-muted">{readyDocs.length < 2 ? 'Add at least two related documents to compare them.' : 'No conflicts detected between the documents in scope.'}</div>}
      {list.map((c) => (
        <section key={c.id} className="card space-y-3 p-4">
          <ConflictAlert cluster={c} showHeader />
          {onAsk && <button className="btn btn-sm" onClick={() => onAsk(`What does the documentation say about ${c.topic.slice(0, 3).join(' ')}?`)}>Investigate in Ask →</button>}
        </section>
      ))}
    </div>
  )
}
