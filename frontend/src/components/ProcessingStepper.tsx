import { STAGE_FLOW, STAGE_LABEL } from '../lib/format'
import type { DocStatus } from '../lib/types'

/** Upload → Extract → (OCR) → Chunk → Embed → Index → Ready, as the plan's visible processing pipeline. */
export function ProcessingStepper({ status, progress, ocr }: { status: DocStatus; progress: number; ocr: boolean }) {
  if (status === 'FAILED') return null
  const flow = STAGE_FLOW.filter((s) => s !== 'OCR' || ocr || status === 'OCR')
  const cur = status === 'PROCESSING' ? 0 : Math.max(0, flow.indexOf(status))
  return (
    <div className="mt-2" aria-label={`Processing: ${STAGE_LABEL[status]}`}>
      <div className="flex items-center gap-1">
        {flow.map((s, i) => (
          <div key={s} className="flex flex-1 items-center gap-1" title={STAGE_LABEL[s]}>
            <span className={`h-1.5 flex-1 rounded-full ${i < cur ? 'bg-ok' : i === cur ? (status === 'READY' ? 'bg-ok' : 'bg-brand bar-active') : 'bg-line'}`} />
          </div>
        ))}
      </div>
      <div className="mt-1 flex justify-between text-[11px] text-muted">
        <span>{STAGE_LABEL[status]}…</span><span>{progress}%</span>
      </div>
    </div>
  )
}
