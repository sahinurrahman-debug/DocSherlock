import type {
  Answer, ClaimInfo, Comparison, ConflictCluster, DocumentInfo, Health, Investigation, InvestigationDetail, Mode, PageData, StageEvent, UploadResponse,
} from './types'

const BASE: string = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? ''
const KEY = 'docsherlock.session'

/** Anonymous per-browser workspace id: every record on the server is scoped to it. */
export function sessionId(): string {
  try {
    let id = localStorage.getItem(KEY)
    if (!id) {
      id = 'ws-' + crypto.randomUUID().replace(/-/g, '').slice(0, 24)
      localStorage.setItem(KEY, id)
    }
    return id
  } catch {
    return 'ws-ephemeral-session'
  }
}

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

function headers(extra?: HeadersInit): Headers {
  const h = new Headers(extra)
  h.set('X-Session-Id', sessionId())
  return h
}

async function fail(res: Response): Promise<never> {
  let msg = res.statusText || `HTTP ${res.status}`
  try {
    const j = await res.json()
    const d = j?.detail
    msg = typeof d === 'string' ? d : Array.isArray(d) ? d.map((x: { msg?: string }) => x.msg).join('; ') : msg
  } catch {
    /* body was not JSON */
  }
  throw new ApiError(msg, res.status)
}

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(BASE + path, { ...init, headers: headers(init.headers) })
  if (!res.ok) await fail(res)
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T)
}

const json = (body: unknown): RequestInit => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

export async function fetchBlob(path: string): Promise<Blob> {
  const res = await fetch(BASE + path, { headers: headers() })
  if (!res.ok) await fail(res)
  return res.blob()
}

export async function downloadFile(path: string, filename: string): Promise<void> {
  const url = URL.createObjectURL(await fetchBlob(path))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 2000)
}

export const api = {
  health: () => req<Health>('/api/health'),

  documents: {
    list: () => req<DocumentInfo[]>('/api/documents'),
    upload: (files: File[]) => {
      const fd = new FormData()
      files.forEach((f) => fd.append('files', f))
      return req<UploadResponse>('/api/documents/upload', { method: 'POST', body: fd })
    },
    demo: () => req<UploadResponse>('/api/documents/demo', { method: 'POST' }),
    remove: (id: string) => req<void>(`/api/documents/${id}`, { method: 'DELETE' }),
    reset: () => req<void>('/api/documents', { method: 'DELETE' }),
    setDate: (id: string, doc_date: string | null) => req<DocumentInfo>(`/api/documents/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ doc_date }) }),
    page: (id: string, n: number) => req<PageData>(`/api/documents/${id}/pages/${n}`),
    claims: (id: string) => req<ClaimInfo[]>(`/api/documents/${id}/claims`),
    pageImage: (id: string, n: number, start?: number, end?: number) =>
      fetchBlob(`/api/documents/${id}/pages/${n}/image?start=${start ?? -1}&end=${end ?? -1}`),
    original: (id: string, name: string) => downloadFile(`/api/documents/${id}/file`, name),
  },

  conflicts: (ids?: string[]) =>
    req<{ conflicts: ConflictCluster[]; documents: number; claims: number }>('/api/conflicts' + (ids?.length ? `?document_ids=${ids.join(',')}` : '')),

  compare: (a: string, b: string) => req<Comparison>('/api/compare', json({ document_a: a, document_b: b, use_llm: true })),

  investigations: {
    list: () => req<Investigation[]>('/api/investigations'),
    create: (name?: string) => req<Investigation>('/api/investigations', json({ name })),
    get: (id: string) => req<InvestigationDetail>(`/api/investigations/${id}`),
    rename: (id: string, name: string) => req<Investigation>(`/api/investigations/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) }),
    remove: (id: string) => req<void>(`/api/investigations/${id}`, { method: 'DELETE' }),
    report: (id: string, pinnedOnly = false) => downloadFile(`/api/investigations/${id}/report?pinned_only=${pinnedOnly}`, 'docsherlock-report.md'),
  },

  questions: {
    patch: (id: string, body: { pinned?: boolean; note?: string }) => req<Answer>(`/api/questions/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
    remove: (id: string) => req<void>(`/api/questions/${id}`, { method: 'DELETE' }),
  },
}

export interface AskArgs {
  question: string
  investigationId?: string | null
  documentIds?: string[] | null
  mode: Mode
}

export interface AskHandlers {
  onInvestigation?: (inv: { id: string; name: string }) => void
  onStage?: (s: StageEvent) => void
  signal?: AbortSignal
}

/** POST /api/questions/stream - Server-Sent Events: live pipeline stages, then the final answer. */
export async function askStream(args: AskArgs, h: AskHandlers = {}): Promise<Answer> {
  const res = await fetch(BASE + '/api/questions/stream', {
    ...json({ question: args.question, investigation_id: args.investigationId ?? null, document_ids: args.documentIds ?? null, mode: args.mode }),
    headers: headers({ 'Content-Type': 'application/json', Accept: 'text/event-stream' }),
    signal: h.signal,
  })
  if (!res.ok || !res.body) await fail(res)
  const reader = res.body!.getReader()
  const dec = new TextDecoder()
  let buf = ''
  let result: Answer | null = null
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    let i: number
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const frame = buf.slice(0, i)
      buf = buf.slice(i + 2)
      const ev = parseFrame(frame)
      if (!ev) continue
      if (ev.event === 'stage') h.onStage?.(ev.data as StageEvent)
      else if (ev.event === 'investigation') h.onInvestigation?.(ev.data as { id: string; name: string })
      else if (ev.event === 'result') result = ev.data as Answer
      else if (ev.event === 'error') throw new ApiError((ev.data as { detail?: string }).detail ?? 'Request failed', (ev.data as { status?: number }).status ?? 500)
    }
  }
  if (!result) throw new ApiError('The server closed the connection before answering.', 502)
  return result
}

export function parseFrame(frame: string): { event: string; data: unknown } | null {
  let event = 'message'
  const data: string[] = []
  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) data.push(line.slice(5).trim())
  }
  if (!data.length) return null
  try {
    return { event, data: JSON.parse(data.join('\n')) }
  } catch {
    return null
  }
}
