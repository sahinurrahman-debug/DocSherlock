import { useEffect, useMemo, useState } from 'react'
import { EmptyState } from '../components/EmptyState'
import { Skeleton } from '../components/Skeleton'
import { useWorkspace } from '../context/workspace'
import { api, ApiError } from '../lib/api'
import type { TrustCase, TrustReport, TrustResult } from '../lib/types'

const CATEGORY_NOTE: Record<string, string> = {
  Honesty: 'Says "not found" and shows disagreement instead of guessing',
  Safety: 'Cannot be talked, tricked or lied into a wrong answer',
  Integrity: 'Every quote can be checked against the original',
  Robustness: 'Bad input is refused or reported - never a crash',
  Privacy: 'One visitor never sees another\'s documents',
}

function Ring({ passed, total, running }: { passed: number; total: number; running: boolean }) {
  const r = 52, c = 2 * Math.PI * r
  const frac = total ? passed / total : 0
  const ok = total > 0 && passed === total
  return (
    <svg viewBox="0 0 128 128" className="h-32 w-32 shrink-0" role="img" aria-label={total ? `${passed} of ${total} checks passed` : 'No results yet'}>
      <circle cx="64" cy="64" r={r} fill="none" stroke="var(--color-line)" strokeWidth="10" />
      <circle cx="64" cy="64" r={r} fill="none" stroke={ok ? 'var(--color-ok)' : 'var(--color-bad)'} strokeWidth="10" strokeLinecap="round" strokeDasharray={c} strokeDashoffset={c * (1 - frac)} transform="rotate(-90 64 64)" style={{ transition: 'stroke-dashoffset .9s cubic-bezier(.22,1,.36,1)' }} className={running ? 'opacity-40' : ''} />
      <text x="64" y="62" textAnchor="middle" className="font-display" fontSize="30" fontWeight="600" fill="var(--color-ink)">{total ? `${passed}/${total}` : '—'}</text>
      <text x="64" y="84" textAnchor="middle" fontSize="12" fill="var(--color-muted)">{total ? 'passed' : 'not run'}</text>
    </svg>
  )
}

function Row({ c, result, i }: { c: TrustCase; result?: TrustResult; i: number }) {
  const state = result ? result.status : 'idle'
  const icon = state === 'pass' ? 'M5 12l5 5 9-10' : state === 'fail' ? 'M6 6l12 12M18 6L6 18' : 'M6 12h12'
  const tone = state === 'pass' ? 'bg-ok-soft text-ok' : state === 'fail' ? 'bg-bad-soft text-bad' : 'bg-none-soft text-none'
  return (
    <li className="rise rounded-xl border border-line bg-surface p-4" style={{ '--i': i } as React.CSSProperties} data-testid="trust-case" data-status={state}>
      <div className="flex items-start gap-3">
        <span className={`mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${tone}`}>
          <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={icon} /></svg>
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline justify-between gap-x-3">
            <h4 className="font-medium">{c.title}</h4>
            {result && <span className="text-xs tabular-nums text-muted">{result.ms} ms</span>}
          </div>
          <p className="text-sm text-muted">{c.what}</p>
          {result ? <p className={`mt-2 rounded-lg px-3 py-2 text-sm leading-relaxed ${state === 'pass' ? 'bg-surface-2' : 'bg-bad-soft text-ink'}`}><span className="sr-only">{state === 'pass' ? 'Passed. ' : 'Failed. '}</span>{result.detail}</p> : <p className="mt-2 text-sm text-muted">Not run yet</p>}
        </div>
      </div>
    </li>
  )
}

export default function TrustLab() {
  const { toast } = useWorkspace()
  const [cases, setCases] = useState<TrustCase[]>([])
  const [report, setReport] = useState<TrustReport | null>(null)
  const [running, setRunning] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let alive = true
    api.trustlab.overview().then((o) => { if (alive) { setCases(o.cases); setReport(o.last) } }).catch((e: unknown) => alive && setErr(e instanceof ApiError ? e.message : 'Could not reach the server')).finally(() => alive && setLoading(false))
    return () => { alive = false }
  }, [])

  const run = async () => {
    setRunning(true); setErr(null)
    try { const r = await api.trustlab.run(); setReport(r); toast(r.failed ? `${r.failed} check${r.failed === 1 ? '' : 's'} failed` : `All ${r.total} checks passed`) }
    catch (e) { setErr(e instanceof ApiError ? e.message : 'The stress test could not run') }
    finally { setRunning(false) }
  }

  const byId = useMemo(() => new Map((report?.cases ?? []).map((r) => [r.id, r])), [report])
  const groups = useMemo(() => {
    const m = new Map<string, TrustCase[]>()
    for (const c of cases) m.set(c.category, [...(m.get(c.category) ?? []), c])
    return [...m.entries()]
  }, [cases])

  return (
    <div className="scroll-thin min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-4xl space-y-6 px-4 py-6 sm:px-6 sm:py-8">
        <header className="card rise flex flex-wrap items-center gap-6 p-6 sm:p-8">
          <Ring passed={report?.passed ?? 0} total={report?.total ?? 0} running={running} />
          <div className="min-w-0 flex-1" style={{ minWidth: 240 }}>
            <h1 className="text-3xl font-semibold sm:text-4xl">Trust Lab</h1>
            <p className="mt-2 text-base leading-relaxed text-muted">Don&apos;t take our word for it. This attacks DocSherlock live, on this server: contradicting documents, a hidden instruction, a model that invents quotes, corrupt files, a second visitor. Every case runs through the real pipeline.</p>
            <div className="mt-4 flex flex-wrap items-center gap-3">
              <button className="btn btn-primary !px-6 !py-2.5 text-base" onClick={() => void run()} disabled={running || loading}>{running ? 'Attacking…' : report ? 'Run it again' : 'Run the stress test'}</button>
              {report && !running && <span className="text-sm text-muted">{report.passed} of {report.total} passed in {report.duration_ms < 1000 ? `${report.duration_ms} ms` : `${(report.duration_ms / 1000).toFixed(1)} s`}</span>}
            </div>
          </div>
        </header>

        {err && <p role="alert" className="rounded-xl bg-bad-soft px-4 py-3 text-sm text-ink">{err}</p>}
        <p className="text-sm text-muted">No API key needed and nothing of yours is touched: it runs in a throwaway workspace that is deleted afterwards. The language model is swapped for a scripted one that misbehaves on purpose.</p>

        {loading && <div className="space-y-3" role="status" aria-label="Loading"><Skeleton className="h-24" /><Skeleton className="h-24" /><Skeleton className="h-24" /></div>}
        {!loading && cases.length === 0 && !err && <div className="card"><EmptyState title="No checks are defined">The server returned an empty list.</EmptyState></div>}
        {running && !report && <div className="space-y-3" role="status" aria-label="Running"><Skeleton className="h-24" /><Skeleton className="h-24" /></div>}

        {groups.map(([cat, list]) => (
          <section key={cat} aria-label={cat}>
            <div className="mb-2 flex flex-wrap items-baseline gap-x-3">
              <h2 className="font-display text-2xl font-semibold">{cat}</h2>
              <span className="text-sm text-muted">{CATEGORY_NOTE[cat] ?? ''}</span>
            </div>
            <ul className="space-y-3">{list.map((c, i) => <Row key={c.id + (report?.started_at ?? '')} c={c} result={byId.get(c.id)} i={i} />)}</ul>
          </section>
        ))}
      </div>
    </div>
  )
}
