import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { answered, conflictAnswer, notFound } from '../test/fixtures'
import { AnswerCard } from './AnswerCard'
import { ConfidenceBadge } from './ConfidenceBadge'
import { ProcessingStepper } from './ProcessingStepper'
import { RichText } from './RichText'

const ws = { openSource: vi.fn(), setPinned: vi.fn(), setNote: vi.fn() }
vi.mock('../context/workspace', () => ({ useWorkspace: () => ws }))

beforeEach(() => { Object.values(ws).forEach((f) => f.mockClear()) })

describe('ConfidenceBadge', () => {
  it.each(['HIGH', 'MEDIUM', 'LOW', 'CONFLICTED', 'INSUFFICIENT'] as const)('renders the %s level', (level) => {
    render(<ConfidenceBadge level={level} />)
    expect(screen.getByText(level)).toBeInTheDocument()
  })
})

describe('RichText', () => {
  it('never turns document text into HTML', () => {
    const { container } = render(<RichText text={'<img src=x onerror=alert(1)> and <script>alert(2)</script>'} />)
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('script')).toBeNull()
    expect(container).toHaveTextContent('<img src=x onerror=alert(1)>')
  })

  it('makes citation markers clickable', async () => {
    const onCite = vi.fn()
    render(<RichText text="Net 45 [S3] wins." onCite={onCite} />)
    await userEvent.click(screen.getByRole('button', { name: '3' }))
    expect(onCite).toHaveBeenCalledWith('S3')
  })
})

describe('ProcessingStepper', () => {
  it('shows the OCR step only for scans and reports progress', () => {
    const { rerender } = render(<ProcessingStepper status="CHUNKING" progress={55} ocr={false} />)
    expect(screen.getByText('Chunking…')).toBeInTheDocument()
    expect(screen.getByText('55%')).toBeInTheDocument()
    expect(screen.getByLabelText(/Processing: Chunking/).querySelectorAll('[title]')).toHaveLength(6)
    rerender(<ProcessingStepper status="OCR" progress={35} ocr />)
    expect(screen.getByLabelText(/Processing: Reading scan/).querySelectorAll('[title]')).toHaveLength(7)
  })

  it('renders nothing for failed documents', () => {
    const { container } = render(<ProcessingStepper status="FAILED" progress={100} ocr={false} />)
    expect(container).toBeEmptyDOMElement()
  })
})

describe('AnswerCard', () => {
  it('presents a conflict as positions with sources, an inference-labelled resolution and an evidence matrix', async () => {
    render(<AnswerCard a={conflictAnswer} />)
    expect(screen.getByText('Sources conflict - no single answer')).toBeInTheDocument()
    expect(screen.getByTestId('answer-card')).toHaveAttribute('data-level', 'CONFLICTED')
    expect(screen.getAllByText('Net 30').length).toBeGreaterThan(1)          // headline + position card + matrix row
    expect(screen.getByText(/inference, not stated in the documents/i)).toBeInTheDocument()
    expect(screen.getByText('Evidence matrix')).toBeInTheDocument()
    const rows = within(screen.getByRole('table')).getAllByRole('row')
    expect(rows).toHaveLength(3)                                              // header + two competing claims
    await userEvent.click(rows[2])
    expect(ws.openSource).toHaveBeenCalledWith(expect.objectContaining({ docId: 'd2', docName: 'Amendment.docx' }))
  })

  it('shows engine provenance, OCR quality and opens the cited passage', async () => {
    render(<AnswerCard a={answered} />)
    expect(screen.getByRole('heading', { name: '$1,000,000' })).toBeInTheDocument()
    expect(screen.getByText(/gpt-oss-120b · quotes verified/)).toBeInTheDocument()
    expect(screen.getByText('OCR 82%')).toBeInTheDocument()
    await userEvent.click(screen.getByText('Agreement.pdf'))
    expect(ws.openSource).toHaveBeenCalledWith({ docId: 'd1', docName: 'Agreement.pdf', page: 1, start: 0, end: 34, quote: 'Liability is capped at $1,000,000.' })
  })

  it('says "not found", lists unknown terms, marks leads as not answers and shows the fallback reason', () => {
    render(<AnswerCard a={notFound} />)
    expect(screen.getByText('Not found in the documents')).toBeInTheDocument()
    expect(screen.getByText('cfo')).toBeInTheDocument()
    expect(screen.getByText('related, not an answer')).toBeInTheDocument()
    expect(screen.getByText('rules (LLM fallback)')).toBeInTheDocument()
    expect(screen.getByText(/rate limit was reached/)).toBeInTheDocument()
  })

  it('reveals the reasoning behind the level on demand', async () => {
    render(<AnswerCard a={answered} />)
    expect(screen.queryByText(/Best passage covers/)).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: /Why high/i }))
    expect(screen.getByText(/Best passage covers 100%/)).toBeInTheDocument()
    expect(screen.getByText(/not a probability/)).toBeInTheDocument()
  })

  it('pins an answer', async () => {
    render(<AnswerCard a={answered} />)
    await userEvent.click(screen.getByRole('button', { name: /Pin/ }))
    expect(ws.setPinned).toHaveBeenCalledWith(answered, true)
  })
})
