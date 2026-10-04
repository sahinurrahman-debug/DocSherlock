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
        className={`cursor-pointer rounded-xl border-2 border-dashed text-center transition ${compact ? 'px-3 py-4' : 'px-6 py-10'} ${over ? 'border-brand bg-brand-soft' : 'border-line bg-surface-2 hover:border-brand'}`}
      >
        <input ref={input} type="file" multiple hidden accept={accept} onChange={(e) => { void upload([...(e.target.files ?? [])]); e.target.value = '' }} />
        <div className="font-semibold">Drop files here <span className="font-normal text-muted">or</span> <span className="text-brand underline">browse</span></div>
        <div className="mt-1 text-[11px] leading-snug text-muted">PDF · DOCX · scans &amp; images (OCR) · TXT / MD · CSV / XLSX · HTML · JSON · EML<br />up to {health?.max_upload_mb ?? 40} MB each</div>
      </div>
      {documents.length === 0 && (
        <button className="btn btn-primary mt-2 w-full" onClick={() => void loadDemo()}>Load the sample set (11 files, some contradict)</button>
      )}
    </div>
  )
}
