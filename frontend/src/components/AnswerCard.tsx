import { useState } from 'react'
import { useWorkspace } from '../context/workspace'
import { LEVELS, TONE_CLASS } from '../lib/format'
import type { Answer } from '../lib/types'
import { CitationCard } from './CitationCard'
import { ComparisonView } from './ComparePanel'
import { ConfidenceBadge, WhyPanel } from './ConfidenceBadge'
import { ConflictAlert } from './ConflictAlert'
import { EvidenceMatrix } from './EvidenceMatrix'
import { RichText } from './RichText'

const BANNER: Record<string, { icon: string; text: string }> = {
  answered: { icon: '✓', text: 'Answered from the documents' },
  partial: { icon: '◐', text: 'Partial answer - read the notes' },
  conflict: { icon: '⚠', text: 'Sources conflict - no single answer' },
  insufficient: { icon: '?', text: 'Not found in the documents' },
}

function EngineTag({ a }: { a: Answer }) {
  const e = a.engine
  if (e.name === 'rules') {
    return <span className={`chip ${e.fallback ? '!bg-warn-soft !text-warn' : ''}`} title={e.reason ?? 'Deterministic rule-based engine'}>{e.fallback ? 'rules (LLM fallback)' : 'rule-based'}</span>
  }
  return <span className="chip !bg-brand-soft !text-brand" title={`Answered by ${e.model} on Groq${e.strict_schema ? ' with strict JSON-schema output' : ''}. Every quote was verified against the source text.`}>{e.model.split('/').pop()} · quotes verified</span>
}

export function AnswerCard({ a, showActions = true }: { a: Answer; showActions?: boolean }) {
  const { openSource, setPinned, setNote } = useWorkspace()
  const [trace, setTrace] = useState(false)
  const [noting, setNoting] = useState(false)
  const tone = LEVELS[a.level].tone
  const b = BANNER[a.status] ?? BANNER.answered
  const onCite = (id: string) => {
    const c = a.citations.find((x) => x.id === id)
    if (c) openSource({ docId: c.doc_id, docName: c.doc_name, page: c.page ?? 1, start: c.start, end: c.end, quote: c.quote })
  }
  const supporting = a.citations.filter((c) => c.role !== 'lead')
  const leads = a.citations.filter((c) => c.role === 'lead')

  return (
    <article className="card overflow-hidden" data-testid="answer-card" data-status={a.status} data-level={a.level}>
      <div className={`flex flex-wrap items-center gap-2 px-5 py-3 text-sm font-semibold ${TONE_CLASS[tone]}`}>
        <span aria-hidden>{b.icon}</span><span>{b.text}</span>
        <span className="ml-auto flex flex-wrap items-center gap-1.5"><EngineTag a={a} /><ConfidenceBadge level={a.level} /></span>
      </div>

      <div className="space-y-5 px-5 py-5">
        {a.headline && a.status !== 'insufficient' && <h2 className="font-display text-2xl font-semibold leading-snug tracking-tight sm:text-3xl">{a.headline}</h2>}
        {!a.comparison && <RichText text={a.status === 'conflict' && a.conflicts.length ? (a.answer.split('\n')[0] ?? a.answer) : a.answer} onCite={onCite} />}
        {a.conflicts.map((c) => <ConflictAlert key={c.id} cluster={c} />)}
        {a.comparison && <ComparisonView result={a.comparison} />}
        <EvidenceMatrix rows={a.evidence_matrix} citations={a.citations} />
        {a.missing_terms.length > 0 && a.status === 'insufficient' && <p className="text-sm text-muted">Terms that appear in none of your documents: <b>{a.missing_terms.join(', ')}</b></p>}
        {a.caveats.length > 0 && (
          <ul className="space-y-1.5 rounded-xl bg-warn-soft px-4 py-3 text-sm text-ink">{a.caveats.map((c, i) => <li key={i} className="flex gap-2"><span className="text-warn">⚠</span><span>{c}</span></li>)}</ul>
        )}
        <WhyPanel level={a.level} reasons={a.confidence.reasons} />
      </div>

      {a.citations.length > 0 && (
        <div className="border-t border-line px-5 py-4">
          <div className="eyebrow mb-2">Sources {supporting.length ? `(${supporting.length})` : ''}</div>
          {supporting.map((c) => <CitationCard key={c.id} c={c} />)}
          {leads.length > 0 && <div className="eyebrow mb-1 mt-2">Closest passages - shown for orientation only</div>}
          {leads.map((c) => <CitationCard key={c.id} c={c} />)}
        </div>
      )}

      {trace && (
        <div className="border-t border-line bg-surface-2 px-4 py-3 text-xs">
          <div className="mb-1">Question type <b>{a.trace.question_type ?? a.trace.intent ?? '—'}</b> · key terms <b>{(a.trace.query_terms ?? []).join(', ') || '—'}</b> · channels <b>{(a.trace.channels ?? []).join(' + ') || '—'}</b>
            {a.effective_question !== a.question && <> · interpreted as “{a.effective_question}”</>}</div>
          <div className="mb-2 text-muted">{a.engine.tokens ? `LLM ${a.engine.tokens.prompt}+${a.engine.tokens.completion} tokens in ${a.engine.tokens.latency_ms} ms · ` : ''}retrieve {a.timings_ms.retrieve ?? '—'} ms · total {a.timings_ms.total ?? '—'} ms · scope {a.trace.scope_documents ?? '—'} docs / {a.trace.scope_chunks ?? '—'} passages</div>
          <table className="w-full"><thead><tr className="text-left text-muted"><th className="py-0.5">Passage</th><th>Rank</th><th>Relevance</th><th>Coverage</th><th>Rerank</th></tr></thead>
            <tbody>{a.trace.hits.map((h, i) => <tr key={i} className="border-t border-line"><td className="py-1 pr-2">{h.doc}{h.page ? ` p.${h.page}` : ''}{h.section ? ` § ${h.section}` : ''}</td><td>{h.rank.toFixed(2)}</td><td>{h.relevance.toFixed(2)}</td><td>{Math.round(h.coverage * 100)}%</td><td>{h.rerank ?? '—'}</td></tr>)}</tbody></table>
        </div>
      )}

      {showActions && (
        <div className="flex flex-wrap items-center gap-2 border-t border-line px-5 py-3">
          <button className={`btn btn-sm ${a.pinned ? '!border-brand !text-brand' : ''}`} aria-pressed={a.pinned} onClick={() => void setPinned(a, !a.pinned)}>{a.pinned ? '📌 Pinned' : '📌 Pin'}</button>
          <button className="btn btn-sm btn-ghost" onClick={() => setNoting((n) => !n)}>{a.note ? '✎ Edit note' : '✎ Add note'}</button>
          <button className="btn btn-sm btn-ghost" onClick={() => setTrace((t) => !t)}>{trace ? 'Hide trace' : 'How was this found?'}</button>
          <span className="ml-auto text-xs text-muted">{a.timings_ms.total ?? ''} ms</span>
          {noting && (
            <textarea autoFocus defaultValue={a.note} placeholder="Your note (saved to the report)…" rows={2} maxLength={2000}
              onBlur={(e) => { if (e.target.value !== a.note) void setNote(a, e.target.value) }}
              className="mt-1 w-full rounded-lg border border-line bg-surface p-2 text-sm" />
          )}
          {!noting && a.note && <p className="w-full text-sm italic text-muted">“{a.note}”</p>}
        </div>
      )}
    </article>
  )
}
