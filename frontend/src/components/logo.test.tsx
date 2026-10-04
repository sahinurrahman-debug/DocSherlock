import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { Logo, LogoMark } from './Logo'
import { SiteFooter } from './SiteFooter'
import { TopBar } from './TopBar'

const health = {
  status: 'healthy', version: '2.0.0', llm: { available: true, model: 'openai/gpt-oss-120b' }, vector_store: { ok: true, mode: 'server', collection: 'c' }, ocr: { available: true, reason: '' },
  models: { dense: { name: 'm', enabled: true, ready: true, loading: false, error: null }, sparse: {}, reranker: {}, loading: false },
}
vi.mock('../context/workspace', () => ({ useWorkspace: () => ({ mode: 'auto', setMode: vi.fn(), health }) }))

const root = resolve(__dirname, '../..')
const read = (p: string) => readFileSync(resolve(root, p), 'utf-8')
const css = read('src/index.css')
const favicon = read('public/favicon.svg')
const sources = import.meta.glob('../**/*.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>
const svg = new DOMParser().parseFromString(favicon, 'image/svg+xml')

/** Geometry only (colours are compared separately): the attributes that define the shape of each element. */
const GEOMETRY = ['width', 'rx', 'cx', 'cy', 'r', 'd', 'stroke-width', 'stroke-linecap']
const shape = (root: ParentNode) => [...root.querySelectorAll('rect, circle, path')].map((el) => [el.tagName.toLowerCase(), ...GEOMETRY.map((a) => el.getAttribute(a) ?? '')].join('|'))

const tokens = (block: string) => Object.fromEntries([...block.matchAll(/--color-([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})/g)].map((m) => [m[1], m[2].toLowerCase()]))
const [lightCss, darkCss] = css.split(/\n\.dark \{/)
const light = tokens(lightCss)
const dark = tokens(darkCss.split('}')[0])

describe('one logo, everywhere', () => {
  it('the static SVG (favicon, README, PDF cover) has exactly the shape of the React logo mark', () => {
    const { container } = render(<LogoMark />)
    const mark = container.querySelector('svg')!
    expect(mark.getAttribute('viewBox')).toBe(svg.documentElement.getAttribute('viewBox'))
    expect(shape(mark)).toEqual(shape(svg.documentElement))
    expect(shape(mark)).toHaveLength(4)
  })

  it('the static SVG uses the design tokens: light colours as attributes, dark colours in its media query', () => {
    const rect = svg.querySelector('rect')!, ring = svg.querySelector('circle')!, handle = svg.querySelector('path.lamp')!
    expect(rect.getAttribute('fill')?.toLowerCase()).toBe(light.brand)
    expect(ring.getAttribute('stroke')?.toLowerCase()).toBe(light['brand-ink'])
    expect(handle.getAttribute('stroke')?.toLowerCase()).toBe(light.lamp)
    const style = svg.querySelector('style')!.textContent!.toLowerCase()
    expect(style).toContain('prefers-color-scheme: dark')
    expect(style).toContain(`.tile { fill: ${dark.brand}; }`)
    expect(style).toContain(`.ink { stroke: ${dark['brand-ink']}; }`)
    expect(style).toContain(`.lamp { stroke: ${dark.lamp}; }`)
  })

  it('the React mark takes its colours from the same tokens', () => {
    const { container } = render(<LogoMark />)
    expect(container.querySelector('rect')?.getAttribute('fill')).toBe('var(--color-brand)')
    expect(container.querySelector('circle')?.getAttribute('stroke')).toBe('var(--color-brand-ink)')
    expect(container.querySelector('path')?.getAttribute('stroke')).toBe('var(--color-lamp)')
  })

  it('every size and variant shows the same mark and the same wordmark', () => {
    const { container } = render(<><Logo /><Logo size="lg" tagline /></>)
    const words = [...container.querySelectorAll('[data-testid=logo] .font-display')].map((e) => e.textContent)
    expect(words).toEqual(['DocSherlock', 'DocSherlock'])
    expect(screen.getAllByTestId('logo-mark').map((m) => shape(m).join(';')).filter((v, i, a) => a.indexOf(v) === i)).toHaveLength(1)
    expect(screen.getByText('Evidence-grounded document investigation')).toBeInTheDocument()
  })

  it('the top bar and the footer both use it', () => {
    const { container } = render(<MemoryRouter><TopBar /><SiteFooter /></MemoryRouter>)
    expect(container.querySelectorAll('[data-testid=logo]')).toHaveLength(2)
    expect(screen.getAllByRole('img', { name: 'DocSherlock logo' })).toHaveLength(2)
  })

  it('no other source file draws its own logo or imports the bare mark', () => {
    const offenders = Object.entries(sources)
      .filter(([path]) => !path.endsWith('/Logo.tsx') && !path.includes('.test.'))
      .filter(([, code]) => /viewBox="0 0 32 32"/.test(code) || /\bLogoMark\b/.test(code))
      .map(([path]) => path)
    expect(offenders).toEqual([])
  })
})
