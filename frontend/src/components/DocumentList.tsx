import { useWorkspace } from '../context/workspace'
import { isBusy, pct } from '../lib/format'
import type { DocumentInfo } from '../lib/types'
import { EmptyState } from './EmptyState'
import { PapersIllustration } from './illustrations'
import { ProcessingStepper } from './ProcessingStepper'
import { Skeleton } from './Skeleton'

export function DocDateChip({ doc }: { doc: DocumentInfo }) {
  const { setDate } = useWorkspace()
  return (
    <button
      className="chip hover:border-brand hover:text-brand"
      title={(doc.doc_date_source ? `Detected: ${doc.doc_date_source}. ` : '') + 'Click to set the document date - it drives "which source is newer" in conflict reasoning.'}
      onClick={(e) => {
        e.stopPropagation()
        const v = window.prompt(`Date of "${doc.filename}" (YYYY, YYYY-MM or YYYY-MM-DD). Leave empty to clear.`, doc.doc_date ?? '')
        if (v !== null) void setDate(doc.id, v.trim() || null)
      }}
    >
      {doc.doc_date ? `dated ${doc.doc_date}` : 'set date'}
    </button>
  )
}

function DocItem({ doc }: { doc: DocumentInfo }) {
  const { deselected, toggleDoc, removeDoc, openSource } = useWorkspace()
  const ready = doc.status === 'READY'
  return (
    <li className={`pop rounded-xl border bg-surface p-3 transition duration-200 hover:shadow-[var(--shadow-card)] ${doc.status === 'FAILED' ? 'border-bad/50' : 'border-line'}`}>
      <div className="flex items-start gap-2">
        <input
          type="checkbox" className="mt-1 accent-[var(--color-brand)]" disabled={!ready} checked={ready && !deselected.has(doc.id)}
          onChange={() => toggleDoc(doc.id)} aria-label={`Include ${doc.filename} in the investigation`} title="Include in the investigation scope"
        />
        <button className="min-w-0 flex-1 text-left" disabled={!ready} onClick={() => openSource({ docId: doc.id, docName: doc.filename, page: 1 })}>
          <div className="flex items-center gap-1.5">
            <span className="rounded-md bg-brand-soft px-1.5 py-0.5 text-xs font-bold uppercase text-brand">{doc.file_type.replace('.', '')}</span>
            <span className="break-all text-sm font-semibold leading-snug">{doc.filename}</span>
          </div>
        </button>
        <button className="px-1 text-muted hover:text-bad" aria-label={`Remove ${doc.filename}`} onClick={() => void removeDoc(doc.id)}>×</button>
      </div>
      {isBusy(doc.status) && <ProcessingStepper status={doc.status} progress={doc.progress} ocr={doc.ocr_used || doc.file_type.match(/png|jpe?g|tiff?|bmp|webp|gif/) !== null} />}
      {doc.status === 'FAILED' && <div className="mt-1.5 text-xs text-bad">✕ {doc.error ?? 'Processing failed'}</div>}
      {ready && (
        <div className="mt-1.5 flex flex-wrap items-center gap-1">
          <span className="chip">{doc.n_pages} {doc.paged ? (doc.n_pages === 1 ? 'page' : 'pages') : 'section'}</span>
          <span className="chip">{doc.n_claims} claims</span>
          {doc.ocr_used && <span className="chip !bg-warn-soft !text-warn" title="Text recovered with OCR">OCR {pct(doc.ocr_conf)}</span>}
          {!doc.indexed && <span className="chip" title="Semantic vectors not available for this document - keyword retrieval is used">keyword only</span>}
          <DocDateChip doc={doc} />
        </div>
      )}
      {doc.warnings.slice(0, 2).map((w) => <div key={w} className="mt-1 text-xs text-warn">⚠ {w}</div>)}
    </li>
  )
}

export function DocumentList() {
  const { documents, loadingDocs, readyDocs, selectAll, deselected } = useWorkspace()
  if (loadingDocs) return <div className="space-y-2" role="status" aria-label="Loading documents">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-[4.5rem]" />)}</div>
  if (!documents.length) return <EmptyState compact art={<PapersIllustration />} title="Nothing here yet">Drop a file above, or load the sample set to see DocSherlock in action.</EmptyState>
  return (
    <div>
      {readyDocs.length > 1 && (
        <div className="mb-1.5 flex items-center justify-between text-xs text-muted">
          <span>{readyDocs.length - deselected.size} of {readyDocs.length} in scope</span>
          {deselected.size > 0 && <button className="text-brand underline" onClick={selectAll}>include all</button>}
        </div>
      )}
      <ul className="space-y-2">{documents.map((d) => <DocItem key={d.id} doc={d} />)}</ul>
    </div>
  )
}
