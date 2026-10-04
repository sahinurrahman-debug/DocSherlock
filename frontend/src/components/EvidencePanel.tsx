import { useWorkspace } from '../context/workspace'
import { SourceViewer } from './SourceViewer'
import { CitationCard } from './CitationCard'

/** Right-hand pane: the source being inspected, or - when nothing is open - the evidence behind the latest answer. */
export function EvidencePanel({ onClose }: { onClose?: () => void }) {
  const { viewer, openSource, closeViewer, thread } = useWorkspace()
  const last = thread[thread.length - 1]
  return (
    <aside className="flex h-full min-h-0 flex-col border-l border-line bg-surface" aria-label="Evidence and source viewer">
      <div className="flex items-center justify-between gap-2 border-b border-line px-3.5 py-2.5">
        <div className="min-w-0">
          <div className="eyebrow">{viewer ? 'Source' : 'Evidence'}</div>
          <div className="truncate text-[13px] font-semibold">{viewer ? viewer.docName : last ? 'Latest answer' : 'Nothing selected'}</div>
        </div>
        <div className="flex gap-1">
          {viewer && last && <button className="btn btn-sm btn-ghost" onClick={closeViewer}>← Evidence</button>}
          {onClose && <button className="btn btn-sm btn-ghost" onClick={onClose} aria-label="Close panel">✕</button>}
        </div>
      </div>
      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto">
        {viewer ? <SourceViewer target={viewer} onPage={(n) => openSource({ ...viewer, page: n, start: undefined, end: undefined, quote: undefined })} />
          : last && last.citations.length ? (
            <div className="space-y-1 p-3">
              <p className="mb-2 text-xs text-muted">Click a source to open the page with the passage highlighted.</p>
              {last.citations.map((c) => <CitationCard key={c.id} c={c} />)}
            </div>
          ) : <p className="p-4 text-[13px] text-muted">Click any citation, document or comparison row to see the exact passage in its original context - the page image with the quote highlighted, or the OCR boxes it was read from.</p>}
      </div>
    </aside>
  )
}
