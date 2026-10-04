import { act, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from '../lib/api'
import type { DocumentInfo, UploadItem } from '../lib/types'
import { FileUploader } from './FileUploader'

type Ctx = { upload: () => void; loadDemo: () => void; health: null; uploading: UploadItem[]; documents: DocumentInfo[] }
let ctx: Ctx
vi.mock('../context/workspace', () => ({ useWorkspace: () => ctx }))

const doc = (over: Partial<DocumentInfo>): DocumentInfo => ({
  id: 'd1', filename: 'Contract.pdf', file_type: '.pdf', file_size: 1000, status: 'READY', progress: 100, error: null, uploaded_at: '2026-01-01T00:00:00',
  n_pages: 1, paged: true, n_chunks: 1, n_claims: 1, ocr_used: false, ocr_conf: null, doc_date: null, doc_date_source: null, title: null, warnings: [], indexed: true, ...over,
} as DocumentInfo)

beforeEach(() => { ctx = { upload: vi.fn(), loadDemo: vi.fn(), health: null, uploading: [], documents: [] } })

describe('FileUploader progress', () => {
  it('shows the plain drop prompt while idle', () => {
    render(<FileUploader />)
    expect(screen.getByText(/Drop files here/)).toBeInTheDocument()
    expect(screen.queryByTestId('upload-progress')).toBeNull()
  })

  it('shows each file being sent, by name, with a completion bar', () => {
    ctx.uploading = [{ id: 'u1', name: 'Handbook.docx', progress: 0.42 }]
    render(<FileUploader />)
    const bar = screen.getByRole('progressbar', { name: 'Handbook.docx: Uploading…' })
    expect(bar).toHaveAttribute('aria-valuenow', '42')
    expect(screen.getByText('Handbook.docx')).toBeInTheDocument()
    expect(screen.getByText('42%')).toBeInTheDocument()
    expect(screen.queryByText(/Drop files here/)).toBeNull()
  })

  it('then follows the server-side stages of a document that is still processing', () => {
    ctx.documents = [doc({ id: 'd2', filename: 'Scan.pdf', status: 'OCR', progress: 35, ocr_used: true }), doc({ id: 'd3', filename: 'Done.pdf' })]
    render(<FileUploader />)
    expect(screen.getByRole('progressbar', { name: 'Scan.pdf: Reading scan (OCR)…' })).toHaveAttribute('aria-valuenow', '35')
    expect(screen.queryByText('Done.pdf')).toBeNull()                      // documents that were already READY are not listed
  })

  it('keeps a finished file on screen briefly as Ready, then clears it', () => {
    vi.useFakeTimers()
    try {
      ctx.documents = [doc({ filename: 'Fast.pdf', status: 'CHUNKING', progress: 55 })]
      const { rerender } = render(<FileUploader />)
      expect(screen.getByText('55%')).toBeInTheDocument()
      ctx = { ...ctx, documents: [doc({ filename: 'Fast.pdf', status: 'READY', progress: 100 })] }
      rerender(<FileUploader />)
      expect(screen.getByText('Ready to question')).toBeInTheDocument()
      act(() => { vi.advanceTimersByTime(4000) })
      expect(screen.queryByText('Ready to question')).toBeNull()
      expect(screen.getByText(/Drop files here/)).toBeInTheDocument()
    } finally { vi.useRealTimers() }
  })

  it('summarises long queues instead of growing without bound', () => {
    ctx.documents = Array.from({ length: 7 }, (_, i) => doc({ id: `q${i}`, filename: `File${i}.pdf`, status: 'UPLOADED', progress: 5 }))
    render(<FileUploader />)
    expect(within(screen.getByTestId('upload-progress')).getAllByRole('progressbar')).toHaveLength(4)
    expect(screen.getByText('+ 3 more files…')).toBeInTheDocument()
  })
})

describe('api.documents.upload progress', () => {
  class FakeXHR {
    static last: FakeXHR
    upload: { onprogress: ((e: { lengthComputable: boolean; loaded: number; total: number }) => void) | null } = { onprogress: null }
    onload: (() => void) | null = null
    onerror: (() => void) | null = null
    status = 0
    statusText = ''
    responseText = ''
    headers: Record<string, string> = {}
    method = ''
    url = ''
    constructor() { FakeXHR.last = this }
    open(m: string, u: string) { this.method = m; this.url = u }
    setRequestHeader(k: string, v: string) { this.headers[k] = v }
    send() { /* the test drives events */ }
    onabort = null
    ontimeout = null
  }
  const realXHR = globalThis.XMLHttpRequest
  beforeEach(() => { globalThis.XMLHttpRequest = FakeXHR as unknown as typeof XMLHttpRequest })
  afterEach(() => { globalThis.XMLHttpRequest = realXHR })

  it('reports bytes sent, sends the session header, and resolves with the server response', async () => {
    const seen: number[] = []
    const p = api.documents.upload([new File(['hello'], 'a.txt')], (loaded, total) => seen.push(loaded / total))
    const x = FakeXHR.last
    expect(x.method).toBe('POST'); expect(x.url).toBe('/api/documents/upload'); expect(x.headers['X-Session-Id']).toMatch(/^ws-/)
    x.upload.onprogress?.({ lengthComputable: true, loaded: 25, total: 100 })
    x.upload.onprogress?.({ lengthComputable: true, loaded: 100, total: 100 })
    x.status = 202; x.responseText = JSON.stringify({ results: [], documents: [] }); x.onload?.()
    await expect(p).resolves.toEqual({ results: [], documents: [] })
    expect(seen).toEqual([0.25, 1, 1])
  })

  it('turns an API error into an ApiError with the server message', async () => {
    const p = api.documents.upload([new File(['x'], 'a.txt')])
    const x = FakeXHR.last
    x.status = 413; x.responseText = JSON.stringify({ detail: 'File is too large' }); x.onload?.()
    await expect(p).rejects.toMatchObject({ message: 'File is too large', status: 413 })
    await p.catch((e) => expect(e).toBeInstanceOf(ApiError))
  })

  it('reports a network failure', async () => {
    const p = api.documents.upload([new File(['x'], 'a.txt')])
    FakeXHR.last.onerror?.()
    await expect(p).rejects.toThrow(/Network error/)
  })
})
