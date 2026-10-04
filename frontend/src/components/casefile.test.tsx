import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../lib/api'
import type { CaseFileData } from '../lib/types'
import { CaseFile } from './CaseFile'

const ws = { openSource: vi.fn(), scopeIds: null as string[] | null, documents: [{ id: 'd1', status: 'READY', doc_date: null }], readyDocs: [{ id: 'd1' }], loadDemo: vi.fn() }
vi.mock('../context/workspace', () => ({ useWorkspace: () => ws }))

const data: CaseFileData = {
  briefing: '11 documents and 67 claims checked. 10 points are disputed, touching 9 documents (3 high severity).',
  stats: { documents: 11, claims: 67, disputed_points: 10, high_severity: 3, documents_in_dispute: 9, corroborated_points: 1, superseded_documents: 1, scans: 2, undated: 1 },
  findings: [
    { id: 'conflict-a', type: 'conflict', severity: 'high', title: 'Invoices are payable ___ from the invoice date: Net 30 vs Net 45', cluster_id: 'a',
      detail: '"Net 45" is the most likely current position: **Contract_Amendment_No1.docx** uses amendment wording.', question: 'What do the documents say about payment terms?',
      evidence: [{ doc_id: 'd1', doc_name: 'Vendor_Agreement.pdf', doc_date: '2023-03-03', page: 1, section: 'Payment', start: 10, end: 62, quote: 'Invoices are payable Net 30 from the invoice date.', value: 'Net 30', ocr_conf: null },
                 { doc_id: 'd2', doc_name: 'Amendment.docx', doc_date: '2024-01-15', page: null, section: '', start: 0, end: 40, quote: 'Invoices are payable Net 45.', value: 'Net 45', ocr_conf: null }] },
    { id: 'undated', type: 'undated', severity: 'low', title: '1 document without a date', detail: '**Company_FAQ.html**: without a date it cannot be ordered.', evidence: [] },
  ],
  findings_total: 4, omitted_conflicts: 2, documents: [], suggested_questions: ['Do any documents contradict each other?'],
}

beforeEach(() => {
  Object.assign(ws, { scopeIds: null, readyDocs: [{ id: 'd1' }] })
  ws.openSource.mockClear()
  vi.spyOn(api, 'casefile').mockResolvedValue(data)
})

describe('CaseFile', () => {
  it('shows a loading skeleton, then the briefing, stats and findings', async () => {
    render(<CaseFile onAsk={vi.fn()} />)
    expect(screen.getAllByRole('status', { name: 'Loading' }).length).toBeGreaterThan(0)
    expect(await screen.findByTestId('briefing')).toHaveTextContent('10 points are disputed')
    expect(screen.getByText('10 disputed')).toBeInTheDocument()
    const cards = screen.getAllByTestId('finding')
    expect(cards).toHaveLength(2)
    expect(cards[0]).toHaveAttribute('data-severity', 'high')
    expect(within(cards[0]).getByText(/Net 30 vs Net 45/)).toBeInTheDocument()
    expect(within(cards[0]).getByText('Contract_Amendment_No1.docx').tagName).toBe('STRONG')       // **bold** is rendered, never as raw markup
  })

  it('opens the exact passage when evidence is clicked', async () => {
    render(<CaseFile onAsk={vi.fn()} />)
    await userEvent.click(await screen.findByRole('button', { name: /Vendor_Agreement\.pdf/ }))
    expect(ws.openSource).toHaveBeenCalledWith({ docId: 'd1', docName: 'Vendor_Agreement.pdf', page: 1, start: 10, end: 62, quote: 'Invoices are payable Net 30 from the invoice date.' })
  })

  it('turns a finding or a suggested question into an ask', async () => {
    const onAsk = vi.fn()
    render(<CaseFile onAsk={onAsk} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Ask about this' }))
    expect(onAsk).toHaveBeenCalledWith('What do the documents say about payment terms?')
    await userEvent.click(screen.getByRole('button', { name: 'Do any documents contradict each other?' }))
    expect(onAsk).toHaveBeenLastCalledWith('Do any documents contradict each other?')
  })

  it('offers the case board for a dispute and points to the rest on the Conflict board', async () => {
    const onBoard = vi.fn(); const onConflicts = vi.fn()
    render(<CaseFile onAsk={vi.fn()} onBoard={onBoard} onConflicts={onConflicts} />)
    await userEvent.click(await screen.findByRole('button', { name: 'See on the case board' }))
    expect(onBoard).toHaveBeenCalledWith('a')
    await userEvent.click(screen.getByRole('button', { name: /see them all on the Conflict board/ }))
    expect(onConflicts).toHaveBeenCalled()
  })

  it('designs the empty states: no documents, and nothing to report', async () => {
    Object.assign(ws, { readyDocs: [] })
    const { unmount } = render(<CaseFile onAsk={vi.fn()} />)
    expect(screen.getByRole('heading', { name: 'Your case file starts with documents' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Load the sample set' }))
    expect(ws.loadDemo).toHaveBeenCalled()
    unmount()

    Object.assign(ws, { readyDocs: [{ id: 'd1' }] })
    vi.spyOn(api, 'casefile').mockResolvedValue({ ...data, findings: [], omitted_conflicts: 0, suggested_questions: [] })
    render(<CaseFile onAsk={vi.fn()} />)
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Nothing needs attention' })).toBeInTheDocument())
  })
})
