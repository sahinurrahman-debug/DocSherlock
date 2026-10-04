import { useEffect, useMemo, useState } from 'react'
import { useWorkspace } from '../context/workspace'
import { api, ApiError } from '../lib/api'
import { layoutBoard, lit, type Focus } from '../lib/boardLayout'
import type { BoardData, BoardDispute } from '../lib/types'
import { EmptyState } from './EmptyState'
import { BalanceIllustration, PapersIllustration } from './illustrations'
import { RichText } from './RichText'
import { Skeleton } from './Skeleton'

const clip = (s: string, n: number) => (s.length > n ? s.slice(0, n - 1).trimEnd() + '…' : s)
const docLabel = (name: string) => clip(name.replace(/\.[^.]+$/, '').replace(/_/g, ' '), 30)
const SEV_FILL = { high: 'var(--color-bad)', medium: 'var(--color-warn)', low: 'var(--color-none)' } as const

const CORK: React.CSSProperties = {
  backgroundColor: 'color-mix(in srgb, var(--color-lamp) 13%, var(--color-surface-2))',
  backgroundImage: 'radial-gradient(color-mix(in srgb, var(--color-ink) 14%, transparent) 1px, transparent 1.5px)',
  backgroundSize: '14px 14px',
}

export function BoardView({ focusCluster, onAsk }: { focusCluster?: string | null; onAsk: (q: string) => void }) {
  const { scopeIds, documents, readyDocs, openSource, loadDemo } = useWorkspace()
  const [data, setData] = useState<BoardData | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [focus, setFocus] = useState<Focus>(null)
  const [zoom, setZoom] = useState<'fit' | 'full'>('fit')
  const key = JSON.stringify(scopeIds) + documents.map((d) => `${d.id}${d.status}${d.doc_date ?? ''}`).join()

  useEffect(() => {
    let alive = true
    if (!readyDocs.length) { setData(null); return }
    api.board(scopeIds ?? undefined).then((d) => { if (alive) { setData(d); setErr(null) } }).catch((e: unknown) => alive && setErr(e instanceof ApiError ? e.message : 'Could not build the board'))
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])
  useEffect(() => { if (focusCluster) setFocus({ kind: 'dispute', id: focusCluster }) }, [focusCluster])

  const layout = useMemo(() => (data ? layoutBoard(data) : null), [data])
  const on = useMemo(() => (layout ? lit(layout, focus) : null), [layout, focus])
  const selected: BoardDispute | undefined = data?.disputes.find((d) => (focus?.kind === 'dispute' ? d.id === focus.id : focus?.kind === 'note' ? d.id === focus.id.split(':')[0] : false))

  if (!readyDocs.length) {
    return <div className="mx-auto max-w-5xl px-4 py-8 sm:px-6"><div className="card"><EmptyState art={<PapersIllustration />} title="The board is empty" actions={<button className="btn btn-primary" onClick={() => void loadDemo()}>Load the sample set</button>}>Pin some documents and DocSherlock will string together every claim they disagree about.</EmptyState></div></div>
  }
  const dim = (id: boolean) => (on ? (id ? 1 : 0.16) : 1)
  const openFirst = (d: BoardDispute, i: number) => { const s = d.positions[i].sources[0]; if (s) openSource({ docId: s.doc_id, docName: s.doc_name, page: s.page ?? 1, start: s.start, end: s.end, quote: s.quote }) }
  const press = (fn: () => void) => ({ role: 'button', tabIndex: 0, onKeyDown: (e: React.KeyboardEvent) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fn() } }, onClick: fn, className: 'cursor-pointer outline-none focus-visible:[&>rect]:stroke-[var(--color-brand)]' })

  return (
    <div className="mx-auto max-w-6xl space-y-5 px-4 py-6 sm:px-6">
      <header>
        <h2 className="text-3xl font-semibold">Case board</h2>
        <p className="mt-2 max-w-3xl text-base leading-relaxed text-muted">Documents on the left, the claims they disagree about on the right. <span className="font-medium text-bad">Red string</span> joins claims that conflict; <span className="font-medium text-lamp">amber</span> shows which document amends which. Click anything to follow its strings.</p>
        <div className="mt-3 flex flex-wrap gap-4 text-sm text-muted" role="group" aria-label="Legend">
          <span className="inline-flex items-center gap-2"><svg width="30" height="8" aria-hidden="true"><path d="M0 4h30" stroke="var(--color-bad)" strokeWidth="3" strokeLinecap="round" /></svg>conflicts with</span>
          <span className="inline-flex items-center gap-2"><svg width="30" height="8" aria-hidden="true"><path d="M0 4h30" stroke="var(--color-lamp)" strokeWidth="3" strokeDasharray="5 4" strokeLinecap="round" /></svg>amends / newer than</span>
          <span className="inline-flex items-center gap-2"><svg width="30" height="8" aria-hidden="true"><path d="M0 4h30" stroke="var(--color-muted)" strokeWidth="2" opacity=".6" /></svg>states</span>
          <span className="inline-flex items-center gap-2"><span className="h-3 w-3 rounded-full" style={{ background: 'var(--color-ok)' }} />likely current</span>
        </div>
      </header>

      {err && <p className="text-sm text-bad">{err}</p>}
      {!data && !err && <Skeleton className="h-96" />}
      {data && data.disputes.length === 0 && <div className="card"><EmptyState art={<BalanceIllustration />} title="Nothing to string together">The documents don&apos;t disagree, so there are no red strings to draw.</EmptyState></div>}

      {layout && data && data.disputes.length > 0 && (
        <>
          <div className="flex justify-end"><div className="inline-flex overflow-hidden rounded-lg border border-line text-sm" role="group" aria-label="Board zoom">
            {(['fit', 'full'] as const).map((z) => <button key={z} aria-pressed={zoom === z} onClick={() => setZoom(z)} className={`px-3 py-1.5 transition ${zoom === z ? 'bg-brand text-brand-ink' : 'bg-surface hover:bg-surface-2'}`}>{z === 'fit' ? 'Fit to width' : 'Actual size'}</button>)}
          </div></div>
          <div className="scroll-thin max-h-[78vh] overflow-auto rounded-2xl border border-line shadow-[var(--shadow-card)]" style={CORK}>
            <svg viewBox={`0 0 ${layout.width} ${layout.height}`} style={zoom === 'fit' ? { width: '100%', height: 'auto', minWidth: Math.round(layout.width * 0.62) } : { width: layout.width, height: layout.height }} className="mx-auto block max-w-none" role="group" aria-label={`Case board: ${data.stats.disputes} disputed points across ${data.stats.documents} documents`}
              onClick={(e) => { if (e.target === e.currentTarget) setFocus(null) }}>
              <defs>
                <marker id="arrow-amber" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" fill="var(--color-lamp)" /></marker>
                <filter id="note-shadow" x="-10%" y="-10%" width="120%" height="130%"><feDropShadow dx="0" dy="2" stdDeviation="2.5" floodOpacity=".22" /></filter>
              </defs>

              {layout.groups.map((g) => (
                <g key={g.dispute.id} opacity={dim(!!on?.disputes.has(g.dispute.id))} style={{ transition: 'opacity .25s' }}>
                  <rect x={g.x} y={g.y} width={g.w} height={g.h} rx="14" fill="var(--color-surface)" fillOpacity=".55" stroke="var(--color-line)" />
                  <g {...press(() => setFocus(focus?.kind === 'dispute' && focus.id === g.dispute.id ? null : { kind: 'dispute', id: g.dispute.id }))} aria-label={`Dispute: ${g.dispute.title}`}>
                    <circle cx={g.x + 20} cy={g.y + 22} r="6" fill={SEV_FILL[g.dispute.severity]} />
                    <text x={g.x + 34} y={g.y + 27} fontSize="15" fontWeight="600" fill="var(--color-ink)">{clip(g.dispute.title, 52)}</text>
                  </g>
                </g>
              ))}

              {layout.strings.map((s) => {
                const hot = !!on?.strings.has(s.id)
                const base = s.kind === 'conflicts' ? { stroke: 'var(--color-bad)', w: 3.2, dash: undefined, o: 0.9 } : s.kind === 'amends' ? { stroke: 'var(--color-lamp)', w: 3, dash: '7 6', o: 0.95 } : { stroke: hot ? 'var(--color-brand)' : 'var(--color-muted)', w: hot ? 2.6 : 1.8, dash: undefined, o: on ? 1 : 0.5 }
                return (
                  <g key={s.id} opacity={on ? (hot ? 1 : 0.1) : base.o} style={{ transition: 'opacity .25s' }}>
                    <path d={s.d} fill="none" stroke={base.stroke} strokeWidth={base.w} strokeDasharray={base.dash} strokeLinecap="round" markerEnd={s.kind === 'amends' ? 'url(#arrow-amber)' : undefined} />
                    {s.kind === 'conflicts' && <g transform={`translate(${s.mid[0]} ${s.mid[1]})`}><circle r="11" fill="var(--color-surface)" stroke="var(--color-bad)" strokeWidth="2.2" /><text textAnchor="middle" y="5" fontSize="14" fontWeight="700" fill="var(--color-bad)">≠</text></g>}
                    {s.kind === 'amends' && s.label && <text x={s.mid[0] - 6} y={s.mid[1]} textAnchor="end" fontSize="12" fontWeight="600" fill="var(--color-lamp)" transform={`rotate(-90 ${s.mid[0] - 6} ${s.mid[1]})`}>{s.label}</text>}
                  </g>
                )
              })}

              {layout.docs.map((d) => (
                <g key={d.id} opacity={dim(!!on?.docs.has(d.id))} style={{ transition: 'opacity .25s' }} {...press(() => setFocus(focus?.kind === 'doc' && focus.id === d.id ? null : { kind: 'doc', id: d.id }))} aria-label={`Document ${d.name}`}>
                  <rect x={d.x} y={d.y} width={d.w} height={d.h} rx="12" fill="var(--color-surface)" stroke={focus?.kind === 'doc' && focus.id === d.id ? 'var(--color-brand)' : 'var(--color-line)'} strokeWidth={focus?.kind === 'doc' && focus.id === d.id ? 2.5 : 1.5} filter="url(#note-shadow)" strokeDasharray={d.connected ? undefined : '5 4'} />
                  <text x={d.x + 16} y={d.y + 28} fontSize="15" fontWeight="600" fill="var(--color-ink)">{docLabel(d.name)}</text>
                  <text x={d.x + 16} y={d.y + 49} fontSize="13" fill="var(--color-muted)">{d.doc_date ?? 'undated'}{d.connected ? '' : ' · no disputes'}</text>
                  <circle cx={d.x + d.w} cy={d.y + d.h / 2} r="6" fill={d.connected ? 'var(--color-brand)' : 'var(--color-line)'} stroke="var(--color-surface)" strokeWidth="2" />
                </g>
              ))}

              {layout.groups.flatMap((g) => g.notes.map((n) => (
                <g key={n.key} opacity={dim(!!on?.notes.has(n.key))} style={{ transition: 'opacity .25s' }} transform={`rotate(${n.tilt} ${n.x + n.w / 2} ${n.y + n.h / 2})`}
                  {...press(() => { setFocus({ kind: 'note', id: n.key }); openFirst(g.dispute, n.index) })} aria-label={`Claim: ${n.value}, stated by ${n.docNames.join(', ')}${n.current ? ', likely current' : ''}`}>
                  <rect x={n.x} y={n.y} width={n.w} height={n.h} rx="10" fill="var(--color-surface)" stroke={n.current ? 'var(--color-ok)' : 'var(--color-line)'} strokeWidth={n.current ? 2.4 : 1.5} filter="url(#note-shadow)" />
                  <text x={n.x + 36} y={n.y + 28} fontSize="19" fontWeight="600" className="font-display" fill="var(--color-ink)">{clip(n.value, n.current || n.corroborated ? 16 : 30)}</text>
                  <text x={n.x + 36} y={n.y + 49} fontSize="13" fill="var(--color-muted)">{clip(n.docNames.map((x) => docLabel(x)).join(' · '), 44)}</text>
                  <circle cx={n.x + 16} cy={n.y + n.h / 2} r="6.5" fill={n.current ? 'var(--color-ok)' : 'var(--color-bad)'} stroke="var(--color-surface)" strokeWidth="2" />
                  {(n.current || n.corroborated) && <text x={n.x + n.w - 12} y={n.y + 22} textAnchor="end" fontSize="12" fontWeight="700" fill="var(--color-ok)">{[n.current ? 'LIKELY CURRENT' : '', n.corroborated ? `✓ ${n.docNames.length} DOCS` : ''].filter(Boolean).join(' · ')}</text>}
                </g>
              )))}
            </svg>
          </div>
          {data.stats.shown_of > data.stats.disputes && <p className="text-sm text-muted">Showing the {data.stats.disputes} highest-priority of {data.stats.shown_of} disputed points - the Conflicts tab has the rest.</p>}

          {selected ? (
            <section className="card pop space-y-3 p-5" aria-label="Selected dispute" data-testid="board-detail">
              <div className="flex flex-wrap items-center gap-2"><span className="chip">{selected.severity} priority</span>{selected.basis && <span className="chip !bg-brand-soft !text-brand">likely current by {selected.basis === 'amendment' ? 'amendment wording' : 'recency'}</span>}</div>
              <h3 className="font-display text-xl font-semibold">{selected.title}</h3>
              <div className="grid gap-3 md:grid-cols-2">
                {selected.positions.map((p) => (
                  <div key={p.index} className={`rounded-xl border p-3.5 ${p.current ? 'border-ok/60 bg-ok-soft/40' : 'border-line bg-surface-2/50'}`}>
                    <div className="font-display text-lg font-semibold">{p.value}{p.current ? <span className="ml-2 text-sm font-semibold text-ok">likely current</span> : null}</div>
                    {p.sources.slice(0, 3).map((s, i) => (
                      <button key={i} className="mt-1.5 block w-full text-left text-sm text-muted hover:text-ink" onClick={() => openSource({ docId: s.doc_id, docName: s.doc_name, page: s.page ?? 1, start: s.start, end: s.end, quote: s.quote })}>
                        <span className="font-semibold text-ink">{s.doc_name}</span>{s.doc_date ? ` · ${s.doc_date}` : ''}<span className="block">“{clip(s.quote, 130)}”</span>
                      </button>
                    ))}
                  </div>
                ))}
              </div>
              <div className="text-sm text-muted"><RichText text={selected.resolution} /></div>
              <div className="flex flex-wrap gap-2"><button className="btn btn-sm" onClick={() => onAsk(`Which applies: ${selected.positions.map((p) => p.value).join(' or ')}? (${selected.title.replace(/___/g, '...')})`)}>Ask about this</button><button className="btn btn-sm btn-ghost" onClick={() => setFocus(null)}>Clear selection</button></div>
            </section>
          ) : <p className="text-sm text-muted">Tip: click a document to follow its strings, or a claim to see its sources side by side.</p>}
        </>
      )}
    </div>
  )
}

