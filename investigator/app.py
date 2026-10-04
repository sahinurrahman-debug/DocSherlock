"""FastAPI application: JSON API + static single-page UI."""
from __future__ import annotations

import io
import logging
import re
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config
from .engine import Engine, IngestError

log = logging.getLogger("docinv.app")
STATIC = Path(__file__).parent / "static"


class AskBody(BaseModel):
    question: str = Field(..., max_length=2000)
    history: list[dict] = Field(default_factory=list, max_length=20)
    mode: str = Field("auto", pattern="^(auto|offline|llm)$")


class DateBody(BaseModel):
    doc_date: Optional[str] = None


class NoteBody(BaseModel):
    result: dict
    comment: str = ""


def create_app(engine: Engine | None = None) -> FastAPI:
    app = FastAPI(title="Intelligent Document Investigator", version="1.0.0")
    eng = engine or Engine()
    app.state.engine = eng

    # ------------------------------------------------------------------ system
    @app.get("/api/status")
    def status():
        return eng.status()

    # --------------------------------------------------------------- documents
    @app.get("/api/documents")
    def list_documents():
        return {"documents": eng.documents()}

    @app.post("/api/documents")
    async def upload(files: list[UploadFile] = File(...)):
        results = []
        for f in files:
            data = await f.read()
            try:
                import anyio
                res = await anyio.to_thread.run_sync(eng.ingest, f.filename or "document", data)
                res["filename"] = f.filename
                res["ok"] = True
            except IngestError as exc:
                res = {"filename": f.filename, "ok": False, "error": str(exc)}
            except Exception as exc:   # never let one bad file break a batch
                log.exception("ingest failed for %s", f.filename)
                res = {"filename": f.filename, "ok": False, "error": f"Unexpected error while reading file: {exc.__class__.__name__}"}
            results.append(res)
        return {"results": results, "documents": eng.documents(), "conflicts": len(eng.conflicts())}

    @app.delete("/api/documents/{doc_id}")
    def delete_document(doc_id: str):
        if not eng.delete(doc_id):
            raise HTTPException(404, "Document not found")
        return {"ok": True, "documents": eng.documents(), "conflicts": len(eng.conflicts())}

    @app.delete("/api/documents")
    def reset():
        eng.reset()
        return {"ok": True}

    @app.patch("/api/documents/{doc_id}")
    def patch_document(doc_id: str, body: DateBody):
        try:
            rec = eng.set_doc_date(doc_id, body.doc_date)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        if not rec:
            raise HTTPException(404, "Document not found")
        return {"document": rec.to_dict(), "conflicts": len(eng.conflicts())}

    @app.post("/api/demo/load")
    async def load_demo():
        import anyio
        try:
            results = await anyio.to_thread.run_sync(eng.load_demo)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc))
        return {"results": results, "documents": eng.documents(), "conflicts": len(eng.conflicts())}

    @app.get("/api/documents/{doc_id}/pages/{n}")
    def get_page(doc_id: str, n: int):
        pages = eng.get_pages(doc_id)
        rec = eng.get_document(doc_id)
        if not pages or not rec:
            raise HTTPException(404, "Document not found")
        page = next((p for p in pages if p.number == n), None)
        if page is None:
            raise HTTPException(404, "Page not found")
        return {"document": rec.to_dict(), "page": {"number": page.number, "text": page.text, "ocr_conf": page.ocr_conf, "method": page.method,
                                                     "has_image": rec.ext == ".pdf" or rec.ext in config.IMAGE_EXTENSIONS},
                "n_pages": len(pages)}

    @app.get("/api/documents/{doc_id}/pages/{n}/image")
    def page_image(doc_id: str, n: int, start: int = -1, end: int = -1, scale: float = 1.6):
        """Render the page (PDF or image) with the cited passage highlighted."""
        rec = eng.get_document(doc_id)
        pages = eng.get_pages(doc_id)
        if not rec or not pages:
            raise HTTPException(404, "Document not found")
        page = next((p for p in pages if p.number == n), None)
        if page is None:
            raise HTTPException(404, "Page not found")
        quote = page.text[start:end] if 0 <= start < end <= len(page.text) else ""
        png = _render_page(eng, rec, page, quote, max(0.8, min(scale, 3.0)))
        if png is None:
            raise HTTPException(415, "This document type has no page image")
        return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.get("/api/documents/{doc_id}/file")
    def original_file(doc_id: str):
        rec = eng.get_document(doc_id)
        if not rec:
            raise HTTPException(404, "Document not found")
        path = eng.store.file_path(doc_id, rec.ext)
        if not path.exists():
            raise HTTPException(404, "File missing")
        return FileResponse(path, filename=rec.name)

    # -------------------------------------------------------------- investigate
    @app.post("/api/ask")
    async def ask(body: AskBody):
        import anyio
        try:
            return await anyio.to_thread.run_sync(lambda: eng.ask(body.question, body.history, body.mode))
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.get("/api/conflicts")
    def conflicts():
        return {"conflicts": eng.conflicts()}

    # ----------------------------------------------------------------- notebook
    @app.get("/api/notebook")
    def notebook():
        return {"notes": eng.notes()}

    @app.post("/api/notebook")
    def add_note(body: NoteBody):
        return eng.add_note(body.result, body.comment)

    @app.delete("/api/notebook/{note_id}")
    def delete_note(note_id: str):
        eng.delete_note(note_id)
        return {"ok": True}

    @app.get("/api/notebook/export")
    def export():
        return PlainTextResponse(eng.export_markdown(), media_type="text/markdown",
                                 headers={"Content-Disposition": 'attachment; filename="investigation-report.md"'})

    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    return app


def _render_page(eng: Engine, rec, page, quote: str, scale: float) -> bytes | None:
    from PIL import Image

    path = eng.store.file_path(rec.id, rec.ext)
    if not path.exists():
        return None
    if rec.ext == ".pdf":
        import pymupdf
        doc = pymupdf.open(path)
        pg = doc[page.number - 1]
        if page.method == "text" and quote:
            # search with progressively shorter needles so line wraps/hyphenation do not defeat us
            needles = [quote.strip(), quote.strip()[:120], quote.strip()[:60]]
            rects = []
            for nd in needles:
                rects = pg.search_for(nd[:200]) if nd else []
                if rects:
                    break
            if not rects:       # fall back to sentence fragments
                for frag in re.split(r"[,;:]\s+", quote.strip())[:6]:
                    if len(frag) > 12:
                        rects += pg.search_for(frag)
            for r in rects:
                pg.draw_rect(r, color=None, fill=(1, 0.85, 0.2), fill_opacity=0.45, overlay=True)
        pix = pg.get_pixmap(matrix=pymupdf.Matrix(scale, scale))
        png = pix.tobytes("png")
        if page.method == "ocr" and quote:
            img = Image.open(io.BytesIO(png)).convert("RGBA")
            _draw_boxes(img, page, quote, img.width / (page.width or img.width))
            out = io.BytesIO()
            img.convert("RGB").save(out, "PNG")
            return out.getvalue()
        return png
    if rec.ext in config.IMAGE_EXTENSIONS:
        from PIL import ImageOps, ImageSequence
        img = Image.open(path)
        frames = [f.copy() for f in ImageSequence.Iterator(img)] if getattr(img, "n_frames", 1) > 1 else [img]
        img = ImageOps.exif_transpose(frames[min(page.number - 1, len(frames) - 1)]).convert("RGBA")
        k = 1.0
        if page.width and img.width != page.width:       # OCR coordinates were computed on a down-scaled copy
            k = img.width / page.width
        if quote:
            _draw_boxes(img, page, quote, k)
        if img.width > 1800:
            img = img.resize((1800, int(img.height * 1800 / img.width)))
        out = io.BytesIO()
        img.convert("RGB").save(out, "PNG")
        return out.getvalue()
    return None


def _draw_boxes(img, page, quote: str, k: float) -> None:
    from PIL import Image, ImageDraw

    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    qn = re.sub(r"\s+", " ", quote).lower()
    for x0, y0, x1, y1, text, conf in page.boxes:
        t = re.sub(r"\s+", " ", text).lower().strip()
        if len(t) >= 3 and t in qn:
            d.rectangle([x0 * k - 3, y0 * k - 2, x1 * k + 3, y1 * k + 2], fill=(255, 215, 40, 110), outline=(230, 150, 0, 255), width=2)
    img.alpha_composite(layer)
