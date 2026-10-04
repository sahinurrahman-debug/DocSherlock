import { useWorkspace } from '../context/workspace'
import { fmtWhen } from '../lib/format'

export function InvestigationList() {
  const { investigations, currentId, openInvestigation, newInvestigation, renameInvestigation, deleteInvestigation } = useWorkspace()
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between">
        <span className="eyebrow">Investigations</span>
        <button className="btn btn-sm" onClick={newInvestigation}>+ New</button>
      </div>
      {investigations.length === 0 ? <p className="text-xs text-muted">Your questions are saved here as investigations.</p> : (
        <ul className="space-y-1">
          {investigations.map((i) => (
            <li key={i.id} className={`group flex items-center gap-1 rounded-lg border px-2 py-1.5 ${i.id === currentId ? 'border-brand bg-brand-soft' : 'border-transparent hover:bg-surface-2'}`}>
              <button className="min-w-0 flex-1 text-left" onClick={() => void openInvestigation(i.id)}>
                <div className="truncate text-[13px] font-medium">{i.name}</div>
                <div className="text-[11px] text-muted">{i.n_questions} question{i.n_questions === 1 ? '' : 's'} · {fmtWhen(i.updated_at)}</div>
              </button>
              <button className="hidden px-1 text-xs text-muted hover:text-brand group-hover:block" aria-label={`Rename ${i.name}`} onClick={() => { const n = window.prompt('Rename investigation', i.name); if (n) void renameInvestigation(i.id, n) }}>✎</button>
              <button className="hidden px-1 text-muted hover:text-bad group-hover:block" aria-label={`Delete ${i.name}`} onClick={() => { if (window.confirm(`Delete "${i.name}" and its answers?`)) void deleteInvestigation(i.id) }}>×</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
