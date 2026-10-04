import { Fragment, useState } from 'react'
import { DocDateChip } from '../components/DocumentList'
import { FileUploader } from '../components/FileUploader'
import { EmptyState } from '../components/EmptyState'
import { PapersIllustration } from '../components/illustrations'
import { ProcessingStepper } from '../components/ProcessingStepper'
import { Skeleton } from '../components/Skeleton'
import { api } from '../lib/api'
import { useWorkspace } from '../context/workspace'
import { fmtBytes, fmtWhen, isBusy, pct, STAGE_LABEL } from '../lib/format'
import type { ClaimInfo } from '../lib/types'

export default function Documents() {
  const { documents, loadingDocs, removeDoc, resetAll, openSource } = useWorkspace()
  const [open, setOpen] = useState<string | null>(null)
  const [claims, setClaims] = useState<ClaimInfo[] | null>(null)

  const toggle = async (id: string) => {
    if (open === id) { setOpen(null); return }
    setOpen(id); setClaims(null)
    try { setClaims(await api.documents.claims(id)) } catch { setClaims([]) }
  }

  return (
    <div className="scroll-thin min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-6xl space-y-5 px-4 py-6 sm:px-6">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div><h1 className="text-3xl font-semibold">Document library</h1><p className="mt-1 text-base text-muted">Everything in this workspace, with its processing status and the claims DocSherlock extracted from it.</p></div>
          {documents.length > 0 && <button className="btn btn-sm text-bad" onClick={() => { if (window.confirm('Remove all documents from this workspace?')) void resetAll() }}>Clear all</button>}
        </div>
        <FileUploader compact />
        <div className="card overflow-x-auto">
          <table className="w-full min-w-[820px] border-collapse text-sm">
            <thead className="bg-surface-2 text-left text-xs uppercase tracking-wide text-muted">
              <tr><th className="px-4 py-3">Document</th><th className="px-4 py-3">Status</th><th className="px-4 py-3">Pages</th><th className="px-4 py-3">Claims</th><th className="px-4 py-3">OCR</th><th className="px-4 py-3">Date</th><th className="px-4 py-3">Added</th><th /></tr>
            </thead>
            <tbody>
              {loadingDocs && [0, 1, 2].map((i) => <tr key={i} className="border-t border-line"><td colSpan={8} className="px-4 py-3"><Skeleton className="h-8" /></td></tr>)}
              {!loadingDocs && documents.length === 0 && <tr><td colSpan={8}><EmptyState art={<PapersIllustration />} title="Your library is empty">Add documents with the box above. They are read, indexed and checked for conflicts automatically.</EmptyState></td></tr>}
              {documents.map((d) => (
                <Fragment key={d.id}>
                  <tr className="fade border-t border-line align-top transition hover:bg-surface-2/60">
                    <td className="px-4 py-3"><button className="text-left font-semibold hover:text-brand hover:underline" disabled={d.status !== 'READY'} onClick={() => openSource({ docId: d.id, docName: d.filename, page: 1 })}>{d.filename}</button><div className="text-xs text-muted">{d.file_type} · {fmtBytes(d.file_size)}</div></td>
                    <td className="min-w-[150px] px-3 py-2">
                      <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${d.status === 'READY' ? 'bg-ok-soft text-ok' : d.status === 'FAILED' ? 'bg-bad-soft text-bad' : 'bg-brand-soft text-brand'}`}>{STAGE_LABEL[d.status]}</span>
                      {isBusy(d.status) && <ProcessingStepper status={d.status} progress={d.progress} ocr={d.ocr_used} />}
                      {d.error && <div className="mt-1 text-xs text-bad">{d.error}</div>}
                      {d.warnings.map((w) => <div key={w} className="mt-1 text-xs text-warn">⚠ {w}</div>)}
                    </td>
                    <td className="px-4 py-3">{d.n_pages || '—'}</td>
                    <td className="px-4 py-3">{d.status === 'READY' ? <button className="text-brand underline" onClick={() => void toggle(d.id)}>{d.n_claims}</button> : '—'}</td>
                    <td className="px-4 py-3">{d.ocr_used ? pct(d.ocr_conf) : '—'}</td>
                    <td className="px-4 py-3">{d.status === 'READY' ? <DocDateChip doc={d} /> : '—'}</td>
                    <td className="px-4 py-3 text-muted">{fmtWhen(d.uploaded_at)}</td>
                    <td className="px-4 py-3 text-right"><button className="text-muted hover:text-bad" aria-label={`Remove ${d.filename}`} onClick={() => void removeDoc(d.id)}>Remove</button></td>
                  </tr>
                  {open === d.id && (
                    <tr className="bg-surface-2"><td colSpan={8} className="px-3 py-3">
                      {!claims ? <span className="text-muted">Loading claims…</span> : claims.length === 0 ? <span className="text-muted">No typed claims were found in this document.</span> : (
                        <ul className="max-h-72 space-y-1 overflow-y-auto text-sm">
                          {claims.map((c) => <li key={c.id} className="flex gap-2"><span className="chip shrink-0">{c.kind}</span><b className="shrink-0">{c.value || '—'}</b><span className="text-muted">p.{c.page}{c.section ? ` § ${c.section}` : ''} — {c.sentence}</span></li>)}
                        </ul>
                      )}
                    </td></tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
