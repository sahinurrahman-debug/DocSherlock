import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { answered } from '../test/fixtures'
import type { RedTeamResult } from '../lib/types'
import { AnswerCard } from './AnswerCard'
import { RedTeamPanel } from './RedTeamPanel'

const ws = { openSource: vi.fn(), setPinned: vi.fn(), setNote: vi.fn(), redTeam: vi.fn() }
vi.mock('../context/workspace', () => ({ useWorkspace: () => ws }))

const ev = { doc_id: 'd2', doc_name: 'Amendment.docx', doc_date: '2024-01-15', page: 1, section: '', start: 5, end: 40, quote: 'Invoices are payable Net 45 from the invoice date.', value: 'Net 45', ocr_conf: null }
const refuted: RedTeamResult = {
  verdict: 'refuted', headline: 'Refuted: a critical problem was found - do not rely on this answer as stated', attacks_run: 6, concerns: 2, adversary: 'rules', ran_at: '2026-10-04T12:00:00Z',
  checks: [
    { id: 'quotes', label: 'Every quote is verbatim', status: 'passed', severity: null, detail: 'All 1 cited quote(s) match the stored page text exactly.', evidence: [] },
    { id: 'contradictions', label: 'No cited passage is disputed elsewhere', status: 'failed', severity: 'critical', detail: 'A passage this answer relies on is disputed by another document (Net 30 vs Net 45).', evidence: [ev] },
    { id: 'single_source', label: 'Backed by more than one document', status: 'skipped', severity: null, detail: 'Not applicable.', evidence: [] },
  ],
}

beforeEach(() => { Object.values(ws).forEach((f) => f.mockClear()) })

describe('RedTeamPanel', () => {
  it('shows the verdict, how many attacks were tried, and every check with its outcome', () => {
    render(<RedTeamPanel r={refuted} />)
    const panel = screen.getByTestId('redteam')
    expect(panel).toHaveAttribute('data-verdict', 'refuted')
    expect(within(panel).getByText('Refuted', { selector: 'span' })).toBeInTheDocument()
    expect(panel).toHaveTextContent('6 attacks tried (deterministic checks; no model involved)')
    const rows = screen.getAllByTestId('rt-check')
    expect(rows.map((r) => r.getAttribute('data-status'))).toEqual(['passed', 'failed', 'skipped'])
    expect(within(rows[1]).getByText('critical')).toBeInTheDocument()
    expect(within(rows[1]).getByText('Broke')).toBeInTheDocument()                    // outcome is also available to screen readers
  })

  it('opens the exact passage behind a failed check', async () => {
    render(<RedTeamPanel r={refuted} />)
    await userEvent.click(screen.getByRole('button', { name: /Amendment\.docx/ }))
    expect(ws.openSource).toHaveBeenCalledWith({ docId: 'd2', docName: 'Amendment.docx', page: 1, start: 5, end: 40, quote: ev.quote })
  })

  it('says when an adversarial model took part', () => {
    render(<RedTeamPanel r={{ ...refuted, verdict: 'survived', headline: 'Survived 5 of 5 attacks', adversary: 'llm', concerns: 0 }} />)
    expect(screen.getByTestId('redteam')).toHaveTextContent('adversarial language model whose objections count only when quoted verbatim')
  })
})

describe('AnswerCard red-team button', () => {
  it('runs the attack on click and shows the stored verdict afterwards', async () => {
    ws.redTeam.mockResolvedValue(undefined)
    const { rerender } = render(<AnswerCard a={answered} />)
    await userEvent.click(screen.getByRole('button', { name: 'Red-team this answer' }))
    expect(ws.redTeam).toHaveBeenCalledWith(answered)
    rerender(<AnswerCard a={{ ...answered, redteam: { ...refuted, verdict: 'survived', headline: 'Survived 6 of 6 attacks', concerns: 0 } }} />)
    expect(screen.getByRole('button', { name: 'Red-team again' })).toBeInTheDocument()
    expect(screen.getByTestId('redteam')).toHaveAttribute('data-verdict', 'survived')
    await userEvent.click(screen.getByRole('button', { name: 'survived' }))          // the verdict chip collapses the panel
    expect(screen.queryByTestId('redteam')).toBeNull()
  })
})

describe('AnswerCard evidence pack', () => {
  it('downloads the evidence pack for the answer', async () => {
    Object.assign(ws, { exportPack: vi.fn().mockResolvedValue(undefined) })
    render(<AnswerCard a={answered} />)
    await userEvent.click(screen.getByRole('button', { name: 'Evidence pack (PDF)' }))
    expect((ws as unknown as { exportPack: ReturnType<typeof vi.fn> }).exportPack).toHaveBeenCalledWith(answered)
  })
})
