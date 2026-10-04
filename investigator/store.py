"""SQLite persistence: documents, extracted pages, embedding cache, notebook. Original files live on disk."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

import numpy as np

from .models import DocumentRecord, PageText

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pages (doc_id TEXT, n INTEGER, text TEXT, conf REAL, method TEXT, boxes TEXT, width INTEGER, height INTEGER,
                                  PRIMARY KEY (doc_id, n));
CREATE TABLE IF NOT EXISTS embeddings (key TEXT PRIMARY KEY, vec BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS notebook (id TEXT PRIMARY KEY, ts REAL, json TEXT NOT NULL);
"""


class Store:
    def __init__(self, data_dir: Path):
        self.dir = Path(data_dir)
        self.files = self.dir / "files"
        self.files.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.dir / "investigator.db", check_same_thread=False)
        self.db.executescript(SCHEMA)
        self._lock = threading.RLock()

    # -- documents ----------------------------------------------------------------------------
    def save_document(self, rec: DocumentRecord, pages: list[PageText], data: bytes) -> None:
        with self._lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO documents VALUES (?, ?)", (rec.id, json.dumps(rec.to_dict())))
            self.db.execute("DELETE FROM pages WHERE doc_id=?", (rec.id,))
            self.db.executemany(
                "INSERT INTO pages VALUES (?,?,?,?,?,?,?,?)",
                [(rec.id, p.number, p.text, p.ocr_conf, p.method, json.dumps(p.boxes), p.width, p.height) for p in pages])
        (self.files / f"{rec.id}{rec.ext}").write_bytes(data)

    def update_document(self, rec: DocumentRecord) -> None:
        with self._lock, self.db:
            self.db.execute("UPDATE documents SET json=? WHERE id=?", (json.dumps(rec.to_dict()), rec.id))

    def delete_document(self, doc_id: str, ext: str) -> None:
        with self._lock, self.db:
            self.db.execute("DELETE FROM documents WHERE id=?", (doc_id,))
            self.db.execute("DELETE FROM pages WHERE doc_id=?", (doc_id,))
        try:
            (self.files / f"{doc_id}{ext}").unlink(missing_ok=True)
        except OSError:
            pass

    def load_documents(self) -> list[tuple[DocumentRecord, list[PageText]]]:
        out = []
        with self._lock:
            rows = self.db.execute("SELECT json FROM documents").fetchall()
            for (js,) in rows:
                rec = DocumentRecord(**json.loads(js))
                prow = self.db.execute("SELECT n,text,conf,method,boxes,width,height FROM pages WHERE doc_id=? ORDER BY n", (rec.id,)).fetchall()
                pages = [PageText(n, t, c, m, json.loads(b or "[]"), w, h) for n, t, c, m, b, w, h in prow]
                out.append((rec, pages))
        out.sort(key=lambda x: x[0].added_at)
        return out

    def file_path(self, doc_id: str, ext: str) -> Path:
        return self.files / f"{doc_id}{ext}"

    # -- embeddings ---------------------------------------------------------------------------
    def load_embeddings(self) -> dict[str, np.ndarray]:
        with self._lock:
            return {k: np.frombuffer(v, dtype=np.float32) for k, v in self.db.execute("SELECT key, vec FROM embeddings")}

    def save_embeddings(self, items: dict[str, np.ndarray]) -> None:
        if not items:
            return
        with self._lock, self.db:
            self.db.executemany("INSERT OR REPLACE INTO embeddings VALUES (?,?)", [(k, v.astype(np.float32).tobytes()) for k, v in items.items()])

    # -- notebook -----------------------------------------------------------------------------
    def add_note(self, note_id: str, ts: float, payload: dict) -> None:
        with self._lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO notebook VALUES (?,?,?)", (note_id, ts, json.dumps(payload)))

    def notes(self) -> list[dict]:
        with self._lock:
            return [json.loads(js) for (js,) in self.db.execute("SELECT json FROM notebook ORDER BY ts")]

    def delete_note(self, note_id: str) -> None:
        with self._lock, self.db:
            self.db.execute("DELETE FROM notebook WHERE id=?", (note_id,))

    def clear_all(self) -> None:
        with self._lock, self.db:
            for t in ("documents", "pages", "embeddings"):
                self.db.execute(f"DELETE FROM {t}")
        for p in self.files.glob("*"):
            try:
                p.unlink()
            except OSError:
                pass
