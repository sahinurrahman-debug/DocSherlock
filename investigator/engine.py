"""Engine: ties ingestion, indexing, conflict scanning, question answering and the investigation notebook together."""
from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
import uuid
from pathlib import Path

from . import config, ocr
from .answer import Analyzer, CitationBook, compose_extractive, contextualize
from .chunking import chunk_document
from .conflicts import ConflictEngine, Conflict, cluster_conflicts
from .extract import ExtractionError, extract, detect_doc_date
from .facts import build_fact
from .llm import LLMUnavailable, compose_llm
from .models import Chunk, DocumentRecord, Fact, PageText
from .retrieval import DenseEmbedder, Retriever
from .store import Store
from .textutil import split_sentences, clip

log = logging.getLogger("docinv.engine")


class IngestError(Exception):
    pass


class Engine:
    def __init__(self, data_dir: Path | str | None = None, dense: bool | None = None, load_existing: bool = True):
        self.store = Store(Path(data_dir or config.DATA_DIR))
        self.dense = DenseEmbedder()
        if dense is False:
            self.dense.enabled = False
        self.retriever = Retriever(self.dense)
        self.retriever.emb_cache.update(self.store.load_embeddings())
        self._saved_emb = set(self.retriever.emb_cache)
        self.lock = threading.RLock()
        self.docs: dict[str, DocumentRecord] = {}
        self.pages: dict[str, list[PageText]] = {}
        self._derived: dict[str, tuple[list[Chunk], list[Fact]]] = {}
        self.chunks: list[Chunk] = []
        self.facts: list[Fact] = []
        self.chunk_by_id: dict[str, Chunk] = {}
        self._conflicts: list[Conflict] = []
        self._clusters: list[dict] = []
        if load_existing:
            for rec, pages in self.store.load_documents():
                self.docs[rec.id] = rec
                self.pages[rec.id] = pages
                self._derive(rec)
            self._reindex()
        self.dense.warmup(on_ready=self._on_dense_ready)

    # ---------------------------------------------------------------------------------------
    # status
    # ---------------------------------------------------------------------------------------
    def status(self) -> dict:
        return {
            "documents": len(self.docs),
            "chunks": len(self.chunks),
            "facts": len(self.facts),
            "conflicts": len(self._clusters),
            "ocr": {"available": ocr.available(), "engine": "RapidOCR (ONNX, offline)" if ocr.available() else None,
                    "reason": ocr.unavailable_reason() if not ocr.available() else ""},
            "dense": {"enabled": self.dense.enabled, "ready": self.dense.ready, "loading": self.dense.loading,
                      "model": config.DENSE_MODEL if self.dense.enabled else None, "active": self.retriever.dense_active,
                      "error": self.dense.error},
            "llm": {"available": config.llm_available(), "model": config.LLM_MODEL if config.llm_available() else None},
            "formats": sorted(config.ALLOWED_EXTENSIONS),
            "max_upload_mb": config.MAX_UPLOAD_MB,
        }

    def _on_dense_ready(self):
        with self.lock:
            self.retriever.refresh_dense()
            self._persist_embeddings()

    def _persist_embeddings(self):
        new = {k: v for k, v in self.retriever.emb_cache.items() if k not in self._saved_emb}
        if new:
            self.store.save_embeddings(new)
            self._saved_emb |= set(new)

    # ---------------------------------------------------------------------------------------
    # ingestion
    # ---------------------------------------------------------------------------------------
    def ingest(self, filename: str, data: bytes) -> dict:
        filename = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", Path(filename or "document").name)[:150] or "document"
        if len(data) > config.MAX_UPLOAD_MB * 1024 * 1024:
            raise IngestError(f"File is larger than the {config.MAX_UPLOAD_MB:g} MB limit.")
        sha = hashlib.sha256(data).hexdigest()
        with self.lock:
            for rec in self.docs.values():
                if rec.sha256 == sha:
                    return {"document": rec.to_dict(), "duplicate": True,
                            "message": f"Identical to '{rec.name}', which is already indexed."}
        try:
            ex = extract(filename, data)
        except ExtractionError as exc:
            raise IngestError(str(exc)) from exc

        ext = Path(filename).suffix.lower()
        doc_date, date_src = detect_doc_date(filename, ex)
        full_text = "\n".join(p.text for p in ex.pages)
        confs = [p.ocr_conf for p in ex.pages if p.ocr_conf is not None]
        with self.lock:
            name = self._unique_name(filename)
            rec = DocumentRecord(
                id=sha[:10], name=name, ext=ext, sha256=sha, size=len(data), n_pages=len(ex.pages), paged=ex.paged,
                ocr_used=bool(confs), ocr_conf=(sum(confs) / len(confs)) if confs else None, doc_date=doc_date,
                doc_date_source=date_src, warnings=ex.warnings, added_at=time.time(), n_chars=len(full_text),
                title=ex.meta.get("title"), status="ready" if full_text.strip() else "empty")
            self.docs[rec.id] = rec
            self.pages[rec.id] = ex.pages
            self._derive(rec)
            self.store.save_document(rec, ex.pages, data)
            self._reindex()
            self.store.update_document(rec)
            return {"document": rec.to_dict(), "duplicate": False, "message": ""}

    def _unique_name(self, name: str) -> str:
        existing = {d.name for d in self.docs.values()}
        if name not in existing:
            return name
        p = Path(name)
        i = 2
        while f"{p.stem} ({i}){p.suffix}" in existing:
            i += 1
        return f"{p.stem} ({i}){p.suffix}"

    def _derive(self, rec: DocumentRecord) -> None:
        pages = self.pages[rec.id]
        chunks = chunk_document(rec.id, rec.name, pages, rec.paged, rec.doc_date, rec.title)
        facts: list[Fact] = []
        for ch in chunks:
            for i, (a, b) in enumerate(split_sentences(ch.text)):
                s = ch.text[a:b]
                if s.lstrip().startswith("#") or len(s) < 15:
                    continue
                f = build_fact(f"{ch.id}:{i}", ch, a, b, s, ch.section, rec.title)
                if f:
                    facts.append(f)
        rec.n_chunks, rec.n_facts = len(chunks), len(facts)
        self._derived[rec.id] = (chunks, facts)

    def _reindex(self) -> None:
        self.chunks = [c for rec in self.docs.values() for c in self._derived[rec.id][0]]
        self.facts = [f for rec in self.docs.values() for f in self._derived[rec.id][1]]
        self.chunk_by_id = {c.id: c for c in self.chunks}
        self.retriever.build(self.chunks)
        self._persist_embeddings()
        self._conflicts = ConflictEngine(self.facts, idf=None).scan() if len(self.facts) > 1 else []
        self._clusters = cluster_conflicts(self._conflicts)

    # ---------------------------------------------------------------------------------------
    # document management
    # ---------------------------------------------------------------------------------------
    def documents(self) -> list[dict]:
        return [d.to_dict() for d in sorted(self.docs.values(), key=lambda d: d.added_at)]

    def get_document(self, doc_id: str) -> DocumentRecord | None:
        return self.docs.get(doc_id)

    def delete(self, doc_id: str) -> bool:
        with self.lock:
            rec = self.docs.pop(doc_id, None)
            if not rec:
                return False
            self.pages.pop(doc_id, None)
            self._derived.pop(doc_id, None)
            self.store.delete_document(doc_id, rec.ext)
            self._reindex()
            return True

    def reset(self) -> None:
        with self.lock:
            self.docs.clear()
            self.pages.clear()
            self._derived.clear()
            self.store.clear_all()
            self.retriever.emb_cache.clear()
            self._saved_emb.clear()
            self._reindex()

    def set_doc_date(self, doc_id: str, iso: str | None) -> DocumentRecord | None:
        with self.lock:
            rec = self.docs.get(doc_id)
            if not rec:
                return None
            if iso:
                if not re.fullmatch(r"\d{4}(-\d{2}(-\d{2})?)?", iso):
                    raise ValueError("Date must look like YYYY, YYYY-MM or YYYY-MM-DD.")
            rec.doc_date = iso or None
            rec.doc_date_source = "set manually" if iso else None
            self._derive(rec)
            self.store.update_document(rec)
            self._reindex()
            return rec

    def get_pages(self, doc_id: str) -> list[PageText] | None:
        return self.pages.get(doc_id)

    # ---------------------------------------------------------------------------------------
    # conflicts
    # ---------------------------------------------------------------------------------------
    def conflicts(self) -> list[dict]:
        return self._clusters

    # ---------------------------------------------------------------------------------------
    # question answering
    # ---------------------------------------------------------------------------------------
    def ask(self, question: str, history: list[dict] | None = None, mode: str = "auto", llm_client=None) -> dict:
        t0 = time.perf_counter()
        question = re.sub(r"\s+", " ", (question or "")).strip()
        if not question:
            raise ValueError("Please enter a question.")
        if len(question) > 1500:
            raise ValueError("Question is too long (max 1500 characters).")
        if not self.docs:
            return self._empty_result(question, "No documents have been uploaded yet. Add documents on the left, then ask a question.")

        with self.lock:
            eff = contextualize(question, history, self.retriever)
            analyzer = Analyzer(self.retriever, self.chunk_by_id, self._clusters, len(self.docs))
            ctx = analyzer.build(question, eff)
            chunks = dict(self.chunk_by_id)
        t1 = time.perf_counter()

        book = CitationBook()
        engine_used = "extractive"
        note = None
        want_llm = mode in ("auto", "llm") and (config.llm_available() or llm_client is not None) and bool(ctx.hits)
        if mode == "llm" and not want_llm and not config.llm_available() and llm_client is None:
            note = "Claude is not configured (set ANTHROPIC_API_KEY); used the offline extractive engine instead."
        result = None
        if want_llm:
            try:
                result = compose_llm(ctx, book, chunks, history, client=llm_client)
                engine_used = "claude"
            except LLMUnavailable as exc:
                log.warning("LLM failed, falling back: %s", exc)
                note = f"Claude was unavailable ({clip(str(exc), 120)}); used the offline extractive engine instead."
                book = CitationBook()
        if result is None:
            result = compose_extractive(ctx, book, chunks)
        if note:
            result["caveats"] = [note] + result.get("caveats", [])
        t2 = time.perf_counter()

        return {
            "id": uuid.uuid4().hex[:10],
            "question": question,
            "effective_question": eff,
            "status": result["status"],
            "headline": result.get("headline", ""),
            "answer": result["answer"],
            "confidence": result["confidence"],
            "citations": [c.to_dict() for c in book.items],
            "conflicts": result.get("conflicts", []),
            "caveats": result.get("caveats", []),
            "missing_terms": ctx.missing_terms,
            "engine": engine_used,
            "timings_ms": {"retrieve": round((t1 - t0) * 1000), "compose": round((t2 - t1) * 1000), "total": round((t2 - t0) * 1000)},
            "trace": {
                "query_terms": ctx.info.terms, "question_type": ctx.info.qtype, "wants": sorted(ctx.info.wants),
                "dense": ctx.dense_active,
                "hits": [{"doc": h.chunk.doc_name, "page": h.chunk.page if h.chunk.paged else None, "section": h.chunk.section,
                          "rank": round(h.rank_score, 3), "relevance": round(h.relevance, 3), "coverage": round(h.coverage, 3),
                          "preview": clip(h.chunk.text, 140)} for h in ctx.hits],
                "relevant_conflicts": len(ctx.conflicts),
            },
        }

    def _empty_result(self, question: str, msg: str) -> dict:
        return {"id": uuid.uuid4().hex[:10], "question": question, "effective_question": question, "status": "insufficient", "headline": "",
                "answer": msg, "confidence": {"score": 0.0, "label": "None", "reasons": []}, "citations": [], "conflicts": [],
                "caveats": [], "missing_terms": [], "engine": "extractive", "timings_ms": {"total": 0}, "trace": {"hits": []}}

    # ---------------------------------------------------------------------------------------
    # notebook
    # ---------------------------------------------------------------------------------------
    def add_note(self, result: dict, comment: str = "") -> dict:
        note = {"id": uuid.uuid4().hex[:10], "ts": time.time(), "comment": comment[:2000], "result": result}
        self.store.add_note(note["id"], note["ts"], note)
        return note

    def notes(self) -> list[dict]:
        return self.store.notes()

    def delete_note(self, note_id: str) -> None:
        self.store.delete_note(note_id)

    def export_markdown(self) -> str:
        from .report import render_markdown
        return render_markdown(self.notes(), self.documents(), self.conflicts())

    # ---------------------------------------------------------------------------------------
    def load_demo(self) -> list[dict]:
        out = []
        if not config.SAMPLES_DIR.exists():
            raise FileNotFoundError("Sample corpus not found. Run `python samples/generate_samples.py`.")
        for p in sorted(config.SAMPLES_DIR.iterdir()):
            if p.is_file() and p.suffix.lower() in config.ALLOWED_EXTENSIONS:
                out.append(self.ingest(p.name, p.read_bytes()))
        return out
