import { useWorkspace } from '../context/workspace'
import { RichText, CiteChip } from './RichText'
import type { ConflictCluster, SourceRef } from '../lib/types'

const BORDER = ['border-t-bad', 'border-t-brand', 'border-t-ok', 'border-t-warn']
const SEV = { high: 'bg-bad-soft text-bad', medium: 'bg-warn-soft text-warn', low: 'bg-none-soft text-none' }

/** One disputed point: every position with its sources side by side, then what might explain it (labelled as inference). */
export function ConflictAlert({ cluster, showHeader = false }: { cluster: ConflictCluster; showHeader?: boolean }) {
  const { openSource } = useWorkspace()
  const open = (s: SourceRef) => openSource({ docId: s.doc_id, docName: s.doc_name, page: s.page ?? 1, start: s.start, end: s.end, quote: s.sentence })
  return (
    <div className="space-y-3">
      {showHeader && (
        <div className="flex flex-wrap items-center gap-2">
          <span className={`rounded-full px-2 py-0.5 text-[11px] font-bold uppercase ${SEV[cluster.severity]}`}>{cluster.severity}</span>
          <span className="text-[15px] font-bold">{cluster.topic.slice(0, 3).join(' · ') || 'Disputed point'}</span>
          <span className="chip">{cluster.value_kind || cluster.kind}</span>
          {cluster.same_document && <span className="chip">same document</span>}
          {cluster.time_scoped && <span className="chip !bg-warn-soft !text-warn">time-scoped</span>}
        </div>
      )}
      <div className={`grid gap-2.5 sm:grid-cols-2 ${cluster.positions.length > 2 ? 'xl:grid-cols-3' : ''}`}>
        {cluster.positions.map((p, i) => (
          <div key={i} className={`rounded-lg border border-line border-t-[3px] bg-surface p-3 ${BORDER[i % BORDER.length]}`}>
            <div className="break-words text-[17px] font-bold leading-snug">{cluster.kind === 'assertion' ? `Position ${String.fromCharCode(65 + i)}` : p.value}</div>
            {p.sources.map((s, j) => (
              <div key={j} className="mt-2 border-t border-dashed border-line pt-2 first:mt-2 text-[12.5px]">
                <div className="flex flex-wrap items-center gap-1">
                  <button className="font-semibold hover:text-brand hover:underline" onClick={() => open(s)}>{s.doc_name}</button>
                  {s.doc_date && <span className="text-muted">· {s.doc_date}</span>}
                  {s.cite && <CiteChip id={s.cite} onClick={() => open(s)} />}
                </div>
                <q className="mt-0.5 block text-muted [quotes:'“'_'”']">{s.sentence}</q>
                <div className="text-[11px] text-muted">{[s.page ? `p.${s.page}` : null, s.section ? `§ ${s.section}` : null].filter(Boolean).join(' · ')}</div>
              </div>
            ))}
          </div>
        ))}
      </div>
      {cluster.resolution && (
        <div className="rounded-lg border-l-[3px] border-l-warn bg-warn-soft px-3 py-2.5 text-[13px]">
          <div className="mb-0.5 text-[10.5px] font-bold uppercase tracking-wider text-warn">What might explain it · inference, not stated in the documents</div>
          <RichText text={cluster.resolution} />
        </div>
      )}
      {cluster.hints.length > 0 && (
        <ul className="list-disc space-y-0.5 pl-5 text-xs text-muted">{cluster.hints.map((h) => <li key={h}>{h}</li>)}</ul>
      )}
    </div>
  )
}
