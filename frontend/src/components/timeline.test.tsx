import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../lib/api'
import type { TimelineData, TopicSnapshot } from '../lib/types'
import { TimelineView } from './TimelineView'

const ws = { openSource: vi.fn(), scopeIds: null, documents: [{ id: 'a', status: 'READY', doc_date: '2023-03-03' }], readyDocs: [{ id: 'a' }] }
vi.mock('../context/workspace', () => ({ useWorkspace: () => ws }))

const src = { doc_id: 'a', doc_name: 'Vendor_Agreement.pdf', doc_date: '2023-03-03', page: 1, section: '', start: 3, end: 40, quote: 'Invoices are payable Net 30.', value: 'Net 30', ocr_conf: null }
const base: TimelineData = {
  documents: [
    { id: 'a', name: 'Vendor_Agreement.pdf', doc_date: '2023-03-03', key: '2023-03-03', dated: true, introduces: [] },
    { id: 'b', name: 'Amendment.docx', doc_date: '2024-01-15', key: '2024-01-15', dated: true, introduces: [{ cluster_id: 'c1', title: 'Invoices are payable ___', value: 'Net 45' }] },
    { id: 'f', name: 'FAQ.html', doc_date: null, key: '', dated: false, introduces: [] },
  ],
  range: { min: '2023-03-03', max: '2024-01-15' }, undated: ['FAQ.html'], topics: [],
}
const topic = (day: string): TopicSnapshot => day < '2024-01-15'
  ? { cluster_id: 'c1', title: 'Invoices are payable ___', label: 'Payment', kind: 'value', severity: 'high', status: 'settled', value: 'Net 30', basis: 'only position documented by then', source: src, note: '',
      upcoming: [{ value: 'Net 45', date: '2024-01-15', doc_name: 'Amendment.docx', doc_id: 'b' }], positions_known: 1 }
  : { cluster_id: 'c1', title: 'Invoices are payable ___', label: 'Payment', kind: 'value', severity: 'high', status: 'likely', value: 'Net 45', basis: 'amendment wording',
      source: { ...src, doc_id: 'b', doc_name: 'Amendment.docx', doc_date: '2024-01-15', value: 'Net 45' }, note: '', alternatives: ['Net 30'], upcoming: [], positions_known: 2 }

beforeEach(() => {
  ws.openSource.mockClear()
  vi.spyOn(api, 'timeline').mockImplementation(async (asOf) => asOf
    ? { ...base, as_of: { date: asOf, documents_used: asOf < '2024-01-15' ? 1 : 2, documents_total: 3, topics: [topic(asOf)], excluded: [{ doc_id: 'f', name: 'FAQ.html', doc_date: null, reason: 'undated' }] } }
    : base)
})

describe('TimelineView', () => {
  it('starts at the latest date and shows what is in force then', async () => {
    render(<TimelineView onAsk={vi.fn()} />)
    expect(await screen.findByTestId('as-of-date')).toHaveTextContent('15 Jan 2024')
    const card = await screen.findByTestId('topic')
    expect(within(card).getByText('Net 45')).toBeInTheDocument()
    expect(within(card).getByText('Likely in force')).toBeInTheDocument()
    expect(within(card).getByText('amendment wording')).toBeInTheDocument()
    expect(screen.getByText('2 of 3 documents existed by then')).toBeInTheDocument()
  })

  it('moving back in time flips the value, highlights what changed, and lists what is still to come', async () => {
    render(<TimelineView onAsk={vi.fn()} />)
    await screen.findByTestId('topic')
    await userEvent.click(screen.getByRole('button', { name: '‹ Previous change' }))
    await waitFor(() => expect(screen.getByTestId('topic')).toHaveAttribute('data-status', 'settled'))
    const card = screen.getByTestId('topic')
    expect(within(card).getByText('Net 30')).toBeInTheDocument()
    expect(card).toHaveAttribute('data-changed', 'true')
    expect(within(card).getByText('changed')).toBeInTheDocument()
    expect(within(card).getByText(/Net 45 from 15 Jan 2024/)).toBeInTheDocument()
    expect(screen.getByText('FAQ.html')).toBeInTheDocument()                       // undated files are listed as left out
  })

  it('jumps to a document by clicking its dot, and back to the latest', async () => {
    render(<TimelineView onAsk={vi.fn()} />)
    await screen.findByTestId('topic')
    await userEvent.click(screen.getByRole('button', { name: /Jump to Vendor_Agreement.pdf, 2023-03-03/ }))
    await waitFor(() => expect(screen.getByTestId('as-of-date')).toHaveTextContent('3 Mar 2023'))
    await userEvent.click(screen.getByRole('button', { name: 'Latest' }))
    await waitFor(() => expect(screen.getByTestId('as-of-date')).toHaveTextContent('15 Jan 2024'))
  })

  it('opens the supporting source and asks a question as of the chosen date', async () => {
    const onAsk = vi.fn()
    render(<TimelineView onAsk={onAsk} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Amendment.docx' }))
    expect(ws.openSource).toHaveBeenCalledWith(expect.objectContaining({ docId: 'b', docName: 'Amendment.docx', page: 1 }))
    await userEvent.type(screen.getByLabelText(/Ask a question as of/), 'What are the payment terms?')
    await userEvent.click(screen.getByRole('button', { name: 'Ask as of this date' }))
    expect(onAsk).toHaveBeenCalledWith('What are the payment terms?', '2024-01-15')
  })

  it('has designed empty states', async () => {
    ws.readyDocs = []
    const { unmount } = render(<TimelineView onAsk={vi.fn()} />)
    expect(screen.getByRole('heading', { name: 'Time travel needs dated documents' })).toBeInTheDocument()
    unmount()
    ws.readyDocs = [{ id: 'a' }]
    vi.spyOn(api, 'timeline').mockResolvedValue({ ...base, documents: [{ ...base.documents[2] }], range: { min: null, max: null } })
    render(<TimelineView onAsk={vi.fn()} />)
    expect(await screen.findByRole('heading', { name: 'None of these documents has a date' })).toBeInTheDocument()
  })
})
