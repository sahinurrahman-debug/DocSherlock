import { useEffect, useMemo, useRef, useState } from 'react'
import { useWorkspace } from '../context/workspace'
import { AnswerCard } from './AnswerCard'

const STAGES: Record<string, string> = {
  retrieving: 'Searching your documents', checking_conflicts: 'Checking evidence and conflicts', reasoning: 'Reasoning over the evidence',
  composing: 'Composing the answer', verifying: 'Verifying every citation', comparing: 'Comparing the documents',
}
const ORDER = ['retrieving', 'checking_conflicts', 'reasoning', 'composing', 'comparing', 'verifying']

const DEMO_QS = [
  'What are the payment terms?', 'What is the termination notice period?', 'How many employees does Northwind have?', 'How often must passwords be rotated?',
  'Is MFA required for remote access?', 'When did the outage start?', 'What was the root cause of the September outage?', 'What marketing budget did the board approve?',
  'What changed between the 2023 contract and the 2024 amendment?', 'Who is the CFO?', 'What is the share price of Northwind?',
]
const GENERIC_QS = ['Summarise the key obligations in these documents.', 'What amounts are mentioned?', 'What dates are mentioned?', 'Do any documents contradict each other?']

export function ChatPanel() {
  const { thread, pending, ask, documents, readyDocs, scopeIds, health, loadDemo } = useWorkspace()
  const [q, setQ] = useState('')
  const end = useRef<HTMLDivElement>(null)
  const area = useRef<HTMLTextAreaElement>(null)
  const demo = documents.some((d) => /Vendor_Services|Board_Minutes/.test(d.filename))
  const suggestions = useMemo(() => (demo ? DEMO_QS : GENERIC_QS), [demo])
  const busy = pending !== null
  const noDocs = readyDocs.length === 0

  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [thread.length, pending?.stage])
  useEffect(() => { const t = area.current; if (t) { t.style.height = 'auto'; t.style.height = Math.min(t.scrollHeight, 140) + 'px' } }, [q])

  const submit = () => { const v = q.trim(); if (!v || busy) return; setQ(''); void ask(v) }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="scroll-thin min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
        {thread.length === 0 && !pending && (
          <div className="mx-auto mt-[4vh] max-w-2xl text-center">
            <h1 className="text-2xl font-bold tracking-tight">What do you want to find out?</h1>
            <p className="mx-auto mt-2 max-w-xl text-[13.5px] text-muted">Answers come only from your documents, with the exact passage cited. When documents disagree you get every position - not a guess. When they don't say, you get “not found”.</p>
            {noDocs ? (
              <div className="mt-5"><button className="btn btn-primary" onClick={() => void loadDemo()}>Load the sample set</button><p className="mt-2 text-xs text-muted">or upload your own documents on the left</p></div>
            ) : (
              <div className="mt-5 flex flex-wrap justify-center gap-2">{suggestions.map((s) => <button key={s} className="rounded-full border border-line bg-surface px-3 py-1.5 text-[13px] hover:border-brand hover:text-brand" onClick={() => void ask(s)}>{s}</button>)}</div>
            )}
          </div>
        )}
        {thread.map((a) => (
          <section key={a.id} className="space-y-2.5">
            <div className="flex justify-end"><div className="max-w-[85%] rounded-2xl rounded-br-sm bg-brand px-3.5 py-2 text-[14px] font-medium text-brand-ink">{a.question}</div></div>
            <AnswerCard a={a} />
          </section>
        ))}
        {pending && (
          <section className="space-y-2.5" aria-live="polite">
            <div className="flex justify-end"><div className="max-w-[85%] rounded-2xl rounded-br-sm bg-brand px-3.5 py-2 text-[14px] font-medium text-brand-ink">{pending.question}</div></div>
            <div className="card px-4 py-3">
              <div className="dot-pulse mb-2"><i /><i /><i /></div>
              <ol className="flex flex-wrap gap-x-4 gap-y-1 text-[12.5px]">
                {ORDER.filter((s) => s !== 'comparing' || pending.stage === 'comparing').filter((s) => s !== 'composing' || pending.stage === 'composing').map((s) => {
                  const idx = ORDER.indexOf(pending.stage)
                  const state = ORDER.indexOf(s) < idx ? 'done' : s === pending.stage ? 'now' : 'todo'
                  return <li key={s} className={state === 'now' ? 'font-semibold text-brand' : state === 'done' ? 'text-ok' : 'text-muted'}>{state === 'done' ? '✓' : state === 'now' ? '●' : '○'} {STAGES[s]}{s === 'reasoning' && state === 'now' && pending.detail ? ` (${pending.detail.replace('Asking ', '')})` : ''}</li>
                })}
              </ol>
            </div>
          </section>
        )}
        <div ref={end} />
      </div>

      <form className="border-t border-line bg-bg px-4 pb-3 pt-2.5" onSubmit={(e) => { e.preventDefault(); submit() }}>
        <div className="mb-1.5 flex flex-wrap items-center gap-x-3 text-[11.5px] text-muted">
          <span>Scope: <b className="text-ink">{scopeIds ? `${scopeIds.length} of ${readyDocs.length} documents` : `all ${readyDocs.length} ready documents`}</b></span>
          <span>{health?.llm.available ? 'Groq answers, rule-based fallback' : 'Rule-based answers (add GROQ_API_KEY for LLM answers)'}</span>
        </div>
        <div className="flex items-end gap-2">
          <textarea ref={area} value={q} onChange={(e) => setQ(e.target.value)} rows={1} maxLength={1500} disabled={noDocs}
            placeholder={noDocs ? 'Upload or load documents to start' : 'Ask a question about your documents…  (Enter to send · Shift+Enter for a new line)'}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit() } }}
            className="max-h-36 min-h-[42px] flex-1 resize-none rounded-xl border border-line bg-surface px-3 py-2.5 text-[14px] disabled:opacity-60" aria-label="Your question" />
          <button type="submit" className="btn btn-primary h-[42px] px-5" disabled={busy || noDocs || !q.trim()}>{busy ? 'Working…' : 'Investigate'}</button>
        </div>
      </form>
    </div>
  )
}
