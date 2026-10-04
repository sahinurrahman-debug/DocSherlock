import { useWorkspace } from '../context/workspace'

function Pill({ tone, children, title }: { tone: 'ok' | 'warn' | 'none' | 'bad'; children: React.ReactNode; title?: string }) {
  const cls = { ok: 'bg-ok-soft text-ok', warn: 'bg-warn-soft text-warn', none: 'bg-none-soft text-none', bad: 'bg-bad-soft text-bad' }[tone]
  return <span title={title} className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-medium ${cls}`}><i className="inline-block h-1.5 w-1.5 rounded-full bg-current" />{children}</span>
}

/** Live system status: which engine answers, whether OCR / vector search / models are ready. */
export function StatusPills() {
  const { health: h } = useWorkspace()
  if (!h) return <Pill tone="none">Connecting…</Pill>
  const dense = h.models.dense
  const semantic = dense.ready ? 'ok' : dense.loading ? 'warn' : dense.enabled ? 'warn' : 'none'
  return (
    <div className="flex flex-wrap items-center gap-1.5" aria-live="polite">
      <Pill tone={h.llm.available ? 'ok' : 'warn'} title={h.llm.available ? `LLM: ${h.llm.model} (Groq). Falls back to the rule-based engine if the LLM fails.` : 'No GROQ_API_KEY configured - answers come from the rule-based engine.'}>
        {h.llm.available ? `Groq · ${h.llm.model?.split('/').pop()}` : 'Rule-based engine'}
      </Pill>
      {h.vector_store.mode !== 'disabled' && (
        <Pill tone={h.vector_store.ok ? 'ok' : 'bad'} title={`Qdrant (${h.vector_store.mode}) · collection ${h.vector_store.collection}`}>
          Qdrant {h.vector_store.mode === 'server' ? '' : '· local'}
        </Pill>
      )}
      <Pill tone={semantic} title={`${dense.name}${dense.error ? ' - ' + dense.error : ''}`}>
        {dense.ready ? 'Semantic search' : dense.loading ? 'Loading models…' : dense.enabled ? 'Models pending' : 'Keyword search'}
      </Pill>
      <Pill tone={h.ocr.available ? 'ok' : 'none'} title={h.ocr.reason || 'RapidOCR (offline)'}>{h.ocr.available ? 'OCR' : 'OCR off'}</Pill>
      {h.status !== 'healthy' && <Pill tone="bad">Degraded</Pill>}
    </div>
  )
}
