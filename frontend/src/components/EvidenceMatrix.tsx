import { useState } from 'react'
import { useWorkspace } from '../context/workspace'
import type { Citation, MatrixRow } from '../lib/types'
import { CiteChip } from './RichText'

/** Claim | Source | Page - every competing claim the answer is based on (or disagrees about). */
export function EvidenceMatrix({ rows, citations }: { rows: MatrixRow[]; citations: Citation[] }) {
  const { openSource } = useWorkspace()
  const [open, setOpen] = useState(true)
  if (!rows.length) return null
  const open_ = (r: MatrixRow) => {
    const c = citations.find((x) => x.id === r.cite)
    openSource({ docId: r.doc_id, docName: r.document, page: r.page ?? 1, start: c?.start, end: c?.end, quote: c?.quote ?? r.quote })
  }
  return (
    <div>
      <button className="eyebrow mb-1 flex items-center gap-1" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <span>{open ? '▾' : '▸'}</span> Evidence matrix <span className="chip ml-1 normal-case tracking-normal">{rows.length}</span>
      </button>
      {open && (
        <div className="overflow-x-auto rounded-lg border border-line">
          <table className="w-full min-w-[520px] border-collapse text-sm">
            <thead className="bg-surface-2 text-left text-xs uppercase tracking-wide text-muted">
              <tr><th className="px-2.5 py-1.5">Claim</th><th className="px-2.5 py-1.5">Value</th><th className="px-2.5 py-1.5">Source</th><th className="px-2.5 py-1.5">Page</th><th className="px-2.5 py-1.5" /></tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className="cursor-pointer border-t border-line hover:bg-surface-2" onClick={() => open_(r)}>
                  <td className="max-w-[260px] px-2.5 py-1.5"><div className="font-medium">{r.subject || '—'}</div>{r.date && <div className="text-xs text-muted">as of {r.date}</div>}</td>
                  <td className="px-2.5 py-1.5 font-semibold">{r.value || '—'}</td>
                  <td className="px-2.5 py-1.5">{r.document}</td>
                  <td className="px-2.5 py-1.5 text-muted">{r.page ?? '—'}</td>
                  <td className="px-2.5 py-1.5"><CiteChip id={r.cite} onClick={() => open_(r)} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
