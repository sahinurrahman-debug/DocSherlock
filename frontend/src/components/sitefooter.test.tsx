import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { COPYRIGHT_START, MIT_TEXT, REPO_URL, SiteFooter } from './SiteFooter'

vi.mock('../context/workspace', () => ({ useWorkspace: () => ({ health: { version: '2.0.0' } }) }))

const license = readFileSync(resolve(__dirname, '../../../LICENSE'), 'utf-8')
const norm = (s: string) => s.replace(/\s+/g, ' ').trim()
afterEach(() => { window.location.hash = '' })

describe('SiteFooter', () => {
  it('states the copyright and the MIT License, and links to the source', () => {
    render(<SiteFooter />)
    const footer = screen.getByRole('contentinfo', { name: 'Legal information' })
    expect(footer).toHaveTextContent(new RegExp(`© ${COPYRIGHT_START}(–\\d{4})? DocSherlock contributors`))
    expect(within(footer).getAllByRole('button', { name: 'MIT License' })).toHaveLength(2)          // the notice button and the copyright line
    expect(within(footer).getByRole('link', { name: 'Source on GitHub' })).toHaveAttribute('href', REPO_URL)
    expect(footer).toHaveTextContent('v2.0.0')
  })

  it('offers three notices, all closed at first', () => {
    render(<SiteFooter />)
    const nav = screen.getByRole('navigation', { name: 'Legal' })
    const buttons = within(nav).getAllByRole('button')
    expect(buttons.map((b) => b.textContent)).toEqual(['Conditions of use', 'Privacy notice', 'MIT License'])
    expect(buttons.every((b) => b.getAttribute('aria-expanded') === 'false')).toBe(true)
    expect(screen.queryByTestId('legal-panel')).toBeNull()
  })

  it('the conditions of use say what a user needs to know', async () => {
    render(<SiteFooter />)
    await userEvent.click(screen.getByRole('button', { name: 'Conditions of use' }))
    const panel = screen.getByRole('region', { name: 'Conditions of use' })
    for (const phrase of ['provided as is', 'Answers can be wrong', 'check it against the original document', 'sensitive material', 'Acceptable use', 'Retention', 'Third-party services', 'Last updated']) {
      expect(panel).toHaveTextContent(phrase)
    }
    expect(screen.getByRole('button', { name: 'Conditions of use' })).toHaveAttribute('aria-expanded', 'true')
  })

  it('the privacy notice matches what the app actually does', async () => {
    render(<SiteFooter />)
    await userEvent.click(screen.getByRole('button', { name: 'Privacy notice' }))
    const panel = screen.getByRole('region', { name: 'Privacy notice' })
    for (const phrase of ['does not ask for or store your name', 'workspace ID', 'Groq', 'Jina', 'Google Fonts', 'sets no cookies', 'local storage', 'No sale of data', 'docsherlock.session']) {
      expect(panel).toHaveTextContent(phrase)
    }
    expect(within(panel).getByRole('link', { name: 'the repository' })).toHaveAttribute('href', `${REPO_URL}/issues`)
  })

  it('opens one notice at a time and can be closed', async () => {
    render(<SiteFooter />)
    await userEvent.click(screen.getByRole('button', { name: 'Privacy notice' }))
    await userEvent.click(screen.getByRole('button', { name: 'Conditions of use' }))
    expect(screen.getAllByTestId('legal-panel')).toHaveLength(1)
    expect(screen.getByRole('region', { name: 'Conditions of use' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(screen.queryByTestId('legal-panel')).toBeNull()
  })

  it('shows the full MIT text, identical to the LICENSE file in the repository', async () => {
    render(<SiteFooter />)
    await userEvent.click(screen.getAllByRole('button', { name: 'MIT License' })[0])
    const shown = screen.getByTestId('mit-text').textContent ?? ''
    expect(norm(shown)).toBe(norm(license))
    expect(norm(MIT_TEXT)).toBe(norm(license))
    expect(shown).toContain('THE SOFTWARE IS PROVIDED "AS IS"')
    expect(screen.getByRole('region', { name: 'MIT License' })).toHaveTextContent('PyMuPDF')       // third-party licences are not hidden
  })

  it('the copyright line also opens the license, and a link like /#privacy opens its notice directly', async () => {
    const { unmount } = render(<SiteFooter />)
    await userEvent.click(within(screen.getByRole('contentinfo')).getAllByRole('button', { name: 'MIT License' }).at(-1)!)
    expect(screen.getByRole('region', { name: 'MIT License' })).toBeInTheDocument()
    unmount()
    window.location.hash = '#privacy'
    render(<SiteFooter />)
    expect(screen.getByRole('region', { name: 'Privacy notice' })).toBeInTheDocument()
  })
})
