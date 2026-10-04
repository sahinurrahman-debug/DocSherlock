"""Render a source page (PDF or image) as PNG with the cited passage highlighted: text search on born-digital PDFs, OCR boxes on scans."""
from __future__ import annotations

import io
import re
from pathlib import Path

from app.core.config import settings


def render_page(path: Path, file_type: str, page, quote: str, scale: float) -> bytes | None:
    """`page` needs: number, method, boxes, width."""
    from PIL import Image

    if not path.exists():
        return None
    if file_type == ".pdf":
        import pymupdf
        doc = pymupdf.open(path)
        try:
            pg = doc[page.page_number - 1]
            if page.method == "text" and quote:
                q = quote.strip()
                rects = []
                for nd in (q, q[:120], q[:60]):              # progressively shorter needles: line wraps / hyphenation must not defeat us
                    rects = pg.search_for(nd[:200]) if nd else []
                    if rects:
                        break
                if not rects:
                    for frag in re.split(r"[,;:]\s+", q)[:6]:
                        if len(frag) > 12:
                            rects += pg.search_for(frag)
                for r in rects:
                    pg.draw_rect(r, color=None, fill=(1, 0.85, 0.2), fill_opacity=0.45, overlay=True)
            png = pg.get_pixmap(matrix=pymupdf.Matrix(scale, scale)).tobytes("png")
        finally:
            doc.close()
        if page.method == "ocr" and quote:
            img = Image.open(io.BytesIO(png)).convert("RGBA")
            _draw_boxes(img, page, quote, img.width / (page.width or img.width))
            out = io.BytesIO()
            img.convert("RGB").save(out, "PNG")
            return out.getvalue()
        return png
    if file_type in settings.image_extensions:
        from PIL import ImageOps, ImageSequence
        img = Image.open(path)
        frames = [f.copy() for f in ImageSequence.Iterator(img)] if getattr(img, "n_frames", 1) > 1 else [img]
        img = ImageOps.exif_transpose(frames[min(page.page_number - 1, len(frames) - 1)]).convert("RGBA")
        k = img.width / page.width if page.width and img.width != page.width else 1.0   # OCR ran on a down-scaled copy
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
    for x0, y0, x1, y1, text, conf in page.boxes or []:
        t = re.sub(r"\s+", " ", text).lower().strip()
        if len(t) >= 3 and t in qn:
            d.rectangle([x0 * k - 3, y0 * k - 2, x1 * k + 3, y1 * k + 2], fill=(255, 215, 40, 110), outline=(230, 150, 0, 255), width=2)
    img.alpha_composite(layer)
