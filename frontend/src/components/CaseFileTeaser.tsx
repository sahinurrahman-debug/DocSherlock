import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useWorkspace } from '../context/workspace'
import { api } from '../lib/api'
import type { CaseFileData } from '../lib/types'
import { Skeleton } from './Skeleton'

const DOT = { high: 'bg-bad', medium: 'bg-warn', low: 'bg-none' } as const

/** Dashboard highlight: the top findings of the case file, so the first thing a visitor sees is what the documents are hiding. */
export function CaseFileTeaser() {
  const { readyDocs, documents } = useWorkspace()
  const [data, setData] = useState<CaseFileData | null>(null)
  const key = readyDocs.map((d) => d.id + (d.doc_date ?? '')).join()

  useEffect(() => {
    let alive = true
    if (!readyDocs.length) { setData(null); return }
    api.casefile().then((d) => alive && setData(d)).catch(() => alive && setData(null))
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  if (!readyDocs.length && documents.length === 0) return null
  return (
    <section className="card rise p-6 sm:p-7" style={{ '--i': 4 } as React.CSSProperties} aria-label="Case file highlights">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-2xl font-semibold">What needs your attention</h2>
        <Link to="/investigate" className="link text-sm">Open the case file</Link>
      </div>
      {!data ? <div className="mt-4 space-y-3" role="status" aria-label="Loading"><Skeleton className="h-6 w-full" /><Skeleton className="h-6 w-5/6" /><Skeleton className="h-6 w-2/3" /></div> : (
        <>
          <p className="mt-2 text-base text-muted">{data.briefing}</p>
          <ul className="mt-4 space-y-2.5">
            {data.findings.slice(0, 3).map((f) => (
              <li key={f.id} className="flex items-start gap-3">
                <span className={`mt-2 h-2.5 w-2.5 shrink-0 rounded-full ${DOT[f.severity]}`} aria-label={`${f.severity} priority`} />
                <span className="text-base font-medium leading-snug">{f.title}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}
