import { useWorkspace } from '../context/workspace'
import { pct } from '../lib/format'
import type { Citation } from '../lib/types'
import { CiteChip } from './RichText'

export function CitationCard({ c }: { c: Citation }) {
  const { openSource } = useWorkspace()
  const open = () => openSource({ docId: c.doc_id, docName: c.doc_name, page: c.page ?? 1, start: c.start, end: c.end, quote: c.quote })
  return (
    <div role="button" tabIndex={0} onClick={open} onKeyDown={(e) => { if (e.key === 'Enter') open() }}
      className="group grid cursor-pointer grid-cols-[28px_1fr] gap-2 rounded-lg px-1 py-2 hover:bg-surface-2">
      <div><CiteChip id={c.id} muted={c.role === 'lead'} onClick={open} /></div>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[13px] font-semibold group-hover:text-brand">{c.doc_name}</span>
          {c.role === 'conflict' && <span className="chip !bg-bad-soft !text-bad">conflicting</span>}
          {c.role === 'lead' && <span className="chip">related, not an answer</span>}
          {c.ocr_conf != null && <span className="chip !bg-warn-soft !text-warn">OCR {pct(c.ocr_conf)}</span>}
          {c.doc_date && <span className="chip">{c.doc_date}</span>}
        </div>
        <div className="text-xs text-muted">{[c.page ? `page ${c.page}` : null, c.section ? `section “${c.section}”` : null].filter(Boolean).join(' · ') || 'document'}</div>
        <blockquote className="mt-1 border-l-2 border-line pl-2 text-[13px] text-ink/90">“{c.quote}”</blockquote>
      </div>
    </div>
  )
}
