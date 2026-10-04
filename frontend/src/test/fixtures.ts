import type { Answer, ConflictCluster } from '../lib/types'

export const cluster: ConflictCluster = {
  id: 'c1', kind: 'value', value_kind: 'duration', topic: ['payment', 'terms'], severity: 'high', score: 1, explanation: 'Different durations.',
  hints: ['Contract is newer than the email'], same_document: false, time_scoped: false, n_sources: 3,
  resolution: '"Net 45" is the **most likely current position** - confirm before relying on it.',
  positions: [
    { value: 'Net 30', sources: [
      { doc_id: 'd1', doc_name: 'Agreement.pdf', page: 1, section: 'Payment Terms', sentence: 'Invoices are payable Net 30.', start: 0, end: 28, chunk_id: 'd1:0', doc_date: '2023-03-03', cite: 'S1' },
      { doc_id: 'd3', doc_name: 'Email.eml', page: null, section: '', sentence: 'Per our contract invoices are due Net 30.', start: 0, end: 41, chunk_id: 'd3:0', doc_date: '2024-02-02', cite: 'S2' }] },
    { value: 'Net 45', sources: [
      { doc_id: 'd2', doc_name: 'Amendment.docx', page: null, section: 'Payment Terms', sentence: 'Invoices are payable Net 45.', start: 0, end: 28, chunk_id: 'd2:0', doc_date: '2024-01-15', cite: 'S3' }] },
  ],
}

const base: Answer = {
  id: 'q1', investigation_id: 'i1', question: 'What are the payment terms?', effective_question: 'What are the payment terms?', status: 'answered', level: 'HIGH',
  headline: '', answer: '', confidence: { score: 0.9, label: 'High', reasons: [{ text: 'Best passage covers 100% of key terms', effect: '+' }, { text: 'Supported by a single document', effect: '=' }] },
  conflict_detected: false, citations: [], conflicts: [], evidence_matrix: [], caveats: [], missing_terms: [],
  engine: { name: 'rules', model: '', fallback: false, reason: null, tokens: null, strict_schema: false },
  trace: { hits: [] }, timings_ms: { total: 12 }, pinned: false, note: '', created_at: null,
}

export const conflictAnswer: Answer = {
  ...base, status: 'conflict', level: 'CONFLICTED', headline: 'Net 30 vs Net 45', conflict_detected: true,
  answer: '**The documents disagree on this - there is no single supported answer.**\n\n- **Net 30** - Agreement.pdf [S1]\n- **Net 45** - Amendment.docx [S3]',
  conflicts: [cluster],
  citations: [
    { id: 'S1', doc_id: 'd1', doc_name: 'Agreement.pdf', page: 1, section: 'Payment Terms', quote: 'Invoices are payable Net 30.', start: 0, end: 28, score: 1, ocr_conf: null, doc_date: '2023-03-03', chunk_id: 'd1:0', verified: true, role: 'conflict', side: 'A' },
    { id: 'S3', doc_id: 'd2', doc_name: 'Amendment.docx', page: null, section: 'Payment Terms', quote: 'Invoices are payable Net 45.', start: 0, end: 28, score: 1, ocr_conf: null, doc_date: '2024-01-15', chunk_id: 'd2:0', verified: true, role: 'conflict', side: 'B' },
  ],
  evidence_matrix: [
    { subject: 'payment terms', predicate: 'are', value: 'Net 30', date: '2023-03-03', document: 'Agreement.pdf', doc_id: 'd1', page: 1, section: 'Payment Terms', cite: 'S1', quote: 'Invoices are payable Net 30.', verified: true },
    { subject: 'payment terms', predicate: 'are', value: 'Net 45', date: '2024-01-15', document: 'Amendment.docx', doc_id: 'd2', page: null, section: 'Payment Terms', cite: 'S3', quote: 'Invoices are payable Net 45.', verified: true },
  ],
}

export const answered: Answer = {
  ...base, headline: '$1,000,000', answer: 'Liability is capped at $1,000,000. [S1]',
  citations: [{ id: 'S1', doc_id: 'd1', doc_name: 'Agreement.pdf', page: 1, section: 'Limitation of Liability', quote: 'Liability is capped at $1,000,000.', start: 0, end: 34, score: 1, ocr_conf: 0.82, doc_date: null, chunk_id: 'd1:3', verified: true, role: 'support', side: null }],
  engine: { name: 'groq', model: 'openai/gpt-oss-120b', fallback: false, reason: null, tokens: { prompt: 1200, completion: 300, latency_ms: 900 }, strict_schema: true },
}

export const notFound: Answer = {
  ...base, status: 'insufficient', level: 'INSUFFICIENT', question: 'Who is the CFO?', answer: "**I couldn't find a reliable answer in the uploaded documents.**", missing_terms: ['cfo'],
  caveats: ['The LLM rate limit was reached - answered by the rule-based engine instead.'],
  citations: [{ id: 'S1', doc_id: 'd1', doc_name: 'Agreement.pdf', page: 1, section: '', quote: 'Unrelated sentence.', start: 0, end: 19, score: 0.2, ocr_conf: null, doc_date: null, chunk_id: 'd1:1', verified: true, role: 'lead', side: null }],
  engine: { name: 'rules', model: '', fallback: true, reason: 'rate limit', tokens: null, strict_schema: false },
}
