import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, askStream, parseFrame, sessionId } from './api'
import { blocks, fmtBytes, loc, tokenize } from './format'
import { conflictAnswer } from '../test/fixtures'

describe('answer markup', () => {
  it('tokenizes bold, italic and citation markers', () => {
    expect(tokenize('The **Net 45** term [S2] is *newer*.')).toEqual([
      { t: 'text', v: 'The ' }, { t: 'bold', v: 'Net 45' }, { t: 'text', v: ' term ' }, { t: 'cite', v: 'S2' }, { t: 'text', v: ' is ' }, { t: 'em', v: 'newer' }, { t: 'text', v: '.' },
    ])
  })

  it('splits paragraphs and bullets and ignores blank lines', () => {
    const b = blocks('Intro line\n\n- first [S1]\n- second\nTail')
    expect(b.map((x) => x.kind)).toEqual(['p', 'li', 'li', 'p'])
    expect(b[1].toks.some((t) => t.t === 'cite' && t.v === 'S1')).toBe(true)
  })

  it('leaves markup-looking text from documents as plain text', () => {
    const t = tokenize('<img src=x onerror=alert(1)> 2 * 3 * 4')
    expect(t.every((x) => x.t === 'text' || x.t === 'em')).toBe(true)
    expect(t.map((x) => x.v).join('')).toContain('<img src=x onerror=alert(1)>')
  })

  it('formats sizes and locations', () => {
    expect(fmtBytes(512)).toBe('512 B')
    expect(fmtBytes(2048)).toBe('2 KB')
    expect(fmtBytes(5 * 1024 * 1024)).toBe('5.0 MB')
    expect(loc({ doc_name: 'a.pdf', page: 3, section: 'Fees' })).toBe('a.pdf · p.3 · § Fees')
    expect(loc({ doc_name: 'a.docx', page: null })).toBe('a.docx')
  })
})

describe('session', () => {
  it('creates one anonymous workspace id and keeps it', () => {
    localStorage.clear()
    const a = sessionId()
    expect(a).toMatch(/^ws-[a-f0-9]{24}$/)
    expect(sessionId()).toBe(a)
  })
})

describe('server-sent events', () => {
  it('parses frames and ignores malformed ones', () => {
    expect(parseFrame('event: stage\ndata: {"stage":"retrieving","detail":"x"}')).toEqual({ event: 'stage', data: { stage: 'retrieving', detail: 'x' } })
    expect(parseFrame('event: x\ndata: {not json')).toBeNull()
    expect(parseFrame(': keep-alive')).toBeNull()
  })

  const sse = (events: [string, unknown][], chunk = 17) => {
    const text = events.map(([e, d]) => `event: ${e}\ndata: ${JSON.stringify(d)}\n\n`).join('')
    const enc = new TextEncoder().encode(text)
    return new ReadableStream({ start(c) { for (let i = 0; i < enc.length; i += chunk) c.enqueue(enc.slice(i, i + chunk)); c.close() } })   // frames split mid-way
  }

  afterEach(() => vi.unstubAllGlobals())

  it('streams stages then resolves with the final answer, sending the session header', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(sse([
      ['investigation', { id: 'i1', name: 'Q' }], ['stage', { stage: 'retrieving', detail: 'Searching' }], ['stage', { stage: 'verifying', detail: '' }], ['result', conflictAnswer],
    ]), { status: 200, headers: { 'Content-Type': 'text/event-stream' } }))
    vi.stubGlobal('fetch', fetchMock)
    const stages: string[] = []
    const inv: string[] = []
    const ans = await askStream({ question: 'What are the payment terms?', mode: 'auto', documentIds: ['d1'] }, { onStage: (s) => stages.push(s.stage), onInvestigation: (i) => inv.push(i.id) })
    expect(stages).toEqual(['retrieving', 'verifying'])
    expect(inv).toEqual(['i1'])
    expect(ans.level).toBe('CONFLICTED')
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/questions/stream')
    expect(new Headers(init.headers).get('X-Session-Id')).toBe(sessionId())
    expect(JSON.parse(init.body)).toMatchObject({ question: 'What are the payment terms?', document_ids: ['d1'], mode: 'auto' })
  })

  it('surfaces server-side errors from the stream', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(sse([['error', { detail: 'Investigation not found', status: 404 }]]), { status: 200 })))
    await expect(askStream({ question: 'q', mode: 'auto' })).rejects.toMatchObject({ message: 'Investigation not found', status: 404 })
  })

  it('reports HTTP failures and truncated streams', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'Invalid X-Session-Id header' }), { status: 400 })))
    await expect(askStream({ question: 'q', mode: 'auto' })).rejects.toBeInstanceOf(ApiError)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(sse([['stage', { stage: 'retrieving', detail: '' }]]), { status: 200 })))
    await expect(askStream({ question: 'q', mode: 'auto' })).rejects.toThrow(/before answering/)
  })
})
