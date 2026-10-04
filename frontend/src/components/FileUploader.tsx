import { useRef, useState } from 'react'
import { useWorkspace } from '../context/workspace'

export function FileUploader({ compact = false }: { compact?: boolean }) {
  const { upload, loadDemo, health, documents } = useWorkspace()
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  const accept = health?.formats.join(',')

  return (
    <div>
      <div
        role="button" tabIndex={0} aria-label="Upload documents"
        onClick={() => input.current?.click()}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.current?.click() } }}
        onDragOver={(e) => { e.preventDefault(); setOver(true) }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); void upload([...e.dataTransfer.files]) }}
        className={`group cursor-pointer rounded-2xl border-2 border-dashed text-center transition duration-300 ${compact ? 'px-4 py-5' : 'px-6 py-10'} ${over ? 'scale-[1.01] border-brand bg-brand-soft' : 'border-line bg-surface/70 hover:border-brand/60 hover:bg-surface'}`}
      >
        <input ref={input} type="file" multiple hidden accept={accept} onChange={(e) => { void upload([...(e.target.files ?? [])]); e.target.value = '' }} />
        <svg viewBox="0 0 24 24" className={`mx-auto mb-2 text-brand transition duration-300 group-hover:-translate-y-0.5 ${compact ? 'h-6 w-6' : 'h-9 w-9'}`} fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 16V4M7 9l5-5 5 5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" /></svg>
        <div className="font-medium">Drop files here <span className="font-normal text-muted">or</span> <span className="link">browse</span></div>
        <div className="mt-1.5 text-xs leading-snug text-muted">PDF · Word · scans &amp; images (OCR) · text · CSV / Excel · HTML · JSON · e-mail<br />up to {health?.max_upload_mb ?? 40} MB each</div>
      </div>
      {documents.length === 0 && (
        <button className="btn btn-primary mt-3 w-full" onClick={() => void loadDemo()}>Load the sample set (11 files, some contradict)</button>
      )}
    </div>
  )
}
