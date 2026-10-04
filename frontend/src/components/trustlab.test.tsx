import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import TrustLab from '../pages/TrustLab'
import { api, ApiError } from '../lib/api'
import type { TrustCase, TrustReport } from '../lib/types'

const ws = { toast: vi.fn() }
vi.mock('../context/workspace', () => ({ useWorkspace: () => ws }))

const cases: TrustCase[] = [
  { id: 'refuse', category: 'Honesty', title: 'Refuses to guess', what: 'Asks something the documents never say.' },
  { id: 'injection', category: 'Safety', title: 'Ignores instructions hidden in a document', what: 'A memo tells AI assistants to deny the clause.' },
  { id: 'corrupt', category: 'Robustness', title: 'Survives a corrupt PDF', what: 'Random bytes with a .pdf name.' },
]
const report = (failed = false): TrustReport => ({
  started_at: '2026-10-04T12:00:00Z', duration_ms: 320, passed: failed ? 2 : 3, failed: failed ? 1 : 0, total: 3, llm_used: false,
  cases: cases.map((c) => ({ ...c, status: failed && c.id === 'injection' ? 'fail' as const : 'pass' as const, ms: 12, detail: `${c.id}: what actually happened` })),
})

beforeEach(() => { ws.toast.mockClear(); vi.restoreAllMocks() })

describe('Trust Lab page', () => {
  it('lists every check grouped by category before anything has run', async () => {
    vi.spyOn(api.trustlab, 'overview').mockResolvedValue({ cases, last: null })
    render(<TrustLab />)
    expect(await screen.findByRole('heading', { name: 'Honesty' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Safety' })).toBeInTheDocument()
    expect(screen.getAllByTestId('trust-case').every((r) => r.getAttribute('data-status') === 'idle')).toBe(true)
    expect(screen.getByRole('img', { name: 'No results yet' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Run the stress test' })).toBeEnabled()
  })

  it('runs the stress test and shows what actually happened for each case, with the score', async () => {
    vi.spyOn(api.trustlab, 'overview').mockResolvedValue({ cases, last: null })
    vi.spyOn(api.trustlab, 'run').mockResolvedValue(report())
    render(<TrustLab />)
    await userEvent.click(await screen.findByRole('button', { name: 'Run the stress test' }))
    await waitFor(() => expect(screen.getByRole('img', { name: '3 of 3 checks passed' })).toBeInTheDocument())
    const rows = screen.getAllByTestId('trust-case')
    expect(rows.map((r) => r.getAttribute('data-status'))).toEqual(['pass', 'pass', 'pass'])
    expect(within(rows[1]).getByText('injection: what actually happened')).toBeInTheDocument()
    expect(screen.getByText('3 of 3 passed in 320 ms')).toBeInTheDocument()
    expect(ws.toast).toHaveBeenCalledWith('All 3 checks passed')
    expect(screen.getByRole('button', { name: 'Run it again' })).toBeInTheDocument()
  })

  it('surfaces a failing case clearly', async () => {
    vi.spyOn(api.trustlab, 'overview').mockResolvedValue({ cases, last: report(true) })
    render(<TrustLab />)
    const rows = await screen.findAllByTestId('trust-case')
    expect(rows.map((r) => r.getAttribute('data-status'))).toEqual(['pass', 'fail', 'pass'])
    expect(screen.getByRole('img', { name: '2 of 3 checks passed' })).toBeInTheDocument()
    expect(within(rows[1]).getByText('Failed.')).toBeInTheDocument()                   // screen-reader text, not colour alone
  })

  it('shows a readable message when the run is refused or the server is unreachable', async () => {
    vi.spyOn(api.trustlab, 'overview').mockResolvedValue({ cases, last: null })
    vi.spyOn(api.trustlab, 'run').mockRejectedValue(new ApiError('A run is already in progress.', 409))
    render(<TrustLab />)
    await userEvent.click(await screen.findByRole('button', { name: 'Run the stress test' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('A run is already in progress.')
    expect(screen.getByRole('button', { name: 'Run the stress test' })).toBeEnabled()
  })

  it('reports an unreachable server', async () => {
    vi.spyOn(api.trustlab, 'overview').mockRejectedValue(new ApiError('Network down', 0))
    render(<TrustLab />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Network down')
  })
})
