# API reference

Interactive OpenAPI docs: `GET /docs` (Swagger) · `GET /openapi.json`. All endpoints are scoped by the `X-Session-Id` header (4-64 chars of `A-Za-z0-9_-`);
the web app generates one per browser. Without the header the shared id `public` is used. Errors are `{"detail": "..."}`.

## System
| Method | Path | Description |
|---|---|---|
| GET | `/health` · `/api/health` | database, vector store, models (loading/ready), OCR, LLM availability (provider, model, fallback) |

## Documents
| Method | Path | Description |
|---|---|---|
| POST | `/api/documents/upload` | multipart `files[]` → **202**; per-file `{ok, duplicate, error, document}`; processing continues in the background |
| POST | `/api/documents/demo` | load the bundled sample documents into this workspace |
| GET | `/api/documents` | list with `status` (`UPLOADED … READY / FAILED`), `progress`, pages, claims, OCR confidence, date |
| GET | `/api/documents/{id}` | one document |
| PATCH | `/api/documents/{id}` | `{doc_date: "YYYY[-MM[-DD]]" \| null}` - drives "which source is newer" |
| DELETE | `/api/documents/{id}` · `/api/documents` | delete one / reset the workspace (also removes vectors) |
| GET | `/api/documents/{id}/pages/{n}` | page text, OCR confidence, `has_image` |
| GET | `/api/documents/{id}/pages/{n}/image?start&end` | PNG of the page with the passage `[start,end)` highlighted (PDF text search / OCR boxes) |
| GET | `/api/documents/{id}/file` | the original file |
| GET | `/api/documents/{id}/claims` | typed claims extracted from the document |

## Investigations and questions
| Method | Path | Description |
|---|---|---|
| POST | `/api/questions` | `{question, document_ids?, investigation_id?, mode: auto\|llm\|rules}` → full answer (below) |
| POST | `/api/questions/stream` | same request; **Server-Sent Events**: `investigation`, `stage` (`retrieving → checking_conflicts → reasoning → verifying`), then `result` (or `error`) |
| GET / PATCH / DELETE | `/api/questions/{id}` | fetch; `{pinned?, note?}`; delete |
| POST / GET | `/api/investigations` | create `{name?}` / list |
| GET / PATCH / DELETE | `/api/investigations/{id}` | detail with all answers / rename / delete |
| GET | `/api/investigations/{id}/report?pinned_only=` | Markdown report (answers, sources, caveats, corpus-wide conflict register) |
| GET | `/api/evidence/{question_id}` | citations (with exact offsets) + evidence matrix |
| GET | `/api/conflicts?document_ids=a,b` | **all** disputed points in scope (positions, sources, resolution reasoning) |
| GET | `/api/conflicts/{question_id}` | the conflicts recorded for an answer |
| POST | `/api/compare` | `{document_a, document_b}` → changes (old → new, direction, delta), unchanged, only-in-old/new, summary |

## Answer object (abridged)
```jsonc
{
  "id": "…", "investigation_id": "…", "question": "…", "effective_question": "…",
  "status": "answered | partial | conflict | insufficient",
  "level": "HIGH | MEDIUM | LOW | CONFLICTED | INSUFFICIENT",
  "headline": "Net 30 vs Net 45", "answer": "markdown with [S1] citation markers",
  "confidence": { "score": 0.97, "label": "High", "reasons": [{ "text": "…", "effect": "+|-|=" }] },
  "citations": [{ "id": "S1", "doc_id": "…", "doc_name": "…", "page": 1, "section": "…", "quote": "…", "start": 0, "end": 28,
                  "role": "support|conflict|lead", "ocr_conf": null, "verified": true }],
  "conflicts": [{ "id": "…", "kind": "value", "severity": "high", "positions": [{ "value": "Net 30", "sources": [ … ] }], "resolution": "…" }],
  "evidence_matrix": [{ "subject": "…", "value": "Net 30", "document": "…", "page": 1, "cite": "S1", "quote": "…" }],
  "caveats": ["…"], "missing_terms": ["cfo"],
  "engine": { "name": "groq | rules", "model": "openai/gpt-oss-120b", "fallback": false, "reason": null,
              "tokens": { "prompt": 1200, "completion": 300, "latency_ms": 900 } },
  "trace": { "channels": ["bm25","char-ngrams","qdrant-dense","qdrant-bm25","cross-encoder"], "hits": [ … ] },
  "comparison": { … }   // only for "what changed between X and Y" questions
}
```
`level` is the public uncertainty classification; `confidence.score` is an internal evidence-strength signal, not a probability.
