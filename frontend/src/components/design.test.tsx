import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { EmptyState } from './EmptyState'
import { PapersIllustration } from './illustrations'
import { Skeleton, SkeletonLines } from './Skeleton'
import { TopBar } from './TopBar'

vi.mock('../context/workspace', () => ({ useWorkspace: () => ({ mode: 'auto', setMode: vi.fn(), health: null }) }))

afterEach(() => { document.documentElement.classList.remove('dark', 'theme-anim'); localStorage.clear() })

describe('EmptyState', () => {
  it('gives a headline, help text, an illustration and the next step', async () => {
    const onClick = vi.fn()
    render(<EmptyState art={<PapersIllustration />} title="Nothing here yet" actions={<button onClick={onClick}>Load the sample set</button>}>Drop a file to begin.</EmptyState>)
    expect(screen.getByRole('heading', { name: 'Nothing here yet' })).toBeInTheDocument()
    expect(screen.getByText('Drop a file to begin.')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /papers/i })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Load the sample set' }))
    expect(onClick).toHaveBeenCalled()
  })
})

describe('Skeleton', () => {
  it('is hidden from assistive tech, while a group of lines announces loading', () => {
    const { container } = render(<><Skeleton className="h-4" /><SkeletonLines lines={3} /></>)
    expect(container.querySelector('.skeleton[aria-hidden="true"]')).not.toBeNull()
    expect(screen.getByRole('status', { name: 'Loading' })).toBeInTheDocument()
  })
})

describe('theme toggle', () => {
  it('switches to dark, remembers the choice, and switches back', async () => {
    render(<MemoryRouter><TopBar /></MemoryRouter>)
    await userEvent.click(screen.getByRole('button', { name: 'Switch to dark mode' }))
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    expect(localStorage.getItem('docsherlock.theme')).toBe('dark')
    await userEvent.click(screen.getByRole('button', { name: 'Switch to light mode' }))
    expect(document.documentElement.classList.contains('dark')).toBe(false)
    expect(localStorage.getItem('docsherlock.theme')).toBe('light')
  })
})
