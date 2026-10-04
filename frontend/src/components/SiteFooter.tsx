import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useWorkspace } from '../context/workspace'
import { Logo } from './Logo'

export const REPO_URL = 'https://github.com/sahinurrahman-debug/DocSherlock'
export const COPYRIGHT_START = 2026
export const LEGAL_UPDATED = '4 October 2026'

/** Identical to the LICENSE file at the repository root (a test keeps them in sync). */
export const MIT_TEXT = `MIT License

Copyright (c) ${COPYRIGHT_START} DocSherlock contributors

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.`

type PanelId = 'terms' | 'privacy' | 'license'

function Item({ title, children }: { title: string; children: ReactNode }) {
  return <li className="leading-relaxed"><strong className="font-semibold text-ink">{title}</strong> {children}</li>
}

function Terms() {
  return (
    <>
      <p>By using DocSherlock you agree to these conditions. If you run your own copy you are its operator, and these conditions are yours to adapt.</p>
      <ol className="mt-3 list-decimal space-y-2.5 pl-5">
        <Item title="A prototype, provided as is.">DocSherlock is an early-stage prototype. It comes without warranty of any kind, as set out in the MIT License, and may be slow, unavailable or reset at any time.</Item>
        <Item title="Answers can be wrong.">Answers, confidence levels, conflict findings and “likely current” suggestions are produced by software, including a language model, and can be incomplete or mistaken. Always open the cited passage and check it against the original document. Do not rely on DocSherlock alone for legal, financial, medical or other decisions that matter.</Item>
        <Item title="What you may upload.">Only documents you have the right to use and to share with the services listed in the privacy notice. Do not upload confidential, personal, health, payment or otherwise sensitive material to a public demo - use the sample set, or your own self-hosted copy.</Item>
        <Item title="Acceptable use.">No unlawful content. No attempts to reach other visitors&apos; data, to overload the service, to scrape it, or to get around its limits (the free hosting tiers it runs on have strict quotas). No use of it to attack other systems.</Item>
        <Item title="Retention.">On a public demo, documents and answers may be deleted automatically after a retention period (14 days in the provided deployment configuration) or whenever the operator resets the service. Keep your own copies.</Item>
        <Item title="Third-party services.">Where enabled, the language-model and embedding providers named in the privacy notice process your content under their own terms.</Item>
        <Item title="Changes.">These conditions may change. Continuing to use DocSherlock means you accept the current version.</Item>
      </ol>
    </>
  )
}

function Privacy() {
  return (
    <>
      <p>DocSherlock needs no account. This notice explains what happens to what you give it.</p>
      <ul className="mt-3 list-disc space-y-2.5 pl-5">
        <Item title="What is stored.">The files you upload (kept so the page viewer can show the original), the text, figures and dates extracted from them, your questions, the answers, and your pins and notes. DocSherlock does not ask for or store your name, e-mail address or any account details.</Item>
        <Item title="How it is tied to you.">Only through a random workspace ID created in your browser and sent with each request. It is not linked to your identity; clearing your browser&apos;s site data starts a fresh, empty workspace (the earlier data stays on the server until it is deleted or purged).</Item>
        <Item title="Where it lives.">In the database and vector index of whoever runs this copy. On the public demo that is Neon (PostgreSQL), Qdrant Cloud and Render. A self-hosted copy keeps everything where you run it.</Item>
        <Item title="Who else processes it.">
          <span className="block">Groq - your question and the retrieved passages (not whole files) when an answer is written, and when you press Red-team.</span>
          <span className="block">Jina - the text of your documents, to compute embeddings, when hosted embeddings are switched on.</span>
          <span className="block">Google Fonts - your browser loads the typefaces from Google, which therefore sees your IP address and browser details.</span>
          <span className="block">Render - ordinary hosting logs (IP addresses, request times).</span>
          <span className="block">The rule-based engine, OCR and the local models run on the server and send nothing elsewhere.</span>
        </Item>
        <Item title="Cookies and tracking.">DocSherlock sets no cookies and uses no analytics, advertising or tracking. Your browser&apos;s local storage holds your workspace ID, your light/dark choice, the answer engine you picked and your last investigation - nothing else.</Item>
        <Item title="Your choices.">Remove a document (the × in the document list, or “clear all”) to delete its file, text and vectors; delete an investigation to delete its answers. Anything older than the retention period is purged automatically. To ask for anything else to be erased, open an issue at <a className="link" href={`${REPO_URL}/issues`} target="_blank" rel="noreferrer">the repository</a>, quoting your workspace ID (browser storage key <code className="rounded bg-surface-2 px-1.5 py-0.5 text-xs">docsherlock.session</code>).</Item>
        <Item title="No sale of data.">Your content is shared only with the processors listed above, to provide the features you use.</Item>
      </ul>
    </>
  )
}

function License() {
  return (
    <>
      <p>DocSherlock is free and open-source software, released under the MIT License. The full text is also in the <a className="link" href={`${REPO_URL}/blob/main/LICENSE`} target="_blank" rel="noreferrer">LICENSE file</a>.</p>
      <pre className="scroll-thin mt-3 max-h-72 overflow-auto whitespace-pre-wrap rounded-xl bg-surface-2 p-4 font-mono text-xs leading-relaxed text-ink" data-testid="mit-text">{MIT_TEXT}</pre>
      <p className="mt-3 text-sm">Third-party components keep their own licences - for example PyMuPDF is licensed under the AGPL or a commercial licence. See the repository&apos;s README for the full list.</p>
    </>
  )
}

const PANELS: { id: PanelId; label: string; title: string; body: ReactNode }[] = [
  { id: 'terms', label: 'Conditions of use', title: 'Conditions of use', body: <Terms /> },
  { id: 'privacy', label: 'Privacy notice', title: 'Privacy notice', body: <Privacy /> },
  { id: 'license', label: 'MIT License', title: 'MIT License', body: <License /> },
]

const fromHash = (): PanelId | null => {
  const h = (typeof window !== 'undefined' ? window.location.hash : '').replace('#', '')
  return h === 'terms' || h === 'privacy' || h === 'license' ? h : null
}

/** Dashboard footer: conditions of use, privacy notice and the MIT license, each opening in place (and reachable as /#terms, /#privacy, /#license). */
export function SiteFooter() {
  const { health } = useWorkspace()
  const [open, setOpen] = useState<PanelId | null>(fromHash)
  const root = useRef<HTMLElement>(null)
  const year = new Date().getFullYear()

  useEffect(() => {
    const on = () => { const p = fromHash(); if (p) { setOpen(p); root.current?.scrollIntoView({ behavior: 'smooth', block: 'center' }) } }
    window.addEventListener('hashchange', on)
    if (fromHash()) window.setTimeout(on, 0)
    return () => window.removeEventListener('hashchange', on)
  }, [])

  const panel = PANELS.find((p) => p.id === open)
  return (
    <footer ref={root} id="legal" className="card rise p-6 sm:p-7" style={{ '--i': 8 } as React.CSSProperties} aria-label="Legal information">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <Logo tagline />
        <nav className="flex flex-wrap gap-2" aria-label="Legal">
          {PANELS.map((p) => (
            <button key={p.id} type="button" aria-expanded={open === p.id} aria-controls={`legal-${p.id}`} onClick={() => setOpen(open === p.id ? null : p.id)}
              className={`rounded-full border px-4 py-2 text-sm font-medium transition duration-200 active:scale-[.98] ${open === p.id ? 'border-brand bg-brand-soft text-brand' : 'border-line bg-surface hover:border-brand/50 hover:text-brand'}`}>
              {p.label}
            </button>
          ))}
        </nav>
      </div>

      {panel && (
        <section id={`legal-${panel.id}`} role="region" aria-label={panel.title} className="fade mt-5 border-t border-line pt-5 text-sm text-muted" data-testid="legal-panel">
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="font-display text-2xl font-semibold text-ink">{panel.title}</h2>
            {panel.id !== 'license' && <span className="text-xs">Last updated {LEGAL_UPDATED}</span>}
          </div>
          <div className="max-w-3xl space-y-1">{panel.body}</div>
          <button className="btn btn-sm btn-ghost mt-4" onClick={() => setOpen(null)}>Close</button>
        </section>
      )}

      <p className="mt-5 flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-line pt-4 text-sm text-muted">
        <span>© {COPYRIGHT_START}{year > COPYRIGHT_START ? `–${year}` : ''} DocSherlock contributors.</span>
        <span>Released under the <button type="button" className="link" onClick={() => setOpen('license')}>MIT License</button>.</span>
        <a className="link" href={REPO_URL} target="_blank" rel="noreferrer">Source on GitHub</a>
        {health?.version && <span aria-label="Version">· v{health.version}</span>}
      </p>
    </footer>
  )
}
