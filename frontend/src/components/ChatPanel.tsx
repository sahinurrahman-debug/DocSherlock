import { useEffect, useMemo, useRef, useState } from 'react'
import { useWorkspace } from '../context/workspace'
import { AnswerCard } from './AnswerCard'
import { EmptyState } from './EmptyState'
import { AskIllustration, PapersIllustration } from './illustrations'

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
      <div className="scroll-thin min-h-0 flex-1 space-y-6 overflow-y-auto px-4 py-6 sm:px-6">
        {thread.length === 0 && !pending && (
          noDocs ? (
            <EmptyState className="mt-[3vh]" art={<PapersIllustration />} title="Let's start with some documents"
              actions={<><button className="btn btn-primary" onClick={() => void loadDemo()}>Load the sample set</button></>}>
              Add a few files on the left - or try the sample set - and then ask anything. Answers come only from your documents, with the exact passage cited.
            </EmptyState>
          ) : (
            <div className="rise mx-auto mt-[3vh] max-w-2xl text-center">
              <div className="mx-auto w-40"><AskIllustration /></div>
              <h1 className="mt-2 text-3xl font-semibold">What do you want to find out?</h1>
              <p className="mx-auto mt-3 max-w-xl text-base leading-relaxed text-muted">Ask in your own words. If documents disagree you'll see every position - never a guess. If they simply don't say, you'll hear that too.</p>
              <div className="mt-6 flex flex-wrap justify-center gap-2.5">{suggestions.map((s, i) => <button key={s} style={{ '--i': i } as React.CSSProperties} className="rise rounded-full border border-line bg-surface px-4 py-2 text-sm transition duration-200 hover:-translate-y-0.5 hover:border-brand hover:text-brand hover:shadow-[var(--shadow-card)] active:scale-[.98]" onClick={() => void ask(s)}>{s}</button>)}</div>
            </div>
          )
        )}
        {thread.map((a) => (
          <section key={a.id} className="rise space-y-3">
            <div className="flex justify-end"><div className="pop max-w-[85%] rounded-3xl rounded-br-md bg-brand px-5 py-3 text-base font-medium text-brand-ink shadow-[var(--shadow-card)]">{a.question}</div></div>
            <AnswerCard a={a} />
          </section>
        ))}
        {pending && (
          <section className="fade space-y-3" aria-live="polite">
            <div className="flex justify-end"><div className="pop max-w-[85%] rounded-3xl rounded-br-md bg-brand px-5 py-3 text-base font-medium text-brand-ink shadow-[var(--shadow-card)]">{pending.question}</div></div>
            <div className="card px-5 py-4">
              <div className="dot-pulse mb-3" aria-hidden="true"><i /><i /><i /></div>
              <ol className="flex flex-wrap gap-x-5 gap-y-1.5 text-sm">
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

      <form className="border-t border-line bg-surface/80 px-4 pb-4 pt-3 backdrop-blur-md sm:px-6" onSubmit={(e) => { e.preventDefault(); submit() }}>
        <div className="mb-2 flex flex-wrap items-center gap-x-4 text-xs text-muted">
          <span>Scope: <b className="text-ink">{scopeIds ? `${scopeIds.length} of ${readyDocs.length} documents` : `all ${readyDocs.length} ready documents`}</b></span>
          <span className="hidden sm:inline">Enter to send · Shift+Enter for a new line</span>
          <span>{health?.llm.available ? 'Groq answers, rule-based fallback' : 'Rule-based answers (add a Groq key for LLM answers)'}</span>
        </div>
        <div className="flex items-end gap-2">
          <textarea ref={area} value={q} onChange={(e) => setQ(e.target.value)} rows={1} maxLength={1500} disabled={noDocs}
            placeholder={noDocs ? 'Add documents to start asking' : 'Ask about your documents…'}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit() } }}
            className="field max-h-36 min-h-12 flex-1 resize-none !rounded-2xl disabled:opacity-60" aria-label="Your question" />
          <button type="submit" className="btn btn-primary !h-12 !rounded-2xl !px-6" disabled={busy || noDocs || !q.trim()}>{busy ? 'Thinking…' : 'Ask'}</button>
        </div>
      </form>
    </div>
  )
}
