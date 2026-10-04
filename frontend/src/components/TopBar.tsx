import { useEffect, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { useWorkspace } from '../context/workspace'
import type { Mode } from '../lib/types'
import { Logo } from './Logo'
import { StatusPills } from './StatusPills'

function useTheme() {
  const [dark, setDark] = useState(() => {
    try {
      const s = localStorage.getItem('docsherlock.theme')
      return s ? s === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches
    } catch { return false }
  })
  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark)
    try { localStorage.setItem('docsherlock.theme', dark ? 'dark' : 'light') } catch { /* private mode */ }
  }, [dark])
  return [dark, () => setDark((d) => !d)] as const
}

const link = ({ isActive }: { isActive: boolean }) =>
  `rounded-lg px-3 py-1.5 text-[13px] font-medium transition ${isActive ? 'bg-brand-soft text-brand' : 'text-muted hover:bg-surface-2 hover:text-ink'}`

export function TopBar() {
  const { mode, setMode, health } = useWorkspace()
  const [dark, toggle] = useTheme()
  return (
    <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line bg-surface px-4 py-2.5">
      <NavLink to="/" className="mr-2" aria-label="DocSherlock home"><Logo /></NavLink>
      <nav className="flex items-center gap-1" aria-label="Main">
        <NavLink to="/" end className={link}>Dashboard</NavLink>
        <NavLink to="/investigate" className={link}>Investigate</NavLink>
        <NavLink to="/documents" className={link}>Documents</NavLink>
      </nav>
      <div className="ml-auto flex flex-wrap items-center gap-3">
        <StatusPills />
        <label className="flex items-center gap-1.5 text-xs text-muted">
          Engine
          <select value={mode} onChange={(e) => setMode(e.target.value as Mode)} className="rounded-md border border-line bg-surface px-1.5 py-1 text-xs text-ink" aria-label="Answer engine">
            <option value="auto">{health?.llm.available ? 'Auto (Groq → rules)' : 'Auto'}</option>
            <option value="rules">Rules only</option>
            <option value="llm">Groq only</option>
          </select>
        </label>
        <button className="btn btn-ghost btn-sm" onClick={toggle} aria-label="Toggle dark mode" title="Toggle theme">{dark ? '☀' : '☾'}</button>
      </div>
    </header>
  )
}
