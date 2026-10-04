import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api, askStream, ApiError } from '../lib/api'
import { isBusy } from '../lib/format'
import type { Answer, DocumentInfo, Health, Investigation, Mode, ViewerTarget } from '../lib/types'

export interface Pending { question: string; stage: string; detail: string }

interface Workspace {
  health: Health | null
  documents: DocumentInfo[]
  loadingDocs: boolean
  refreshDocuments: () => Promise<void>
  deselected: Set<string>
  toggleDoc: (id: string) => void
  selectAll: () => void
  scopeIds: string[] | null          // null => every READY document
  readyDocs: DocumentInfo[]
  upload: (files: File[]) => Promise<void>
  loadDemo: () => Promise<void>
  removeDoc: (id: string) => Promise<void>
  resetAll: () => Promise<void>
  setDate: (id: string, date: string | null) => Promise<void>

  investigations: Investigation[]
  currentId: string | null
  thread: Answer[]
  pending: Pending | null
  mode: Mode
  setMode: (m: Mode) => void
  ask: (q: string) => Promise<void>
  newInvestigation: () => void
  openInvestigation: (id: string) => Promise<void>
  renameInvestigation: (id: string, name: string) => Promise<void>
  deleteInvestigation: (id: string) => Promise<void>
  setPinned: (a: Answer, pinned: boolean) => Promise<void>
  setNote: (a: Answer, note: string) => Promise<void>
  exportReport: (pinnedOnly?: boolean) => Promise<void>

  viewer: ViewerTarget | null
  openSource: (t: ViewerTarget) => void
  closeViewer: () => void
  toast: (msg: string) => void
  toasts: { id: number; msg: string }[]
}

const Ctx = createContext<Workspace | null>(null)
export const useWorkspace = (): Workspace => {
  const v = useContext(Ctx)
  if (!v) throw new Error('useWorkspace must be used inside <WorkspaceProvider>')
  return v
}

const LAST = 'docsherlock.investigation'
const MODE = 'docsherlock.mode'
const safeGet = (k: string) => { try { return localStorage.getItem(k) } catch { return null } }
const safeSet = (k: string, v: string | null) => { try { v === null ? localStorage.removeItem(k) : localStorage.setItem(k, v) } catch { /* private mode */ } }
const errText = (e: unknown) => (e instanceof ApiError || e instanceof Error ? e.message : 'Something went wrong')

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [health, setHealth] = useState<Health | null>(null)
  const [documents, setDocuments] = useState<DocumentInfo[]>([])
  const [loadingDocs, setLoadingDocs] = useState(true)
  const [deselected, setDeselected] = useState<Set<string>>(new Set())
  const [investigations, setInvestigations] = useState<Investigation[]>([])
  const [currentId, setCurrentId] = useState<string | null>(null)
  const [thread, setThread] = useState<Answer[]>([])
  const [pending, setPending] = useState<Pending | null>(null)
  const [mode, setModeState] = useState<Mode>(() => (safeGet(MODE) as Mode) || 'auto')
  const [viewer, setViewer] = useState<ViewerTarget | null>(null)
  const [toasts, setToasts] = useState<{ id: number; msg: string }[]>([])
  const busyRef = useRef(false)

  const toast = useCallback((msg: string) => {
    const id = Date.now() + Math.random()
    setToasts((t) => [...t, { id, msg }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4200)
  }, [])

  // ---- documents (polled while anything is still being processed) -------------------------------------------
  const refreshDocuments = useCallback(async () => {
    try { setDocuments(await api.documents.list()) } catch (e) { toast(errText(e)) } finally { setLoadingDocs(false) }
  }, [toast])

  useEffect(() => { void refreshDocuments() }, [refreshDocuments])
  const anyBusy = documents.some((d) => isBusy(d.status))
  useEffect(() => {
    if (!anyBusy) return
    const t = setInterval(() => void refreshDocuments(), 1200)
    return () => clearInterval(t)
  }, [anyBusy, refreshDocuments])

  // ---- health (faster while models are still loading) ------------------------------------------------------
  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setTimeout>
    const tick = async () => {
      let next = 15000
      try {
        const h = await api.health()
        if (alive) setHealth(h)
        if (h.models.loading) next = 2500
      } catch { next = 5000 }
      if (alive) timer = setTimeout(tick, next)
    }
    void tick()
    return () => { alive = false; clearTimeout(timer) }
  }, [])

  const readyDocs = useMemo(() => documents.filter((d) => d.status === 'READY'), [documents])
  const scopeIds = useMemo(() => {
    const ids = readyDocs.filter((d) => !deselected.has(d.id)).map((d) => d.id)
    return ids.length === readyDocs.length ? null : ids
  }, [readyDocs, deselected])
  const toggleDoc = (id: string) => setDeselected((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })
  const selectAll = () => setDeselected(new Set())

  const upload = useCallback(async (files: File[]) => {
    if (!files.length) return
    try {
      const r = await api.documents.upload(files)
      setDocuments(r.documents)
      for (const x of r.results) {
        if (!x.ok) toast(`${x.filename}: ${x.error}`)
        else if (x.duplicate) toast(x.message)
      }
    } catch (e) { toast(errText(e)) }
  }, [toast])

  const loadDemo = useCallback(async () => {
    try {
      const r = await api.documents.demo()
      setDocuments(r.documents)
      toast(`Loading ${r.results.length} sample documents - they will be ready in a few seconds`)
    } catch (e) { toast(errText(e)) }
  }, [toast])

  const removeDoc = useCallback(async (id: string) => {
    try { await api.documents.remove(id); await refreshDocuments() } catch (e) { toast(errText(e)) }
  }, [refreshDocuments, toast])

  const resetAll = useCallback(async () => {
    try { await api.documents.reset(); await refreshDocuments(); setViewer(null) } catch (e) { toast(errText(e)) }
  }, [refreshDocuments, toast])

  const setDate = useCallback(async (id: string, date: string | null) => {
    try { await api.documents.setDate(id, date); await refreshDocuments() } catch (e) { toast(errText(e)) }
  }, [refreshDocuments, toast])

  // ---- investigations ------------------------------------------------------------------------------------------
  const refreshInvestigations = useCallback(async () => {
    try { setInvestigations(await api.investigations.list()) } catch { /* shown elsewhere */ }
  }, [])

  const openInvestigation = useCallback(async (id: string) => {
    try {
      const d = await api.investigations.get(id)
      setCurrentId(d.id)
      setThread(d.questions)
      safeSet(LAST, d.id)
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) { safeSet(LAST, null); setCurrentId(null); setThread([]) } else toast(errText(e))
    }
  }, [toast])

  useEffect(() => {
    void (async () => {
      await refreshInvestigations()
      const last = safeGet(LAST)
      if (last) await openInvestigation(last)
    })()
  }, [refreshInvestigations, openInvestigation])

  const newInvestigation = () => { setCurrentId(null); setThread([]); safeSet(LAST, null) }

  const renameInvestigation = useCallback(async (id: string, name: string) => {
    try { await api.investigations.rename(id, name); await refreshInvestigations() } catch (e) { toast(errText(e)) }
  }, [refreshInvestigations, toast])

  const deleteInvestigation = useCallback(async (id: string) => {
    try {
      await api.investigations.remove(id)
      if (id === currentId) { setCurrentId(null); setThread([]); safeSet(LAST, null) }
      await refreshInvestigations()
    } catch (e) { toast(errText(e)) }
  }, [currentId, refreshInvestigations, toast])

  const setMode = (m: Mode) => { setModeState(m); safeSet(MODE, m) }

  const ask = useCallback(async (question: string) => {
    const q = question.trim()
    if (!q || busyRef.current) return
    busyRef.current = true
    setPending({ question: q, stage: 'retrieving', detail: 'Starting' })
    try {
      const ans = await askStream({ question: q, investigationId: currentId, documentIds: scopeIds, mode }, {
        onInvestigation: (inv) => { setCurrentId(inv.id); safeSet(LAST, inv.id) },
        onStage: (s) => setPending({ question: q, stage: s.stage, detail: s.detail }),
      })
      setThread((t) => [...t, ans])
      setCurrentId(ans.investigation_id)
      safeSet(LAST, ans.investigation_id)
      void refreshInvestigations()
    } catch (e) {
      toast(errText(e))
    } finally {
      setPending(null)
      busyRef.current = false
    }
  }, [currentId, scopeIds, mode, refreshInvestigations, toast])

  const patchLocal = (id: string, p: Partial<Answer>) => setThread((t) => t.map((a) => (a.id === id ? { ...a, ...p } : a)))
  const setPinned = useCallback(async (a: Answer, pinned: boolean) => {
    patchLocal(a.id, { pinned })
    try { await api.questions.patch(a.id, { pinned }) } catch (e) { patchLocal(a.id, { pinned: !pinned }); toast(errText(e)) }
  }, [toast])
  const setNote = useCallback(async (a: Answer, note: string) => {
    patchLocal(a.id, { note })
    try { await api.questions.patch(a.id, { note }) } catch (e) { toast(errText(e)) }
  }, [toast])

  const exportReport = useCallback(async (pinnedOnly = false) => {
    if (!currentId) { toast('Ask a question first - the report covers the current investigation.'); return }
    try { await api.investigations.report(currentId, pinnedOnly) } catch (e) { toast(errText(e)) }
  }, [currentId, toast])

  const value: Workspace = {
    health, documents, loadingDocs, refreshDocuments, deselected, toggleDoc, selectAll, scopeIds, readyDocs, upload, loadDemo, removeDoc, resetAll, setDate,
    investigations, currentId, thread, pending, mode, setMode, ask, newInvestigation, openInvestigation, renameInvestigation, deleteInvestigation,
    setPinned, setNote, exportReport, viewer, openSource: setViewer, closeViewer: () => setViewer(null), toast, toasts,
  }
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}
