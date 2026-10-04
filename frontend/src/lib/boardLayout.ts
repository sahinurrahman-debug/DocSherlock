import type { BoardData, BoardDispute } from './types'

/** Pure geometry for the Case Board (no DOM measuring), so it can be unit-tested and always draws the same board for the same data. */
export const BOARD = { padL: 78, docX: 78, docW: 224, docH: 64, groupX: 470, groupW: 440, header: 44, noteH: 62, noteGap: 10, pad: 14, groupGap: 26, top: 24, bottom: 36, loop: 40 }

export interface Box { x: number; y: number; w: number; h: number }
export interface DocNode extends Box { id: string; name: string; doc_date: string | null; connected: boolean }
export interface NoteNode extends Box { key: string; disputeId: string; index: number; value: string; current: boolean; corroborated: boolean; tilt: number; docNames: string[] }
export interface GroupNode extends Box { dispute: BoardDispute; notes: NoteNode[] }
export interface Str { id: string; kind: 'states' | 'conflicts' | 'amends'; d: string; docId?: string; noteKey?: string; disputeId?: string; from?: string; to?: string; label?: string; mid: [number, number] }
export interface Layout { width: number; height: number; docs: DocNode[]; groups: GroupNode[]; strings: Str[] }

const curve = (x1: number, y1: number, x2: number, y2: number) => {
  const dx = Math.max(90, Math.abs(x2 - x1) * 0.45)
  return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`
}
const bez = (t: number, a: number, b: number, c: number, d: number) => (1 - t) ** 3 * a + 3 * (1 - t) ** 2 * t * b + 3 * (1 - t) * t * t * c + t ** 3 * d

export function layoutBoard(data: BoardData): Layout {
  const B = BOARD
  const noteW = B.groupW - 2 * B.pad - B.loop
  const nameOf = new Map(data.documents.map((d) => [d.id, d.name]))

  // 1. dispute groups, stacked on the right
  const groups: GroupNode[] = []
  let y = B.top
  for (const dispute of data.disputes) {
    const k = dispute.positions.length
    const h = B.header + k * B.noteH + (k - 1) * B.noteGap + B.pad
    const notes: NoteNode[] = dispute.positions.map((p, i) => ({
      key: `${dispute.id}:${i}`, disputeId: dispute.id, index: i, value: p.value, current: p.current, corroborated: p.corroborated,
      x: B.groupX + B.pad, y: y + B.header + i * (B.noteH + B.noteGap), w: noteW, h: B.noteH, tilt: ((groups.length * 7 + i * 5) % 5 - 2) * 0.28,
      docNames: [...new Set(p.sources.map((s) => nameOf.get(s.doc_id) ?? s.doc_name))],
    }))
    groups.push({ dispute, notes, x: B.groupX, y, w: B.groupW, h })
    y += h + B.groupGap
  }
  const groupsBottom = y - B.groupGap

  // 2. documents on the left, ordered by where their strings land (fewest crossings), unconnected ones last
  const targets = new Map<string, number[]>()
  for (const g of groups) for (const n of g.notes) for (const s of g.dispute.positions[n.index].sources) targets.set(s.doc_id, [...(targets.get(s.doc_id) ?? []), n.y + n.h / 2])
  const bary = (id: string) => { const t = targets.get(id); return t && t.length ? t.reduce((a, b) => a + b, 0) / t.length : Infinity }
  const ordered = [...data.documents].sort((a, b) => bary(a.id) - bary(b.id) || (a.doc_date ?? '9').localeCompare(b.doc_date ?? '9') || a.name.localeCompare(b.name))
  const need = ordered.length * (B.docH + 14)
  const span = Math.max(groupsBottom - B.top, need)
  const step = ordered.length > 1 ? Math.max(B.docH + 14, (span - B.docH) / (ordered.length - 1)) : 0
  const docs: DocNode[] = ordered.map((d, i) => ({ id: d.id, name: d.name, doc_date: d.doc_date, connected: targets.has(d.id), x: B.docX, y: B.top + i * step, w: B.docW, h: B.docH }))
  const docById = new Map(docs.map((d) => [d.id, d]))
  const docsBottom = docs.length ? docs[docs.length - 1].y + B.docH : B.top

  // 3. strings
  const strings: Str[] = []
  for (const g of groups) {
    for (const n of g.notes) {
      const seen = new Set<string>()
      for (const s of g.dispute.positions[n.index].sources) {
        const doc = docById.get(s.doc_id)
        if (!doc || seen.has(doc.id)) continue
        seen.add(doc.id)
        const x1 = doc.x + doc.w, y1 = doc.y + doc.h / 2, x2 = n.x, y2 = n.y + n.h / 2
        const dx = Math.max(90, Math.abs(x2 - x1) * 0.45)
        strings.push({ id: `s:${doc.id}:${n.key}`, kind: 'states', d: curve(x1, y1, x2, y2), docId: doc.id, noteKey: n.key, disputeId: g.dispute.id,
                       mid: [bez(0.5, x1, x1 + dx, x2 - dx, x2), bez(0.5, y1, y1, y2, y2)] })
      }
    }
    const pairs: [number, number][] = g.notes.length > 1 ? g.notes.slice(0, -1).map((_, i) => [i, i + 1] as [number, number]) : []
    if (g.notes.length > 2) pairs.push([0, g.notes.length - 1])
    pairs.forEach(([i, j]) => {
      const a = g.notes[i], b = g.notes[j]
      const xr = a.x + a.w, ya = a.y + a.h / 2, yb = b.y + b.h / 2, bulge = B.loop - 6 + (j - i - 1) * 4
      strings.push({ id: `c:${g.dispute.id}:${i}-${j}`, kind: 'conflicts', d: `M ${xr} ${ya} C ${xr + bulge} ${ya}, ${xr + bulge} ${yb}, ${xr} ${yb}`, disputeId: g.dispute.id, mid: [xr + bulge * 0.75, (ya + yb) / 2] })
    })
  }
  for (const e of data.amends) {
    const a = docById.get(e.newer_doc_id), o = docById.get(e.older_doc_id)
    if (!a || !o) continue
    const x = a.x, y1 = a.y + a.h / 2, y2 = o.y + o.h / 2, out = 46
    strings.push({ id: `a:${a.id}:${o.id}`, kind: 'amends', d: `M ${x} ${y1} C ${x - out} ${y1}, ${x - out} ${y2}, ${x} ${y2}`, from: a.id, to: o.id,
                   label: `${e.kind === 'superseded' ? 'amends' : 'newer'} · ${e.points}`, mid: [x - out * 0.75, (y1 + y2) / 2] })
  }

  return { width: B.groupX + B.groupW + 36, height: Math.max(groupsBottom, docsBottom) + B.bottom, docs, groups, strings }
}

/** Which ids light up when something is focused (everything else dims). */
export type Focus = { kind: 'doc' | 'dispute' | 'note'; id: string } | null
export interface Lit { docs: Set<string>; disputes: Set<string>; notes: Set<string>; strings: Set<string> }

export function lit(layout: Layout, focus: Focus): Lit | null {
  if (!focus) return null
  const out: Lit = { docs: new Set(), disputes: new Set(), notes: new Set(), strings: new Set() }
  for (const s of layout.strings) {
    const hit = focus.kind === 'doc' ? (s.docId === focus.id || s.from === focus.id || s.to === focus.id)
      : focus.kind === 'dispute' ? s.disputeId === focus.id
      : (s.noteKey === focus.id || (s.kind === 'conflicts' && s.disputeId === focus.id.split(':')[0]))
    if (!hit) continue
    out.strings.add(s.id)
    if (s.docId) out.docs.add(s.docId)
    if (s.from) out.docs.add(s.from)
    if (s.to) out.docs.add(s.to)
    if (s.noteKey) out.notes.add(s.noteKey)
    if (s.disputeId) out.disputes.add(s.disputeId)
  }
  if (focus.kind === 'doc') out.docs.add(focus.id)
  if (focus.kind === 'dispute') { out.disputes.add(focus.id); layout.groups.filter((g) => g.dispute.id === focus.id).forEach((g) => g.notes.forEach((n) => out.notes.add(n.key))) }
  if (focus.kind === 'note') { out.notes.add(focus.id); out.disputes.add(focus.id.split(':')[0]) }
  return out
}
