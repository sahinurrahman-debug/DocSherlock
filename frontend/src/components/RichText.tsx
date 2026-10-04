import { Fragment } from 'react'
import { blocks, type Tok } from '../lib/format'

export function CiteChip({ id, onClick, muted = false }: { id: string; onClick?: () => void; muted?: boolean }) {
  return (
    <button
      type="button" onClick={onClick} title={`Open source ${id}`}
      className={`mx-0.5 inline-flex min-w-[18px] items-center justify-center rounded-md px-1 py-0.5 align-[1px] text-[10.5px] font-bold leading-none transition ${muted ? 'bg-none-soft text-none' : 'bg-brand-soft text-brand'} hover:bg-brand hover:text-brand-ink`}
    >
      {id.replace(/^S/, '')}
    </button>
  )
}

function Inline({ toks, onCite }: { toks: Tok[]; onCite?: (id: string) => void }) {
  return (
    <>
      {toks.map((t, i) => {
        if (t.t === 'bold') return <strong key={i}>{t.v}</strong>
        if (t.t === 'em') return <em key={i}>{t.v}</em>
        if (t.t === 'cite') return <CiteChip key={i} id={t.v} onClick={() => onCite?.(t.v)} />
        return <Fragment key={i}>{t.v}</Fragment>
      })}
    </>
  )
}

/** Renders answer text with **bold**, *italic*, bullets and clickable [S#] citation chips. Never uses innerHTML. */
export function RichText({ text, onCite }: { text: string; onCite?: (id: string) => void }) {
  const bs = blocks(text)
  const out: React.ReactNode[] = []
  let items: React.ReactNode[] = []
  const flush = (k: number) => { if (items.length) { out.push(<ul key={`u${k}`} className="mb-2 list-disc space-y-1 pl-5">{items}</ul>); items = [] } }
  bs.forEach((b, i) => {
    if (b.kind === 'li') items.push(<li key={i}><Inline toks={b.toks} onCite={onCite} /></li>)
    else { flush(i); out.push(<p key={i} className="mb-2 last:mb-0"><Inline toks={b.toks} onCite={onCite} /></p>) }
  })
  flush(bs.length)
  return <div className="text-[14px] leading-relaxed">{out}</div>
}
