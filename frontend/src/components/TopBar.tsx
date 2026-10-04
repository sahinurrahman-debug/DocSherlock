import { useEffect, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { useWorkspace } from '../context/workspace'
import type { Mode } from '../lib/types'
import { Logo } from './Logo'
import { StatusPills } from './StatusPills'

function useTheme() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains('dark'))
  const toggle = () => {
    const root = document.documentElement
    root.classList.add('theme-anim')                           // cross-fade colours for a moment instead of snapping
    const next = !root.classList.contains('dark')
    root.classList.toggle('dark', next)
    setDark(next)
    try { localStorage.setItem('docsherlock.theme', next ? 'dark' : 'light') } catch { /* private mode */ }
    window.setTimeout(() => root.classList.remove('theme-anim'), 450)
  }
  useEffect(() => {                                            // follow the OS setting until the user chooses
    let stored: string | null = null
    try { stored = localStorage.getItem('docsherlock.theme') } catch { /* private mode */ }
    if (stored) return
    if (typeof window.matchMedia !== 'function') return
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const on = (e: MediaQueryListEvent) => { document.documentElement.classList.toggle('dark', e.matches); setDark(e.matches) }
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])
  return [dark, toggle] as const
}

function ThemeToggle({ dark, onToggle }: { dark: boolean; onToggle: () => void }) {
  return (
    <button className="btn btn-ghost !min-h-10 !w-10 !px-0" onClick={onToggle} aria-label={dark ? 'Switch to light mode' : 'Switch to dark mode'} aria-pressed={dark} title={dark ? 'Light mode' : 'Dark mode'}>
      <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <g className={`origin-center transition duration-500 ${dark ? 'scale-0 -rotate-90 opacity-0' : 'scale-100 rotate-0 opacity-100'}`} style={{ transformBox: 'fill-box' }}>
          <circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
        </g>
        <path className={`origin-center transition duration-500 ${dark ? 'scale-100 rotate-0 opacity-100' : 'scale-0 rotate-90 opacity-0'}`} style={{ transformBox: 'fill-box' }} d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" />
      </svg>
    </button>
  )
}

const link = ({ isActive }: { isActive: boolean }) =>
  `relative whitespace-nowrap rounded-xl px-3.5 py-2 text-sm font-medium transition duration-200 ${isActive ? 'bg-brand-soft text-brand' : 'text-muted hover:bg-surface-2 hover:text-ink'}`

export function TopBar() {
  const { mode, setMode, health } = useWorkspace()
  const [dark, toggle] = useTheme()
  return (
    <header className="sticky top-0 z-30 flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-line bg-surface/85 px-4 py-2 backdrop-blur-md sm:px-5">
      <NavLink to="/" className="mr-1 rounded-lg" aria-label="DocSherlock home"><Logo /></NavLink>
      <nav className="scroll-thin order-last -mx-1 flex w-full items-center gap-1 overflow-x-auto px-1 pb-1 sm:order-none sm:mx-0 sm:w-auto sm:overflow-visible sm:px-0 sm:pb-0" aria-label="Main">
        <NavLink to="/" end className={link}>Dashboard</NavLink>
        <NavLink to="/investigate" className={link}>Investigate</NavLink>
        <NavLink to="/documents" className={link}>Documents</NavLink>
      </nav>
      <div className="ml-auto flex items-center gap-2 sm:gap-3">
        <div className="hidden xl:block"><StatusPills /></div>
        <label className="hidden items-center gap-2 text-sm text-muted sm:flex">
          <span className="sr-only sm:not-sr-only">Engine</span>
          <select value={mode} onChange={(e) => setMode(e.target.value as Mode)} className="field !w-auto !rounded-lg !py-1.5 !pr-8 text-sm" aria-label="Answer engine">
            <option value="auto">{health?.llm.available ? 'Auto (Groq → rules)' : 'Auto'}</option>
            <option value="rules">Rules only</option>
            <option value="llm">Groq only</option>
          </select>
        </label>
        <ThemeToggle dark={dark} onToggle={toggle} />
      </div>
    </header>
  )
}
