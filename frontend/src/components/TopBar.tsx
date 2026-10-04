import { useEffect, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { useWorkspace } from '../context/workspace'
import type { Mode } from '../lib/types'
import { Logo } from './Logo'
import { StatusMenu } from './StatusMenu'

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

/* Every control in the header shares one height (h-10), one radius (rounded-xl), one border and one hover style, so the row reads as a set. */
const CONTROL = 'rounded-xl border border-line bg-surface transition duration-200 hover:border-brand/50'

function ThemeToggle({ dark, onToggle }: { dark: boolean; onToggle: () => void }) {
  return (
    <button className={`${CONTROL} inline-flex h-10 w-10 shrink-0 items-center justify-center text-ink hover:bg-surface-2 active:scale-[.98]`} onClick={onToggle}
      aria-label={dark ? 'Switch to light mode' : 'Switch to dark mode'} aria-pressed={dark} title={dark ? 'Light mode' : 'Dark mode'}>
      <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <g className={`origin-center transition duration-500 ${dark ? 'scale-0 -rotate-90 opacity-0' : 'scale-100 rotate-0 opacity-100'}`} style={{ transformBox: 'fill-box' }}>
          <circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
        </g>
        <path className={`origin-center transition duration-500 ${dark ? 'scale-100 rotate-0 opacity-100' : 'scale-0 rotate-90 opacity-0'}`} style={{ transformBox: 'fill-box' }} d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" />
      </svg>
    </button>
  )
}

function EngineSelect({ className = '' }: { className?: string }) {
  const { mode, setMode, health } = useWorkspace()
  return (
    <label className={`${CONTROL} relative h-10 items-center text-sm focus-within:border-brand focus-within:ring-2 focus-within:ring-brand/25 ${className}`}>
      <span className="pl-3.5 text-xs font-semibold uppercase tracking-wider text-muted">Engine</span>
      <select value={mode} onChange={(e) => setMode(e.target.value as Mode)} aria-label="Answer engine"
        title={health?.llm.available ? 'Auto: Groq writes the answer, the rule-based engine takes over if it fails. Rules only: never call the LLM. Groq only: no fallback.' : 'No LLM key is configured, so the rule-based engine answers.'}
        className="h-full min-w-0 flex-1 cursor-pointer appearance-none bg-transparent pl-2.5 pr-9 text-sm font-medium text-ink focus:outline-none">
        <option value="auto">Auto</option>
        <option value="rules">Rules only</option>
        <option value="llm">Groq only</option>
      </select>
      <svg viewBox="0 0 20 20" className="pointer-events-none absolute right-3 h-4 w-4 text-muted" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M5 8l5 5 5-5" /></svg>
    </label>
  )
}

const link = ({ isActive }: { isActive: boolean }) =>
  `inline-flex h-8 flex-1 items-center justify-center whitespace-nowrap rounded-[.65rem] px-1 text-[0.84rem] font-medium transition duration-200 sm:px-2 sm:text-sm lg:flex-none lg:px-3.5 ${isActive ? 'bg-surface text-brand shadow-[var(--shadow-card)]' : 'text-muted hover:text-ink'}`

/**
 * Header layout: logo | navigation | controls.
 *  - from 1024 px: one row of three equal-weight zones, so the navigation sits exactly in the middle of the page
 *  - below that (tablets and phones): logo and controls on the first row, the navigation full width underneath
 * The answer-engine choice shows next to the status control from 1280 px and moves inside the status panel below that.
 */
export function TopBar() {
  const [dark, toggle] = useTheme()
  return (
    <header className="sticky top-0 z-30 border-b border-line bg-surface/85 backdrop-blur-md">
      <div className="grid grid-cols-[auto_auto] items-center justify-between gap-x-4 gap-y-2.5 px-4 py-2.5 sm:px-5 lg:grid-cols-[1fr_auto_1fr]">
        <NavLink to="/" className="justify-self-start rounded-lg" aria-label="DocSherlock home"><Logo /></NavLink>

        <nav className="order-last col-span-2 min-w-0 lg:order-none lg:col-span-1 lg:justify-self-center" aria-label="Main">
          <div className="scroll-thin flex h-10 max-w-full items-center gap-0.5 overflow-x-auto sm:gap-1 overflow-y-hidden rounded-2xl border border-line bg-surface-2/70 p-1">
            <NavLink to="/" end className={link}>Dashboard</NavLink>
            <NavLink to="/investigate" className={link}>Investigate</NavLink>
            <NavLink to="/documents" className={link}>Documents</NavLink>
            <NavLink to="/trust" className={link}>Trust Lab</NavLink>
          </div>
        </nav>

        <div className="flex items-center gap-2.5 justify-self-end">
          <StatusMenu extra={<div className="xl:hidden"><div className="eyebrow mb-2">Answer engine</div><EngineSelect className="flex w-full" /></div>} />
          <EngineSelect className="hidden w-[10.5rem] xl:flex" />
          <ThemeToggle dark={dark} onToggle={toggle} />
        </div>
      </div>
    </header>
  )
}
