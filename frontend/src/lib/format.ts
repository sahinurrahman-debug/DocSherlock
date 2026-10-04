import type { DocStatus, Level } from './types'

export const LEVELS: Record<Level, { label: string; tone: 'ok' | 'warn' | 'bad' | 'none' | 'brand'; hint: string }> = {
  HIGH: { label: 'High confidence', tone: 'ok', hint: 'Explicit, consistent support in the documents.' },
  MEDIUM: { label: 'Medium confidence', tone: 'warn', hint: 'Supported, but by a single source, a scan, or light inference.' },
  LOW: { label: 'Low confidence', tone: 'bad', hint: 'Only indirect or partial support - treat as a lead, not a conclusion.' },
  CONFLICTED: { label: 'Sources conflict', tone: 'bad', hint: 'Documents disagree; no single answer is justified.' },
  INSUFFICIENT: { label: 'Insufficient evidence', tone: 'none', hint: 'The documents do not contain enough to answer.' },
}

export const TONE_CLASS: Record<string, string> = {
  ok: 'bg-ok-soft text-ok',
  warn: 'bg-warn-soft text-warn',
  bad: 'bg-bad-soft text-bad',
  none: 'bg-none-soft text-none',
  brand: 'bg-brand-soft text-brand',
}

export const STAGE_FLOW: DocStatus[] = ['UPLOADED', 'EXTRACTING', 'OCR', 'CHUNKING', 'EMBEDDING', 'INDEXING', 'READY']

export const STAGE_LABEL: Record<DocStatus, string> = {
  UPLOADED: 'Queued', PROCESSING: 'Starting', EXTRACTING: 'Extracting text', OCR: 'Reading scan (OCR)', CHUNKING: 'Chunking',
  EMBEDDING: 'Embedding', INDEXING: 'Indexing', READY: 'Ready', FAILED: 'Failed',
}

export const isBusy = (s: DocStatus) => s !== 'READY' && s !== 'FAILED'

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

export function fmtWhen(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const diff = (Date.now() - d.getTime()) / 1000
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export const pct = (x: number | null | undefined) => (x == null ? '' : `${Math.round(x * 100)}%`)

export function loc(c: { doc_name: string; page: number | null; section?: string }): string {
  return [c.doc_name, c.page ? `p.${c.page}` : null, c.section ? `§ ${c.section}` : null].filter(Boolean).join(' · ')
}

// ---- inline markup used by answers: **bold**, *italic*, [S1] citation markers, "- " bullets ---------------------------------
export type Tok = { t: 'text' | 'bold' | 'em' | 'cite'; v: string }
export type Block = { kind: 'p' | 'li'; toks: Tok[] }

export function tokenize(line: string): Tok[] {
  const out: Tok[] = []
  const re = /(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|\[S\d+\])/g
  let last = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(line))) {
    if (m.index > last) out.push({ t: 'text', v: line.slice(last, m.index) })
    const s = m[0]
    if (s.startsWith('**')) out.push({ t: 'bold', v: s.slice(2, -2) })
    else if (s.startsWith('[S')) out.push({ t: 'cite', v: s.slice(1, -1) })
    else out.push({ t: 'em', v: s.slice(1, -1) })
    last = m.index + s.length
  }
  if (last < line.length) out.push({ t: 'text', v: line.slice(last) })
  return out
}

export function blocks(text: string): Block[] {
  const out: Block[] = []
  for (const raw of text.split('\n')) {
    const line = raw.trimEnd()
    if (!line.trim()) continue
    const li = /^\s*-\s+/.test(line)
    out.push({ kind: li ? 'li' : 'p', toks: tokenize(li ? line.replace(/^\s*-\s+/, '') : line) })
  }
  return out
}

export function dateOnly(iso: string | null | undefined): string {
  return iso ?? ''
}
