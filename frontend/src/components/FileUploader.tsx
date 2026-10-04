import { useEffect, useMemo, useRef, useState } from 'react'
import { useWorkspace } from '../context/workspace'
import { isBusy, STAGE_LABEL } from '../lib/format'
import type { DocStatus } from '../lib/types'

type Row = { key: string; name: string; pct: number; stage: string; state: 'active' | 'done' | 'failed' }

const MAX_ROWS = 4
const DONE_MS = 3500

/** One file inside the drop box: its name, what is happening to it, and a completion bar. */
function FileRow({ row }: { row: Row }) {
  const tone = row.state === 'done' ? 'bg-ok' : row.state === 'failed' ? 'bg-bad' : 'bg-brand'
  const text = row.state === 'done' ? 'text-ok' : row.state === 'failed' ? 'text-bad' : 'text-muted'
  return (
    <li className="pop rounded-xl bg-surface-2 px-3.5 py-2.5 text-left">
      <div className="flex items-baseline justify-between gap-3">
        <span className="min-w-0 truncate text-sm font-medium" title={row.name}>{row.name}</span>
        <span className={`shrink-0 text-sm font-semibold tabular-nums ${text}`}>{row.state === 'done' ? '✓' : row.state === 'failed' ? '✕' : `${row.pct}%`}</span>
      </div>
      <div role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={row.pct} aria-label={`${row.name}: ${row.stage}`} className="mt-2 h-2 overflow-hidden rounded-full bg-line">
        <div className={`h-full rounded-full transition-[width] duration-500 ease-out ${tone} ${row.state === 'active' ? 'bar-active' : ''}`} style={{ width: `${Math.max(row.pct, row.state === 'active' ? 4 : 0)}%` }} />
      </div>
      <div className={`mt-1.5 text-xs ${text}`}>{row.stage}</div>
    </li>
  )
}

export function FileUploader({ compact = false }: { compact?: boolean }) {
  const { upload, uploading, loadDemo, health, documents } = useWorkspace()
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  const accept = health?.formats.join(',')

  // files that just finished processing stay visible for a moment as "Ready" (or "Failed") instead of vanishing
  const seen = useRef(new Map<string, DocStatus>())
  const [finished, setFinished] = useState<Row[]>([])
  useEffect(() => {
    for (const d of documents) {
      const was = seen.current.get(d.id)
      if (was && isBusy(was) && !isBusy(d.status)) {
        const row: Row = d.status === 'READY'
          ? { key: `done-${d.id}`, name: d.filename, pct: 100, stage: 'Ready to question', state: 'done' }
          : { key: `done-${d.id}`, name: d.filename, pct: 100, stage: d.error ?? 'Processing failed', state: 'failed' }
        setFinished((f) => [...f.filter((x) => x.key !== row.key), row])
        window.setTimeout(() => setFinished((f) => f.filter((x) => x.key !== row.key)), DONE_MS)
      }
      seen.current.set(d.id, d.status)
    }
  }, [documents])

  const rows = useMemo<Row[]>(() => {
    const sending: Row[] = uploading.map((u) => ({ key: u.id, name: u.name, pct: Math.round(u.progress * 100), stage: 'Uploading…', state: 'active' }))
    const sentNames = new Set(uploading.map((u) => u.name))
    const working: Row[] = documents.filter((d) => isBusy(d.status) && !sentNames.has(d.filename))
      .map((d) => ({ key: d.id, name: d.filename, pct: Math.max(0, Math.min(100, d.progress)), stage: `${STAGE_LABEL[d.status]}…`, state: 'active' as const }))
    return [...sending, ...working, ...finished]
  }, [uploading, documents, finished])

  const active = rows.filter((r) => r.state === 'active').length
  const hidden = Math.max(0, rows.length - MAX_ROWS)
  const busy = rows.length > 0

  return (
    <div>
      <div
        role="button" tabIndex={0} aria-label="Upload documents"
        onClick={() => input.current?.click()}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.current?.click() } }}
        onDragOver={(e) => { e.preventDefault(); setOver(true) }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); void upload([...e.dataTransfer.files]) }}
        className={`group cursor-pointer rounded-2xl border-2 border-dashed text-center transition duration-300 ${compact ? 'px-4 py-5' : 'px-6 py-8'} ${over ? 'scale-[1.01] border-brand bg-brand-soft' : busy ? 'border-brand/50 bg-surface' : 'border-line bg-surface/70 hover:border-brand/60 hover:bg-surface'}`}
      >
        <input ref={input} type="file" multiple hidden accept={accept} onChange={(e) => { void upload([...(e.target.files ?? [])]); e.target.value = '' }} />

        {busy ? (
          <>
            <ul className="space-y-2.5" data-testid="upload-progress">
              {rows.slice(0, MAX_ROWS).map((r) => <FileRow key={r.key} row={r} />)}
            </ul>
            {hidden > 0 && <p className="mt-2.5 text-sm text-muted">+ {hidden} more file{hidden === 1 ? '' : 's'}…</p>}
            <p className="mt-3 text-sm text-muted">Drop more files or <span className="link">browse</span></p>
            <span className="sr-only" role="status" aria-live="polite">{active > 0 ? `Processing ${active} file${active === 1 ? '' : 's'}` : 'All files processed'}</span>
          </>
        ) : (
          <>
            <svg viewBox="0 0 24 24" className={`mx-auto mb-2 text-brand transition duration-300 group-hover:-translate-y-0.5 ${compact ? 'h-6 w-6' : 'h-9 w-9'}`} fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 16V4M7 9l5-5 5 5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" /></svg>
            <div className="font-medium">Drop files here <span className="font-normal text-muted">or</span> <span className="link">browse</span></div>
            <div className="mt-1.5 text-xs leading-snug text-muted">PDF · Word · scans &amp; images (OCR) · text · CSV / Excel · HTML · JSON · e-mail<br />up to {health?.max_upload_mb ?? 40} MB each</div>
          </>
        )}
      </div>
      {documents.length === 0 && !busy && (
        <button className="btn btn-primary mt-3 w-full" onClick={() => void loadDemo()}>Load the sample set (11 files, some contradict)</button>
      )}
    </div>
  )
}
