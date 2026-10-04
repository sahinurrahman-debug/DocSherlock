import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../lib/api'
import { BOARD, layoutBoard, lit } from '../lib/boardLayout'
import type { BoardData, EvidenceRef } from '../lib/types'
import { BoardView } from './BoardView'

const ws = { openSource: vi.fn(), scopeIds: null, documents: [{ id: 'a', status: 'READY', doc_date: '2023-03-03' }], readyDocs: [{ id: 'a' }], loadDemo: vi.fn() }
vi.mock('../context/workspace', () => ({ useWorkspace: () => ws }))

const ev = (doc_id: string, doc_name: string, doc_date: string, value: string, quote: string): EvidenceRef =>
  ({ doc_id, doc_name, doc_date, page: 1, section: '', start: 4, end: 4 + quote.length, quote, value, ocr_conf: null })

const data: BoardData = {
  documents: [
    { id: 'a', name: 'Vendor_Agreement.pdf', doc_date: '2023-03-03', ext: 'pdf', disputes: 1 },
    { id: 'b', name: 'Amendment.docx', doc_date: '2024-01-15', ext: 'docx', disputes: 1 },
    { id: 'e', name: 'Finance_Email.eml', doc_date: '2024-02-02', ext: 'eml', disputes: 1 },
    { id: 'f', name: 'FAQ.html', doc_date: null, ext: 'html', disputes: 0 },
  ],
  disputes: [{
    id: 'c1', title: 'Invoices are payable ___ from the invoice date', severity: 'high', kind: 'value', same_document: false, time_scoped: false,
    resolution: '"Net 45" is the most likely current position: **Amendment.docx** uses amendment wording.', likely_current: 1, basis: 'amendment',
    positions: [
      { index: 0, value: 'Net 30', current: false, corroborated: true, sources: [ev('a', 'Vendor_Agreement.pdf', '2023-03-03', 'Net 30', 'Invoices are payable Net 30.'), ev('e', 'Finance_Email.eml', '2024-02-02', 'Net 30', 'Due Net 30.')] },
      { index: 1, value: 'Net 45', current: true, corroborated: false, sources: [ev('b', 'Amendment.docx', '2024-01-15', 'Net 45', 'Invoices are payable Net 45.')] },
    ],
  }],
  amends: [{ newer_doc_id: 'b', older_doc_id: 'a', points: 3, kind: 'superseded' }],
  stats: { documents: 4, disputes: 1, shown_of: 1, strings: 2 },
}

describe('layoutBoard', () => {
  const L = layoutBoard(data)

  it('puts every dispute in a group with its notes inside it, and nothing overlaps', () => {
    expect(L.groups).toHaveLength(1)
    const g = L.groups[0]
    expect(g.notes.map((n) => n.value)).toEqual(['Net 30', 'Net 45'])
    for (const n of g.notes) { expect(n.x).toBeGreaterThanOrEqual(g.x); expect(n.y).toBeGreaterThanOrEqual(g.y); expect(n.y + n.h).toBeLessThanOrEqual(g.y + g.h); expect(n.x + n.w).toBeLessThanOrEqual(g.x + g.w) }
    expect(g.notes[0].y + g.notes[0].h).toBeLessThan(g.notes[1].y)
    const ys = L.docs.map((d) => d.y)
    expect(ys).toEqual([...ys].sort((a, b) => a - b))
    for (let i = 1; i < L.docs.length; i++) expect(L.docs[i].y - (L.docs[i - 1].y + BOARD.docH)).toBeGreaterThan(0)
  })

  it('draws one string per (document, claim), one red string between conflicting claims, and an amber string for the amendment', () => {
    const kinds = (k: string) => L.strings.filter((s) => s.kind === k)
    expect(kinds('states')).toHaveLength(3)                                  // contract + e-mail -> Net 30, amendment -> Net 45
    expect(kinds('conflicts')).toHaveLength(1)
    expect(kinds('amends')).toHaveLength(1)
    expect(kinds('amends')[0].label).toBe('amends · 3')
    expect(L.strings.every((s) => /^M [\d. -]+ C /.test(s.d))).toBe(true)
  })

  it('keeps documents without disputes on the board, unconnected and last', () => {
    const faq = L.docs.find((d) => d.id === 'f')!
    expect(faq.connected).toBe(false)
    expect(L.docs[L.docs.length - 1].id).toBe('f')
  })

  it('lights up exactly what is connected to the focus', () => {
    expect(lit(L, null)).toBeNull()
    const doc = lit(L, { kind: 'doc', id: 'b' })!
    expect([...doc.docs].sort()).toEqual(['a', 'b'])                         // the amendment and the contract it amends
    expect([...doc.notes]).toEqual(['c1:1'])
    const note = lit(L, { kind: 'note', id: 'c1:0' })!
    expect([...note.docs].sort()).toEqual(['a', 'e']) ; expect(note.strings.size).toBe(3)    // two document strings + the red string to its rival
    const dispute = lit(L, { kind: 'dispute', id: 'c1' })!
    expect(dispute.notes.size).toBe(2) ; expect(dispute.docs.has('f')).toBe(false)
  })
})

describe('BoardView', () => {
  beforeEach(() => { ws.openSource.mockClear(); Object.assign(ws, { readyDocs: [{ id: 'a' }] }); vi.spyOn(api, 'board').mockResolvedValue(data) })

  it('renders documents, claims and the legend', async () => {
    render(<BoardView onAsk={vi.fn()} />)
    expect(await screen.findByRole('group', { name: /1 disputed points across 4 documents/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Document Vendor_Agreement.pdf/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Claim: Net 45, stated by Amendment.docx, likely current/ })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: 'Legend' })).toHaveTextContent('conflicts with')
  })

  it('clicking a claim opens its source and shows the dispute side by side', async () => {
    render(<BoardView onAsk={vi.fn()} />)
    await userEvent.click(await screen.findByRole('button', { name: /Claim: Net 30/ }))
    expect(ws.openSource).toHaveBeenCalledWith(expect.objectContaining({ docId: 'a', docName: 'Vendor_Agreement.pdf', page: 1 }))
    const detail = await screen.findByTestId('board-detail')
    expect(detail).toHaveTextContent('Net 30'); expect(detail).toHaveTextContent('Net 45'); expect(detail).toHaveTextContent('likely current by amendment wording')
  })

  it('can be focused from outside (the case file links here) and can ask about the dispute', async () => {
    const onAsk = vi.fn()
    render(<BoardView focusCluster="c1" onAsk={onAsk} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Ask about this' }))
    expect(onAsk).toHaveBeenCalledWith('Which applies: Net 30 or Net 45? (Invoices are payable ... from the invoice date)')
  })

  it('toggles between fit-to-width and actual size', async () => {
    render(<BoardView onAsk={vi.fn()} />)
    const svg = await screen.findByRole('group', { name: /disputed points/ })
    expect(svg).toHaveStyle({ width: '100%' })
    await userEvent.click(screen.getByRole('button', { name: 'Actual size' }))
    await waitFor(() => expect(svg.style.width).toMatch(/px$/))
  })

  it('has designed empty states', async () => {
    Object.assign(ws, { readyDocs: [] })
    const { unmount } = render(<BoardView onAsk={vi.fn()} />)
    expect(screen.getByRole('heading', { name: 'The board is empty' })).toBeInTheDocument()
    unmount()
    Object.assign(ws, { readyDocs: [{ id: 'a' }] })
    vi.spyOn(api, 'board').mockResolvedValue({ ...data, disputes: [], amends: [] })
    render(<BoardView onAsk={vi.fn()} />)
    expect(await screen.findByRole('heading', { name: 'Nothing to string together' })).toBeInTheDocument()
  })
})
