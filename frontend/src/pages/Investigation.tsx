import { useEffect, useState } from 'react'
import { useWorkspace } from '../context/workspace'
import { ChatPanel } from '../components/ChatPanel'
import { ComparePanel } from '../components/ComparePanel'
import { ConflictBoard } from '../components/ConflictBoard'
import { DocumentList } from '../components/DocumentList'
import { EvidencePanel } from '../components/EvidencePanel'
import { FileUploader } from '../components/FileUploader'
import { InvestigationList } from '../components/InvestigationList'

type Tab = 'ask' | 'conflicts' | 'compare'
type Pane = 'docs' | 'main' | 'source'

export default function Investigation() {
  const { viewer, closeViewer, exportReport, ask, thread, currentId, investigations, documents, resetAll } = useWorkspace()
  const [tab, setTab] = useState<Tab>('ask')
  const [pane, setPane] = useState<Pane>('main')
  const [rightOpen, setRightOpen] = useState(true)
  const name = investigations.find((i) => i.id === currentId)?.name

  useEffect(() => { if (viewer) { setRightOpen(true); if (window.innerWidth < 1024) setPane('source') } }, [viewer])

  const tabBtn = (t: Tab, label: string, badge?: number) => (
    <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
      className={`relative -mb-px border-b-2 px-4 py-3 text-sm font-semibold transition duration-200 ${tab === t ? 'border-brand text-brand' : 'border-transparent text-muted hover:text-ink'}`}>
      {label}{badge ? <span className="ml-1.5 rounded-full bg-surface-2 px-2 py-0.5 text-xs text-muted">{badge}</span> : null}
    </button>
  )

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex gap-1 border-b border-line bg-surface p-2 lg:hidden" role="tablist" aria-label="Workspace panes">
        {([['docs', 'Files'], ['main', 'Workspace'], ['source', 'Source']] as const).map(([p, l]) => (
          <button key={p} role="tab" aria-selected={pane === p} onClick={() => setPane(p)} className={`flex-1 rounded-xl py-2 text-sm font-medium transition duration-200 ${pane === p ? 'bg-brand-soft text-brand' : 'text-muted'}`}>{l}</button>
        ))}
      </div>

      <div className={`grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[320px_minmax(0,1fr)] ${rightOpen ? 'xl:grid-cols-[320px_minmax(0,1fr)_minmax(360px,32%)]' : ''}`}>
        <aside className={`scroll-thin min-h-0 space-y-5 overflow-y-auto border-r border-line bg-bg/60 p-4 ${pane === 'docs' ? 'block' : 'hidden'} lg:block`} aria-label="Documents and investigations">
          <section>
            <div className="mb-2 flex items-center justify-between"><span className="eyebrow">Documents</span>{documents.length > 0 && <button className="text-sm text-muted transition hover:text-bad" onClick={() => { if (window.confirm('Remove all documents from this workspace?')) void resetAll() }}>clear all</button>}</div>
            <FileUploader compact />
            <div className="mt-3"><DocumentList /></div>
          </section>
          <InvestigationList />
        </aside>

        <main className={`flex min-h-0 min-w-0 flex-col ${pane === 'main' ? 'flex' : 'hidden'} lg:flex`}>
          <div className="flex flex-wrap items-center gap-2 border-b border-line bg-surface/80 px-4 backdrop-blur-md" role="tablist" aria-label="Investigation views">
            {tabBtn('ask', 'Ask')}{tabBtn('conflicts', 'Conflict board')}{tabBtn('compare', 'Compare')}
            <div className="ml-auto flex items-center gap-2 py-1.5">
              {name && <span className="hidden max-w-[220px] truncate text-xs text-muted md:inline" title={name}>{name}</span>}
              <button className="btn btn-sm" onClick={() => void exportReport(false)} disabled={!currentId} title="Download a Markdown report of this investigation">Export report</button>
              {!rightOpen && <button className="btn btn-sm hidden xl:inline-flex" onClick={() => setRightOpen(true)}>Show sources</button>}
            </div>
          </div>
          <div key={tab} className="fade min-h-0 flex-1">
            {tab === 'ask' && <ChatPanel />}
            {tab === 'conflicts' && <div className="scroll-thin h-full overflow-y-auto"><ConflictBoard onAsk={(q) => { setTab('ask'); void ask(q) }} /></div>}
            {tab === 'compare' && <div className="scroll-thin h-full overflow-y-auto"><ComparePanel /></div>}
          </div>
        </main>

        <div className={`min-h-0 ${pane === 'source' ? 'block' : 'hidden'} ${rightOpen ? 'xl:block' : 'xl:hidden'}`}>
          <EvidencePanel onClose={() => { closeViewer(); setRightOpen(false); setPane('main') }} />
        </div>
      </div>
      <span className="sr-only" aria-live="polite">{thread.length} answers in this investigation</span>
    </div>
  )
}
