// Types mirror the FastAPI response models (backend/app/schemas, services/qa.py).

export type DocStatus = 'UPLOADED' | 'PROCESSING' | 'EXTRACTING' | 'OCR' | 'CHUNKING' | 'EMBEDDING' | 'INDEXING' | 'READY' | 'FAILED'

export interface DocumentInfo {
  id: string
  filename: string
  file_type: string
  file_size: number
  status: DocStatus
  progress: number
  error: string | null
  uploaded_at: string
  n_pages: number
  paged: boolean
  n_chunks: number
  n_claims: number
  ocr_used: boolean
  ocr_conf: number | null
  doc_date: string | null
  doc_date_source: string | null
  title: string | null
  warnings: string[]
  indexed: boolean
}

export interface UploadResult {
  filename: string
  ok: boolean
  duplicate: boolean
  message: string
  error: string | null
  document: DocumentInfo | null
}

export interface UploadResponse {
  results: UploadResult[]
  documents: DocumentInfo[]
}

export type Level = 'HIGH' | 'MEDIUM' | 'LOW' | 'CONFLICTED' | 'INSUFFICIENT'
export type AnswerStatus = 'answered' | 'partial' | 'conflict' | 'insufficient'
export type Mode = 'auto' | 'llm' | 'rules'

export interface Citation {
  id: string
  doc_id: string
  doc_name: string
  page: number | null
  section: string
  quote: string
  start: number
  end: number
  score: number
  ocr_conf: number | null
  doc_date: string | null
  chunk_id: string
  verified: boolean
  role: 'support' | 'conflict' | 'lead'
  side: string | null
}

export interface SourceRef {
  doc_id: string
  doc_name: string
  page: number | null
  section: string
  sentence: string
  start: number
  end: number
  chunk_id: string
  doc_date: string | null
  cite?: string
  ocr_conf?: number | null
}

export interface Position {
  value: string
  sources: SourceRef[]
}

export interface ConflictCluster {
  id: string
  kind: string
  value_kind: string
  topic: string[]
  severity: 'high' | 'medium' | 'low'
  score: number
  explanation: string
  hints: string[]
  same_document: boolean
  time_scoped: boolean
  positions: Position[]
  n_sources: number
  resolution: string
}

export interface MatrixRow {
  subject: string
  predicate: string
  value: string
  date: string
  document: string
  doc_id: string
  page: number | null
  section: string
  cite: string
  quote: string
  verified: boolean
}

export interface Reason {
  text: string
  effect: '+' | '-' | '='
}

export interface EngineInfo {
  name: string
  model: string
  fallback: boolean
  reason: string | null
  tokens: { prompt: number; completion: number; latency_ms: number } | null
  strict_schema: boolean
}

export interface TraceHit {
  doc: string
  page: number | null
  section: string
  rank: number
  relevance: number
  coverage: number
  rerank: number | null
  preview: string
}

export interface Answer {
  id: string
  investigation_id: string
  question: string
  effective_question: string
  status: AnswerStatus
  level: Level
  headline: string
  answer: string
  confidence: { score: number; label: string; reasons: Reason[] }
  conflict_detected: boolean
  citations: Citation[]
  conflicts: ConflictCluster[]
  evidence_matrix: MatrixRow[]
  caveats: string[]
  missing_terms: string[]
  engine: EngineInfo
  trace: { query_terms?: string[]; question_type?: string; channels?: string[]; scope_documents?: number; scope_chunks?: number; intent?: string; hits: TraceHit[] }
  timings_ms: Record<string, number>
  pinned: boolean
  note: string
  created_at: string | null
  comparison?: Comparison
}

export interface Investigation {
  id: string
  name: string
  status: string
  created_at: string
  updated_at: string
  n_questions: number
}

export interface InvestigationDetail extends Investigation {
  questions: Answer[]
}

export interface ChangeSide {
  value: string
  source: Omit<SourceRef, 'cite'>
  cite?: string
}

export interface Change {
  topic: string
  kind: string
  severity: 'high' | 'medium' | 'low'
  old: ChangeSide
  new: ChangeSide
  direction: string
  delta: number | null
  description: string
  hints: string[]
  time_scoped: boolean
}

export interface Comparison {
  old: { doc_id: string; name: string; doc_date: string | null }
  new: { doc_id: string; name: string; doc_date: string | null }
  ordered_by_date: boolean
  swapped: boolean
  changes: Change[]
  unchanged: { topic: string; value: string; old: SourceRef; new: SourceRef }[]
  only_in_old: { claim: string; value: string; source: SourceRef }[]
  only_in_new: { claim: string; value: string; source: SourceRef }[]
  caveats: string[]
  summary: string
  engine?: string
}

export interface Health {
  status: 'healthy' | 'degraded'
  version: string
  database: { ok: boolean; engine: string }
  vector_store: { ok: boolean; mode: string; collection: string }
  models: { dense: ModelState; sparse: ModelState; reranker: ModelState; loading: boolean }
  ocr: { available: boolean; reason: string }
  llm: { available: boolean; provider: string; model: string | null; fallback: string }
  formats: string[]
  max_upload_mb: number
}

export interface ModelState {
  name: string
  enabled: boolean
  ready: boolean
  loading: boolean
  error: string | null
}

export interface PageData {
  document: DocumentInfo
  page: { number: number; text: string; ocr_conf: number | null; method: string; has_image: boolean }
  n_pages: number
}

export interface ClaimInfo {
  id: string
  page: number
  section: string
  sentence: string
  subject: string
  kind: string
  value: string
}

export interface ViewerTarget {
  docId: string
  docName: string
  page: number
  start?: number
  end?: number
  quote?: string
}

export type StageEvent = { stage: string; detail: string }
