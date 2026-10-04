import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../lib/api'
import { pct } from '../lib/format'
import type { PageData, ViewerTarget } from '../lib/types'
import { Skeleton } from './Skeleton'

function useBlobUrl(load: () => Promise<Blob>, deps: unknown[]) {
  const [url, setUrl] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    let alive = true
    let made: string | null = null
    setUrl(null); setErr(null)
    load().then((b) => { if (alive) { made = URL.createObjectURL(b); setUrl(made) } }).catch((e: unknown) => alive && setErr(e instanceof ApiError ? e.message : 'Could not load the page image'))
    return () => { alive = false; if (made) URL.revokeObjectURL(made) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return { url, err }
}

/** The cited passage in context: original page image with the quote highlighted (PDF text search / OCR boxes), or the extracted text. */
export function SourceViewer({ target, onPage }: { target: ViewerTarget; onPage: (n: number) => void }) {
  const [data, setData] = useState<PageData | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [view, setView] = useState<'image' | 'text'>('image')
  const mark = useRef<HTMLElement>(null)

  useEffect(() => {
    let alive = true
    setData(null); setErr(null)
    api.documents.page(target.docId, target.page).then((d) => alive && setData(d)).catch((e: unknown) => alive && setErr(e instanceof ApiError ? e.message : 'Could not load the page'))
    return () => { alive = false }
  }, [target.docId, target.page])

  const hasImage = data?.page.has_image ?? false
  const img = useBlobUrl(() => api.documents.pageImage(target.docId, target.page, target.start, target.end), [target.docId, target.page, target.start, target.end, hasImage])

  useEffect(() => { if (view === 'text') mark.current?.scrollIntoView({ block: 'center' }) }, [view, data])
  useEffect(() => { if (data && !data.page.has_image) setView('text') }, [data])

  if (err) return <p className="p-4 text-sm text-bad">{err}</p>
  if (!data) return <div className="space-y-3 p-4" role="status" aria-label="Loading page"><Skeleton className="h-5 w-1/2" /><Skeleton className="h-72" /></div>
  const { page, document: doc } = data
  const text = page.text
  const hasQuote = target.start != null && target.end != null && target.start >= 0 && target.end > target.start && target.end <= text.length

  return (
    <div className="space-y-3 p-3.5">
      <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted">
        <span>{doc.paged ? `Page ${page.number} of ${data.n_pages}` : 'Whole document'}</span>
        {doc.paged && data.n_pages > 1 && (
          <span className="flex gap-1">
            <button className="btn btn-sm" disabled={page.number <= 1} onClick={() => onPage(page.number - 1)} aria-label="Previous page">‹</button>
            <button className="btn btn-sm" disabled={page.number >= data.n_pages} onClick={() => onPage(page.number + 1)} aria-label="Next page">›</button>
          </span>
        )}
        {page.ocr_conf != null && <span className="chip !bg-warn-soft !text-warn">OCR {pct(page.ocr_conf)}</span>}
        {doc.doc_date && <span className="chip">dated {doc.doc_date}</span>}
        <button className="ml-auto text-brand underline" onClick={() => void api.documents.original(doc.id, doc.filename)}>original</button>
      </div>
      {target.quote && <div className="rounded-lg border-l-[3px] border-l-brand bg-brand-soft px-3 py-2 text-sm">“{target.quote}”</div>}
      {page.has_image && (
        <div className="inline-flex overflow-hidden rounded-lg border border-line text-xs" role="tablist">
          {(['image', 'text'] as const).map((v) => (
            <button key={v} role="tab" aria-selected={view === v} onClick={() => setView(v)} className={`px-3 py-1 ${view === v ? 'bg-brand text-brand-ink' : 'bg-surface hover:bg-surface-2'}`}>{v === 'image' ? 'Original' : 'Extracted text'}</button>
          ))}
        </div>
      )}
      {page.has_image && view === 'image' && (
        img.err ? <p className="text-sm text-bad">{img.err}</p>
          : img.url ? <img src={img.url} alt={`Page ${page.number} of ${doc.filename} with the cited passage highlighted`} className="w-full rounded-lg border border-line bg-white" />
          : <Skeleton className="h-72" />
      )}
      {view === 'text' && (
        <div className="max-h-[70vh] overflow-auto whitespace-pre-wrap break-words rounded-lg bg-surface-2 p-3 font-mono text-sm leading-relaxed">
          {hasQuote ? <>{text.slice(0, target.start)}<mark ref={mark} className="rounded bg-mark px-0.5 text-ink">{text.slice(target.start, target.end)}</mark>{text.slice(target.end)}</> : text || '(no text extracted)'}
        </div>
      )}
    </div>
  )
}
