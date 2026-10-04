import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { LogoMark } from '../components/Logo'
import { FileUploader } from '../components/FileUploader'
import { useWorkspace } from '../context/workspace'
import { api } from '../lib/api'
import { fmtWhen } from '../lib/format'

const PIPELINE = [
  ['Ingest', 'PDF · DOCX · scans · CSV · HTML · EML, with OCR for scanned pages'],
  ['Index', 'Section-aware chunks, typed claims, dense + sparse vectors in Qdrant'],
  ['Retrieve', 'Hybrid search, reranking, then sentence-level evidence selection'],
  ['Investigate', 'Conflict detection, comparison and calibrated uncertainty'],
  ['Answer', 'Groq LLM with every quote verified; rule-based fallback'],
] as const

function Stat({ label, value, hint, tone }: { label: string; value: string | number; hint?: string; tone?: string }) {
  return (
    <div className="card p-4">
      <div className="eyebrow">{label}</div>
      <div className={`mt-1 text-3xl font-bold tracking-tight ${tone ?? ''}`}>{value}</div>
      {hint && <div className="mt-0.5 text-xs text-muted">{hint}</div>}
    </div>
  )
}

export default function Dashboard() {
  const { documents, readyDocs, investigations, loadDemo, health, openInvestigation } = useWorkspace()
  const nav = useNavigate()
  const [disputes, setDisputes] = useState<number | null>(null)
  const claims = readyDocs.reduce((n, d) => n + d.n_claims, 0)
  const key = readyDocs.map((d) => d.id + (d.doc_date ?? '')).join()

  useEffect(() => { api.conflicts().then((d) => setDisputes(d.conflicts.length)).catch(() => setDisputes(null)) }, [key])

  return (
    <div className="scroll-thin min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-6xl space-y-6 p-5">
        <section className="card overflow-hidden">
          <div className="grid gap-6 bg-gradient-to-br from-brand-soft to-surface p-6 md:grid-cols-[1.3fr_1fr] md:p-8">
            <div>
              <div className="flex items-center gap-3"><LogoMark size={40} /><span className="text-sm font-semibold uppercase tracking-widest text-brand">DocSherlock</span></div>
              <h1 className="mt-3 text-3xl font-extrabold leading-tight tracking-tight md:text-4xl">Ask your documents.<br />Trust what is proven.</h1>
              <p className="mt-3 max-w-xl text-[14.5px] leading-relaxed text-muted">Upload PDFs, scans, Word files, emails and spreadsheets. DocSherlock answers in plain English with the exact supporting passage - and when documents <b className="text-ink">disagree</b> or simply <b className="text-ink">don't say</b>, it tells you instead of guessing.</p>
              <div className="mt-5 flex flex-wrap gap-2">
                <Link to="/investigate" className="btn btn-primary px-4 py-2">Start investigating →</Link>
                {documents.length === 0 && <button className="btn px-4 py-2" onClick={() => void loadDemo().then(() => nav('/investigate'))}>Try the sample set</button>}
              </div>
            </div>
            <div><FileUploader /></div>
          </div>
        </section>

        <section className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat label="Documents ready" value={readyDocs.length} hint={documents.length > readyDocs.length ? `${documents.length - readyDocs.length} processing / failed` : 'in this workspace'} />
          <Stat label="Claims extracted" value={claims} hint="typed amounts, dates, periods, counts" />
          <Stat label="Disputed points" value={disputes ?? '—'} hint="documents that disagree" tone={disputes ? 'text-bad' : ''} />
          <Stat label="Investigations" value={investigations.length} hint="saved question histories" />
        </section>

        <section className="card p-5">
          <h2 className="text-sm font-bold">How DocSherlock reaches an answer</h2>
          <ol className="mt-3 grid gap-3 md:grid-cols-5">
            {PIPELINE.map(([t, d], i) => (
              <li key={t} className="rounded-lg bg-surface-2 p-3">
                <div className="flex items-center gap-2 text-[13px] font-bold"><span className="grid h-5 w-5 place-items-center rounded-full bg-brand text-[11px] text-brand-ink">{i + 1}</span>{t}</div>
                <p className="mt-1.5 text-xs leading-snug text-muted">{d}</p>
              </li>
            ))}
          </ol>
        </section>

        <div className="grid gap-6 md:grid-cols-2">
          <section className="card p-5">
            <h2 className="text-sm font-bold">Recent investigations</h2>
            {investigations.length === 0 ? <p className="mt-2 text-[13px] text-muted">None yet - ask a question to start one.</p> : (
              <ul className="mt-2 divide-y divide-line">
                {investigations.slice(0, 6).map((i) => (
                  <li key={i.id}><button className="flex w-full items-center justify-between gap-3 py-2 text-left hover:text-brand" onClick={() => { void openInvestigation(i.id); nav('/investigate') }}>
                    <span className="truncate text-[13px] font-medium">{i.name}</span><span className="shrink-0 text-xs text-muted">{i.n_questions} q · {fmtWhen(i.updated_at)}</span></button></li>
                ))}
              </ul>
            )}
          </section>
          <section className="card p-5">
            <h2 className="text-sm font-bold">System</h2>
            {!health ? <p className="mt-2 text-[13px] text-muted">Connecting to the API…</p> : (
              <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-[13px]">
                <dt className="text-muted">Answer engine</dt><dd>{health.llm.available ? <>Groq <code>{health.llm.model}</code> <span className="text-muted">→ rule-based fallback</span></> : <span className="text-warn">Rule-based only - set GROQ_API_KEY to enable the LLM</span>}</dd>
                <dt className="text-muted">Database</dt><dd>{health.database.engine}{health.database.ok ? '' : ' (down)'}</dd>
                <dt className="text-muted">Vector store</dt><dd>{health.vector_store.mode === 'disabled' ? 'not used (keyword mode)' : `Qdrant · ${health.vector_store.mode}${health.vector_store.ok ? '' : ' (down)'}`}</dd>
                <dt className="text-muted">Models</dt><dd>{health.models.dense.ready ? 'embeddings ready' : health.models.dense.loading ? 'loading…' : 'keyword search (embeddings off)'}{health.models.reranker.ready ? ' · reranker' : ''}</dd>
                <dt className="text-muted">OCR</dt><dd>{health.ocr.available ? 'RapidOCR available' : 'unavailable'}</dd>
              </dl>
            )}
          </section>
        </div>
      </div>
    </div>
  )
}
