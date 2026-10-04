import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { TopBar } from './TopBar'

type H = Record<string, unknown> | null
const ws = { mode: 'auto', setMode: vi.fn(), health: null as H }
vi.mock('../context/workspace', () => ({ useWorkspace: () => ws }))

const healthy = (over: Record<string, unknown> = {}) => ({
  status: 'healthy', version: '2.0.0', database: { ok: true, engine: 'postgresql' }, llm: { available: true, model: 'openai/gpt-oss-120b' },
  vector_store: { ok: true, mode: 'server', collection: 'c' }, ocr: { available: true, reason: '' },
  models: { dense: { name: 'jina', enabled: true, ready: true, loading: false, error: null }, sparse: {}, reranker: {}, loading: false }, ...over,
})
const renderBar = () => render(<MemoryRouter><TopBar /></MemoryRouter>)
beforeEach(() => { ws.setMode.mockClear(); ws.health = healthy() })

describe('header layout', () => {
  it('has the four destinations in one navigation, in order', () => {
    renderBar()
    const nav = screen.getByRole('navigation', { name: 'Main' })
    expect(within(nav).getAllByRole('link').map((a) => a.textContent)).toEqual(['Dashboard', 'Investigate', 'Documents', 'Trust Lab'])
  })

  it('gives every control one height and one shape, so the row looks uniform', () => {
    const { container } = renderBar()
    const header = container.querySelector('header')!
    const controls = [
      header.querySelector('nav > div'),                                   // the navigation track
      screen.getByRole('button', { name: /system status/i }),
      header.querySelector('label'),                                       // the engine selector
      screen.getByRole('button', { name: /switch to (dark|light) mode/i }),
    ] as HTMLElement[]
    for (const c of controls) { expect(c.className).toMatch(/\bh-10\b/); expect(c.className).toMatch(/rounded-(xl|2xl)/) }
    for (const c of controls.slice(1)) expect(c.className).toContain('border-line')
  })

  it('lays out as logo | navigation | controls in a three-zone grid from 1024 px and stacks below', () => {
    const { container } = renderBar()
    const grid = container.querySelector('header > div')!
    expect(grid.className).toContain('lg:grid-cols-[1fr_auto_1fr]')
    const nav = container.querySelector('nav')!
    expect(nav.className).toContain('order-last')                           // underneath on phones and tablets
    expect(nav.className).toContain('min-w-0')                              // so it scrolls inside its track instead of widening the page
    expect(nav.className).toContain('lg:justify-self-center')               // centred on the page from 1024 px
  })

  it('marks the page you are on', () => {
    renderBar()
    expect(screen.getByRole('link', { name: 'Dashboard' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: 'Trust Lab' })).not.toHaveAttribute('aria-current')
  })
})

describe('status control', () => {
  it('summarises the system in one word, with a dot', () => {
    renderBar()
    expect(screen.getByRole('button', { name: /system status/i })).toHaveTextContent('Ready')
  })

  it('says Limited when running without an LLM key, Degraded when something is down, and Connecting before the first answer', () => {
    ws.health = healthy({ llm: { available: false, model: null } })
    const a = renderBar(); expect(screen.getByRole('button', { name: /system status/i })).toHaveTextContent('Limited'); a.unmount()
    ws.health = healthy({ database: { ok: false, engine: 'postgresql' } })
    const b = renderBar(); expect(screen.getByRole('button', { name: /system status/i })).toHaveTextContent('Degraded'); b.unmount()
    ws.health = null
    renderBar(); expect(screen.getByRole('button', { name: /system status/i })).toHaveTextContent('Connecting')
  })

  it('opens a panel listing each part of the system, and closes it again (button, Escape, click outside)', async () => {
    renderBar()
    const btn = screen.getByRole('button', { name: /system status/i })
    expect(btn).toHaveAttribute('aria-expanded', 'false')
    await userEvent.click(btn)
    const panel = screen.getByRole('group', { name: 'System status' })
    expect(btn).toHaveAttribute('aria-expanded', 'true')
    for (const [label, value] of [['Answer engine', 'Groq · gpt-oss-120b'], ['Database', 'postgresql'], ['Vector store', 'Qdrant · server'], ['Search', 'Semantic search'], ['OCR', 'Available']]) {
      expect(panel).toHaveTextContent(label); expect(panel).toHaveTextContent(value)
    }
    await userEvent.click(btn)
    expect(screen.queryByRole('group', { name: 'System status' })).toBeNull()
    await userEvent.click(btn); await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('group', { name: 'System status' })).toBeNull()
    await userEvent.click(btn); await userEvent.click(document.body)
    expect(screen.queryByRole('group', { name: 'System status' })).toBeNull()
  })

  it('explains keyword-only mode honestly', async () => {
    ws.health = healthy({ vector_store: { ok: true, mode: 'disabled', collection: 'c' }, models: { dense: { name: 'x', enabled: false, ready: false, loading: false, error: null }, sparse: {}, reranker: {}, loading: false } })
    renderBar()
    await userEvent.click(screen.getByRole('button', { name: /system status/i }))
    const panel = screen.getByRole('group', { name: 'System status' })
    expect(panel).toHaveTextContent('Not used'); expect(panel).toHaveTextContent('Keyword search')
  })
})

describe('engine selector', () => {
  it('changes the answer engine and is also reachable inside the status panel on small screens', async () => {
    renderBar()
    const selects = screen.getAllByRole('combobox', { name: 'Answer engine' })
    expect(selects).toHaveLength(1)                                         // the inline one; the panel copy only exists while the panel is open
    await userEvent.selectOptions(selects[0], 'rules')
    expect(ws.setMode).toHaveBeenCalledWith('rules')
    await userEvent.click(screen.getByRole('button', { name: /system status/i }))
    expect(screen.getAllByRole('combobox', { name: 'Answer engine' })).toHaveLength(2)
  })
})
