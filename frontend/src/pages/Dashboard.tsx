import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { CaseFileTeaser } from '../components/CaseFileTeaser'
import { EmptyState } from '../components/EmptyState'
import { FileUploader } from '../components/FileUploader'
import { AskIllustration } from '../components/illustrations'
import { Logo } from '../components/Logo'
import { SiteFooter } from '../components/SiteFooter'
import { Skeleton, SkeletonLines } from '../components/Skeleton'
import { useWorkspace } from '../context/workspace'
import { api } from '../lib/api'
import { fmtWhen } from '../lib/format'

const PIPELINE = [
  ['Ingest', 'PDF, Word, scans, spreadsheets, e-mails - with OCR for scanned pages.'],
  ['Index', 'Section-aware passages, typed claims, and searchable vectors.'],
  ['Retrieve', 'Keyword and meaning-based search, then sentence-level evidence.'],
  ['Investigate', 'Conflicts, comparisons and an honest level of confidence.'],
  ['Answer', 'A plain-English reply where every quote is checked against the source.'],
] as const

function greeting(): string {
  const h = new Date().getHours()
  return h < 5 ? 'Still up?' : h < 12 ? 'Good morning.' : h < 18 ? 'Good afternoon.' : 'Good evening.'
}

function Stat({ label, value, hint, tone, loading, i }: { label: string; value: string | number; hint?: string; tone?: string; loading?: boolean; i: number }) {
  return (
    <div className="card rise p-5" style={{ '--i': i + 2 } as React.CSSProperties}>
      <div className="eyebrow">{label}</div>
      {loading ? <Skeleton className="mt-2 h-9 w-16" /> : <div className={`mt-1 font-display text-4xl font-semibold tracking-tight ${tone ?? ''}`}>{value}</div>}
      {hint && <div className="mt-1 text-sm text-muted">{hint}</div>}
    </div>
  )
}

export default function Dashboard() {
  const { documents, loadingDocs, readyDocs, investigations, loadDemo, health, openInvestigation } = useWorkspace()
  const nav = useNavigate()
  const [disputes, setDisputes] = useState<number | null>(null)
  const claims = readyDocs.reduce((n, d) => n + d.n_claims, 0)
  const key = readyDocs.map((d) => d.id + (d.doc_date ?? '')).join()

  useEffect(() => { api.conflicts().then((d) => setDisputes(d.conflicts.length)).catch(() => setDisputes(null)) }, [key])

  return (
    <div className="scroll-thin min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-6xl space-y-6 px-4 py-6 sm:px-6 sm:py-8">
        <section className="card rise overflow-hidden">
          <div className="grid gap-8 bg-gradient-to-br from-brand-soft via-surface to-surface p-6 md:grid-cols-[1.2fr_1fr] md:p-10">
            <div>
              <Logo size="lg" />
              <h1 className="mt-5 text-4xl font-semibold leading-[1.1] md:text-5xl">{greeting()}<br /><span className="text-brand">What shall we look into?</span></h1>
              <p className="mt-5 max-w-xl text-lg leading-relaxed text-muted">Bring your PDFs, scans, e-mails and spreadsheets. DocSherlock answers in plain English with the exact passage - and when documents <b className="font-semibold text-ink">disagree</b> or simply <b className="font-semibold text-ink">don't say</b>, it tells you, rather than guessing.</p>
              <div className="mt-7 flex flex-wrap gap-3">
                <Link to="/investigate" className="btn btn-primary !px-6 !py-2.5 text-base">Start investigating</Link>
                {!loadingDocs && documents.length === 0 && <button className="btn !px-6 !py-2.5 text-base" onClick={() => void loadDemo().then(() => nav('/investigate'))}>Try the sample set</button>}
              </div>
            </div>
            <div className="self-center"><FileUploader /></div>
          </div>
        </section>

        <section className="grid grid-cols-2 gap-4 md:grid-cols-4" aria-label="Workspace at a glance">
          <Stat i={0} loading={loadingDocs} label="Documents ready" value={readyDocs.length} hint={documents.length > readyDocs.length ? `${documents.length - readyDocs.length} still processing` : 'in this workspace'} />
          <Stat i={1} loading={loadingDocs} label="Claims found" value={claims} hint="amounts, dates, periods, counts" />
          <Stat i={2} loading={loadingDocs || (readyDocs.length > 0 && disputes === null)} label="Points of dispute" value={disputes ?? '—'} hint="where documents disagree" tone={disputes ? 'text-bad' : ''} />
          <Stat i={3} loading={loadingDocs} label="Investigations" value={investigations.length} hint="saved question histories" />
        </section>

        <CaseFileTeaser />

        <section className="card rise p-6 sm:p-7" style={{ '--i': 5 } as React.CSSProperties}>
          <h2 className="text-2xl font-semibold">How an answer is reached</h2>
          <ol className="mt-5 grid gap-4 md:grid-cols-5">
            {PIPELINE.map(([t, d], i) => (
              <li key={t} className="rounded-xl bg-surface-2 p-4">
                <div className="flex items-center gap-2.5 text-base font-semibold"><span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-brand text-xs font-bold text-brand-ink">{i + 1}</span>{t}</div>
                <p className="mt-2 text-sm leading-relaxed text-muted">{d}</p>
              </li>
            ))}
          </ol>
        </section>

        <div className="grid gap-6 md:grid-cols-2">
          <section className="card rise p-6" style={{ '--i': 6 } as React.CSSProperties}>
            <h2 className="text-2xl font-semibold">Recent investigations</h2>
            {investigations.length === 0 ? (
              <EmptyState compact art={<AskIllustration />} title="No questions asked yet">Ask your first question and it will be saved here, so you can pick it up later.</EmptyState>
            ) : (
              <ul className="mt-3 divide-y divide-line">
                {investigations.slice(0, 6).map((i) => (
                  <li key={i.id}><button className="flex w-full items-center justify-between gap-3 rounded-lg py-3 text-left transition hover:text-brand" onClick={() => { void openInvestigation(i.id); nav('/investigate') }}>
                    <span className="truncate font-medium">{i.name}</span><span className="shrink-0 text-sm text-muted">{i.n_questions} q · {fmtWhen(i.updated_at)}</span></button></li>
                ))}
              </ul>
            )}
          </section>
          <section className="card rise p-6" style={{ '--i': 7 } as React.CSSProperties}>
            <h2 className="text-2xl font-semibold">Under the hood</h2>
            {!health ? <SkeletonLines lines={5} className="mt-4" /> : (
              <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-6 gap-y-2.5 text-sm">
                <dt className="text-muted">Answer engine</dt><dd>{health.llm.available ? <>Groq <code className="rounded bg-surface-2 px-1.5 py-0.5 text-xs">{health.llm.model}</code> <span className="text-muted">→ rule-based fallback</span></> : <span className="text-warn">Rule-based only - set GROQ_API_KEY to enable the LLM</span>}</dd>
                <dt className="text-muted">Database</dt><dd>{health.database.engine}{health.database.ok ? '' : ' (down)'}</dd>
                <dt className="text-muted">Vector store</dt><dd>{health.vector_store.mode === 'disabled' ? 'not used (keyword mode)' : `Qdrant · ${health.vector_store.mode}${health.vector_store.ok ? '' : ' (down)'}`}</dd>
                <dt className="text-muted">Models</dt><dd>{health.models.dense.ready ? 'embeddings ready' : health.models.dense.loading ? 'loading…' : 'keyword search (embeddings off)'}{health.models.reranker.ready ? ' · reranker' : ''}</dd>
                <dt className="text-muted">OCR</dt><dd>{health.ocr.available ? 'RapidOCR available' : 'unavailable'}</dd>
              </dl>
            )}
          </section>
        </div>

        <SiteFooter />
      </div>
    </div>
  )
}
