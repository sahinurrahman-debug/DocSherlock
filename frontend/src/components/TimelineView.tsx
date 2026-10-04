import { useEffect, useMemo, useRef, useState } from 'react'
import { useWorkspace } from '../context/workspace'
import { api, ApiError } from '../lib/api'
import type { TimelineData, TopicSnapshot, TopicStatus } from '../lib/types'
import { EmptyState } from './EmptyState'
import { PapersIllustration } from './illustrations'
import { Skeleton, SkeletonCard } from './Skeleton'

const DAY = 86_400_000
const toMs = (d: string) => Date.parse(d + 'T00:00:00Z')
const fromMs = (ms: number) => new Date(ms).toISOString().slice(0, 10)
const addDays = (d: string, n: number) => fromMs(toMs(d) + n * DAY)
export const fmtDay = (d: string) => new Date(toMs(d)).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })

const STATUS: Record<TopicStatus, { label: string; chip: string }> = {
  settled: { label: 'In force', chip: 'bg-ok-soft text-ok' },
  likely: { label: 'Likely in force', chip: 'bg-brand-soft text-brand' },
  disputed: { label: 'Disputed', chip: 'bg-bad-soft text-bad' },
  not_yet: { label: 'Not yet documented', chip: 'bg-none-soft text-none' },
}
const SEV = { high: 0, medium: 1, low: 2 } as const

function TopicCard({ t, changed, i }: { t: TopicSnapshot; changed: boolean; i: number }) {
  const { openSource } = useWorkspace()
  const st = STATUS[t.status]
  const src = t.source
  return (
    <article className={`card p-5 ${changed ? 'pop ring-2 ring-brand/40' : 'rise'}`} style={{ '--i': Math.min(i, 8) } as React.CSSProperties} data-testid="topic" data-status={t.status} data-changed={changed}>
      <div className="flex flex-wrap items-center gap-2">
        <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${st.chip}`}>{st.label}</span>
        {changed && <span className="rounded-full bg-lamp/20 px-2.5 py-1 text-xs font-semibold text-ink">changed</span>}
      </div>
      <h3 className="mt-2 text-base font-medium leading-snug text-muted">{t.title}</h3>
      <div className={`mt-1 font-display text-2xl font-semibold leading-tight ${t.value ? '' : 'text-muted'}`}>{t.value ?? 'No document says yet'}</div>
      {t.status === 'disputed' && t.alternatives && <div className="mt-1 text-base">Documents give: {t.alternatives.map((a) => <span key={a} className="mr-2 rounded-lg bg-surface-2 px-2 py-0.5 font-medium">{a}</span>)}</div>}
      {src && (
        <p className="mt-2 text-sm text-muted">
          {t.basis && <span className="mr-2 rounded-full border border-line px-2 py-0.5 text-xs">{t.basis}</span>}
          per <button className="font-semibold text-ink underline-offset-4 hover:text-brand hover:underline" onClick={() => openSource({ docId: src.doc_id, docName: src.doc_name, page: src.page ?? 1, start: src.start, end: src.end, quote: src.quote })}>{src.doc_name}</button>
          {src.doc_date ? ` (${fmtDay(src.doc_date)})` : ''}
        </p>
      )}
      {t.note && <p className="mt-3 rounded-xl bg-warn-soft px-3.5 py-2.5 text-sm text-ink">{t.note}</p>}
      {t.upcoming.length > 0 && (
        <p className="mt-3 flex flex-wrap items-center gap-2 text-sm text-muted">
          <span className="eyebrow">Still to come</span>
          {t.upcoming.map((u) => <span key={u.doc_id + u.value} className="rounded-full border border-dashed border-line px-2.5 py-0.5">{u.value} from {fmtDay(u.date)}</span>)}
        </p>
      )}
    </article>
  )
}

export function TimelineView({ onAsk }: { onAsk: (q: string, asOf: string) => void }) {
  const { scopeIds, documents, readyDocs } = useWorkspace()
  const [base, setBase] = useState<TimelineData | null>(null)
  const [day, setDay] = useState<string | null>(null)
  const [snap, setSnap] = useState<TimelineData['as_of'] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [q, setQ] = useState('')
  const prev = useRef<Map<string, string>>(new Map())
  const [changed, setChanged] = useState<Set<string>>(new Set())
  const key = JSON.stringify(scopeIds) + documents.map((d) => `${d.id}${d.status}${d.doc_date ?? ''}`).join()

  useEffect(() => {
    let alive = true
    if (!readyDocs.length) { setBase(null); return }
    api.timeline(null, scopeIds ?? undefined).then((t) => {
      if (!alive) return
      setBase(t); setErr(null)
      setDay((d) => d ?? t.range.max)
    }).catch((e: unknown) => alive && setErr(e instanceof ApiError ? e.message : 'Could not load the timeline'))
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  useEffect(() => {
    if (!day || !base) return
    let alive = true
    const t = window.setTimeout(() => {
      api.timeline(day, scopeIds ?? undefined).then((r) => {
        if (!alive || !r.as_of) return
        const now = new Map(r.as_of.topics.map((x) => [x.cluster_id, `${x.status}|${x.value ?? ''}`]))
        const diff = new Set<string>()
        if (prev.current.size) now.forEach((v, id) => { if (prev.current.get(id) !== v) diff.add(id) })
        prev.current = now
        setChanged(diff); setSnap(r.as_of)
      }).catch((e: unknown) => alive && setErr(e instanceof ApiError ? e.message : 'Could not load that date'))
    }, 120)
    return () => { alive = false; window.clearTimeout(t) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [day, base])

  const dated = useMemo(() => (base?.documents ?? []).filter((d) => d.dated), [base])
  const minDay = base?.range.min ? addDays(base.range.min, -1) : null
  const stops = useMemo(() => [...new Set(dated.map((d) => d.key))].sort(), [dated])
  // one evenly spaced stop per distinct document date (the answer can only change at those dates), plus stop 0 = before any document
  const stopDocs = useMemo(() => stops.map((k) => dated.filter((d) => d.key === k)), [stops, dated])
  const total = stops.length
  const index = day ? stops.filter((k) => k <= day).length : total
  const topics = useMemo(() => [...(snap?.topics ?? [])].sort((a, b) => Number(changed.has(b.cluster_id)) - Number(changed.has(a.cluster_id)) || SEV[a.severity] - SEV[b.severity] || a.title.localeCompare(b.title)), [snap, changed])

  if (!readyDocs.length) {
    return <div className="mx-auto max-w-5xl px-4 py-8 sm:px-6"><div className="card"><EmptyState art={<PapersIllustration />} title="Time travel needs dated documents">Add documents with dates - contracts, amendments, policies - and you can slide back to see what each said at any point.</EmptyState></div></div>
  }
  if (base && dated.length === 0) {
    return <div className="mx-auto max-w-5xl px-4 py-8 sm:px-6"><div className="card"><EmptyState art={<PapersIllustration />} title="None of these documents has a date">Click a document&apos;s date chip to set one, and the timeline appears.</EmptyState></div></div>
  }

  const pct = (i: number) => (total ? (i / total) * 100 : 0)
  const goTo = (i: number) => minDay && setDay(i <= 0 ? minDay : stops[Math.min(i, total) - 1])
  const prevStop = day ? [...stops].reverse().find((s) => s < day) ?? minDay : null
  const nextStop = day ? stops.find((s) => s > day) ?? null : null
  const submit = () => { const v = q.trim(); if (v && day) { onAsk(v, day); setQ('') } }

  return (
    <div className="mx-auto max-w-5xl space-y-5 px-4 py-6 sm:px-6">
      <header>
        <h2 className="text-3xl font-semibold">Timeline</h2>
        <p className="mt-2 max-w-3xl text-base leading-relaxed text-muted">Slide to any date and see which value of each disputed point was in force <em>then</em>, using only the documents that existed by that date.</p>
      </header>

      {err && <p className="text-sm text-bad">{err}</p>}
      {!base || !day || !minDay ? <SkeletonCard /> : (
        <section className="card p-5 sm:p-6" aria-label="Date control">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <div className="eyebrow">As of</div>
              <div className="font-display text-4xl font-semibold leading-tight" data-testid="as-of-date">{fmtDay(day)}</div>
              {snap && <div className="mt-1 text-sm text-muted">{snap.documents_used} of {snap.documents_total} documents existed by then</div>}
            </div>
            <div className="flex flex-wrap gap-2">
              <button className="btn btn-sm" disabled={!prevStop || day <= minDay} onClick={() => prevStop && setDay(prevStop)}>‹ Previous change</button>
              <button className="btn btn-sm" disabled={!nextStop} onClick={() => nextStop && setDay(nextStop)}>Next change ›</button>
              <button className="btn btn-sm btn-ghost" disabled={day === base.range.max} onClick={() => setDay(base.range.max)}>Latest</button>
            </div>
          </div>

          <div className="scroll-thin mt-6 overflow-x-auto pb-2">
            <div className="relative mx-10 h-32" style={{ minWidth: Math.max(560, (total + 1) * 96) }}>
              <div className="absolute left-0 right-0 top-1/2 h-1 -translate-y-1/2 rounded-full bg-line" />
              <div className="absolute left-0 top-1/2 h-1 -translate-y-1/2 rounded-full bg-brand transition-[width] duration-300" style={{ width: `${pct(index)}%` }} />
              <span className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2 text-center" style={{ left: '0%' }}>
                <span className={`block h-3 w-3 rounded-full border-2 ${index >= 0 ? 'border-brand bg-brand' : ''}`} />
                <span className="absolute left-1/2 top-6 w-24 -translate-x-1/2 text-center text-xs leading-tight text-muted">before any document</span>
              </span>
              {stopDocs.map((docs, i) => {
                const known = i + 1 <= index
                const first = docs[0]
                const more = docs.length - 1
                return (
                  <button key={first.key} type="button" onClick={() => goTo(i + 1)} title={docs.map((d) => `${d.name} · ${d.doc_date}`).join(', ')} aria-label={`Jump to ${first.name}, ${first.doc_date}`}
                    className="group absolute top-1/2 -translate-x-1/2 -translate-y-1/2" style={{ left: `${pct(i + 1)}%` }}>
                    <span className={`block h-4 w-4 rounded-full border-2 transition duration-200 group-hover:scale-125 ${known ? 'border-brand bg-brand' : 'border-line bg-surface'} ${docs.some((d) => d.introduces.length) ? 'ring-4 ring-lamp/30' : ''}`} />
                    <span className={`absolute left-1/2 w-32 -translate-x-1/2 text-center text-xs leading-tight ${i % 2 ? 'top-7' : 'bottom-7'} ${known ? 'text-ink' : 'text-muted'}`}>
                      <span className="line-clamp-2 break-words">{first.name.replace(/\.[^.]+$/, '').replace(/_/g, ' ')}{more > 0 ? ` +${more}` : ''}</span>
                      <span className="block opacity-70">{fmtDay(first.key)}</span>
                    </span>
                  </button>
                )
              })}
              <input type="range" min={0} max={total} step={1} value={index} onChange={(e) => goTo(Number(e.target.value))}
                aria-label="Date" aria-valuetext={fmtDay(day)} className="absolute inset-x-0 top-1/2 h-12 w-full -translate-y-1/2 cursor-ew-resize opacity-0" />
              <div className="pointer-events-none absolute top-1/2 h-10 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-lamp shadow transition-[left] duration-300" style={{ left: `${pct(index)}%` }} />
            </div>
          </div>
          <p className="mt-1 text-xs text-muted">Each stop is a date on which a document appeared; a glowing ring marks one that changes values set by an earlier document. Undated files can&apos;t be placed on the timeline{base.undated.length ? ` (${base.undated.join(', ')})` : ''}.</p>
        </section>
      )}

      <section aria-label="In force on this date">
        <h3 className="font-display text-xl font-semibold">{snap ? `In force on ${fmtDay(snap.date)}` : 'In force'}</h3>
        {!snap && !err && <div className="mt-3 space-y-3"><Skeleton className="h-28" /><Skeleton className="h-28" /></div>}
        {snap && topics.length === 0 && <div className="card mt-3"><EmptyState compact title="No disputed points to track">The documents don&apos;t disagree, so nothing changes over time.</EmptyState></div>}
        <div className="mt-3 grid gap-4 md:grid-cols-2">
          {topics.map((t, i) => <TopicCard key={t.cluster_id} t={t} i={i} changed={changed.has(t.cluster_id)} />)}
        </div>
      </section>

      {snap && snap.excluded.length > 0 && (
        <section className="card p-5" aria-label="Documents left out">
          <h3 className="font-display text-lg font-semibold">Not part of this date</h3>
          <div className="mt-2 flex flex-wrap gap-2">
            {snap.excluded.map((e) => <span key={e.doc_id} className="chip" title={e.reason === 'later' ? `written ${e.doc_date}` : 'no date'}>{e.name} <span className="ml-1.5 opacity-70">{e.reason === 'later' ? `· ${e.doc_date}` : '· undated'}</span></span>)}
          </div>
        </section>
      )}

      {snap && (
        <form className="card flex flex-wrap items-center gap-3 p-4" onSubmit={(e) => { e.preventDefault(); submit() }}>
          <label className="sr-only" htmlFor="as-of-question">Ask a question as of {snap.date}</label>
          <input id="as-of-question" className="field min-w-[200px] flex-1" value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Ask as of ${fmtDay(snap.date)} - e.g. "What are the payment terms?"`} />
          <button type="submit" className="btn btn-primary" disabled={!q.trim()}>Ask as of this date</button>
        </form>
      )}
    </div>
  )
}
