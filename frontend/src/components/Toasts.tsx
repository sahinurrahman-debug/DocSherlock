import { useWorkspace } from '../context/workspace'

export function Toasts() {
  const { toasts } = useWorkspace()
  return (
    <div className="pointer-events-none fixed bottom-5 left-1/2 z-50 flex -translate-x-1/2 flex-col items-center gap-2 px-4" role="status" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className="pop pointer-events-auto max-w-[92vw] rounded-2xl bg-ink px-5 py-3 text-sm text-bg shadow-[var(--shadow-lift)]">{t.msg}</div>
      ))}
    </div>
  )
}
