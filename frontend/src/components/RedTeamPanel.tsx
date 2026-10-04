import { useWorkspace } from '../context/workspace'
import type { EvidenceRef, RedTeamCheck, RedTeamResult } from '../lib/types'

const VERDICT = {
  survived: { label: 'Survived', tone: 'bg-ok-soft text-ok', ring: 'border-ok/50', icon: 'M5 12l5 5 9-10' },
  weakened: { label: 'Weakened', tone: 'bg-warn-soft text-warn', ring: 'border-warn/50', icon: 'M12 3l9 16H3L12 3zM12 10v4M12 17h.01' },
  refuted: { label: 'Refuted', tone: 'bg-bad-soft text-bad', ring: 'border-bad/50', icon: 'M6 6l12 12M18 6L6 18' },
} as const

const STATUS = {
  passed: { icon: 'M5 12l5 5 9-10', cls: 'bg-ok-soft text-ok', word: 'Held' },
  failed: { icon: 'M6 6l12 12M18 6L6 18', cls: 'bg-bad-soft text-bad', word: 'Broke' },
  skipped: { icon: 'M6 12h12', cls: 'bg-none-soft text-none', word: 'Skipped' },
} as const
const SEV_CLS = { critical: 'bg-bad-soft text-bad', major: 'bg-warn-soft text-warn', minor: 'bg-none-soft text-none' } as const

function Svg({ d, className = '' }: { d: string; className?: string }) {
  return <svg viewBox="0 0 24 24" className={`h-4 w-4 shrink-0 ${className}`} fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={d} /></svg>
}

function Check({ c, i }: { c: RedTeamCheck; i: number }) {
  const { openSource } = useWorkspace()
  const st = STATUS[c.status]
  const open = (e: EvidenceRef) => openSource({ docId: e.doc_id, docName: e.doc_name, page: e.page ?? 1, start: e.start, end: e.end, quote: e.quote })
  return (
    <li className="rise rounded-xl border border-line bg-surface p-3.5" style={{ '--i': i } as React.CSSProperties} data-testid="rt-check" data-status={c.status}>
      <div className="flex flex-wrap items-center gap-2">
        <span className={`inline-flex h-6 w-6 items-center justify-center rounded-full ${st.cls}`} title={st.word}><Svg d={st.icon} className="!h-3.5 !w-3.5" /></span>
        <span className="font-medium">{c.label}</span>
        {c.severity && <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${SEV_CLS[c.severity]}`}>{c.severity}</span>}
        <span className="sr-only">{st.word}</span>
      </div>
      <p className="mt-1.5 text-sm leading-relaxed text-muted">{c.detail}</p>
      {c.evidence.length > 0 && (
        <div className="mt-2 grid gap-2 md:grid-cols-2">
          {c.evidence.map((e, k) => (
            <button key={k} type="button" onClick={() => open(e)} className="rounded-lg bg-surface-2/70 px-3 py-2 text-left text-sm transition hover:bg-surface-2">
              <span className="block text-xs text-muted"><span className="font-semibold text-ink">{e.doc_name}</span>{e.doc_date ? ` · ${e.doc_date}` : ''}{e.page ? ` · p.${e.page}` : ''}</span>
              <span className="mt-0.5 block border-l-[3px] border-lamp/60 pl-2.5">“{e.quote.length > 150 ? e.quote.slice(0, 149) + '…' : e.quote}”</span>
            </button>
          ))}
        </div>
      )}
    </li>
  )
}

/** The verdict of an adversarial second pass over one answer, with every attack that was tried. */
export function RedTeamPanel({ r }: { r: RedTeamResult }) {
  const v = VERDICT[r.verdict]
  return (
    <section className={`fade rounded-2xl border-2 ${v.ring} bg-surface-2/40 p-4`} aria-label="Red-team result" data-testid="redteam" data-verdict={r.verdict}>
      <div className="flex flex-wrap items-center gap-3">
        <span className={`inline-flex items-center gap-2 rounded-full px-3.5 py-1.5 font-display text-lg font-semibold ${v.tone}`}><Svg d={v.icon} className="!h-5 !w-5" />{v.label}</span>
        <p className="min-w-0 flex-1 text-base font-medium">{r.headline}</p>
      </div>
      <p className="mt-1.5 text-sm text-muted">{r.attacks_run} attack{r.attacks_run === 1 ? '' : 's'} tried{r.adversary === 'llm' ? ', including an adversarial language model whose objections count only when quoted verbatim' : ' (deterministic checks; no model involved)'}.</p>
      <ul className="mt-3 space-y-2.5">{r.checks.map((c, i) => <Check key={c.id} c={c} i={i} />)}</ul>
    </section>
  )
}
