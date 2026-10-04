import { useWorkspace } from '../context/workspace'

export function Toasts() {
  const { toasts } = useWorkspace()
  return (
    <div className="pointer-events-none fixed bottom-4 left-1/2 z-50 flex -translate-x-1/2 flex-col items-center gap-2" role="status" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className="pointer-events-auto max-w-[90vw] rounded-full bg-ink px-4 py-2 text-[13px] text-bg shadow-lg">{t.msg}</div>
      ))}
    </div>
  )
}
