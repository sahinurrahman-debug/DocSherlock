"""OCR wrapper around RapidOCR (ONNX, fully offline, no system binaries required)."""
from __future__ import annotations

import io
import logging
import statistics
import threading
from dataclasses import dataclass

from app.core.config import settings

log = logging.getLogger("docinv.ocr")

_engine = None
_engine_error: str | None = None
_lock = threading.Lock()

MAX_SIDE = 2600


@dataclass
class OcrLine:
    text: str
    conf: float
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def h(self) -> float:
        return self.y1 - self.y0


def available() -> bool:
    if not settings.ocr_enabled:
        return False
    return _get_engine() is not None


def unavailable_reason() -> str:
    if not settings.ocr_enabled:
        return "OCR disabled by configuration (DOCINV_OCR=off)."
    _get_engine()
    return _engine_error or ""


def _get_engine():
    global _engine, _engine_error
    if _engine is not None or _engine_error is not None:
        return _engine
    with _lock:
        if _engine is None and _engine_error is None:
            try:
                from rapidocr import RapidOCR  # type: ignore
                logging.getLogger("RapidOCR").setLevel(logging.WARNING)
                _engine = RapidOCR(params={"Global.log_level": "warning"})
            except Exception as exc:  # pragma: no cover - depends on environment
                _engine_error = f"OCR engine unavailable ({exc.__class__.__name__}: {exc}). Install `rapidocr`."
                log.warning(_engine_error)
    return _engine


def ocr_image_bytes(data: bytes) -> tuple[list[OcrLine], int, int]:
    """Run OCR on encoded image bytes. Returns (lines, width, height) with coordinates in the *returned* image size."""
    from PIL import Image, ImageOps
    import numpy as np

    img = Image.open(io.BytesIO(data))
    return ocr_pil(img, np, ImageOps)


def ocr_pil(img, np=None, ImageOps=None) -> tuple[list[OcrLine], int, int]:
    if np is None:
        import numpy as np  # noqa: F811
    if ImageOps is None:
        from PIL import ImageOps  # noqa: F811
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    if max(img.size) > MAX_SIDE:
        scale = MAX_SIDE / max(img.size)
        img = img.resize((int(img.width * scale), int(img.height * scale)))
    w, h = img.size
    engine = _get_engine()
    if engine is None:
        return [], w, h
    arr = np.array(img.convert("RGB"))
    with _lock:   # the ONNX session is not guaranteed thread safe
        result = engine(arr)
    txts = getattr(result, "txts", None)
    boxes = getattr(result, "boxes", None)
    scores = getattr(result, "scores", None)
    lines: list[OcrLine] = []
    if txts is None or boxes is None:
        return lines, w, h
    for txt, box, sc in zip(txts, boxes, scores):
        if not str(txt).strip():
            continue
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        lines.append(OcrLine(str(txt).strip(), float(sc), float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys))))
    return lines, w, h


def lines_to_text(lines: list[OcrLine]) -> tuple[str, list[list], float | None]:
    """Rebuild reading-order text (rows -> lines, vertical gaps -> paragraphs) and return boxes in the same order."""
    if not lines:
        return "", [], None
    heights = [l.h for l in lines if l.h > 0]
    med_h = statistics.median(heights) if heights else 12.0
    ordered = sorted(lines, key=lambda l: ((l.y0 + l.y1) / 2, l.x0))

    rows: list[list[OcrLine]] = []
    for ln in ordered:
        cy = (ln.y0 + ln.y1) / 2
        if rows:
            last = rows[-1]
            ref_cy = sum((l.y0 + l.y1) / 2 for l in last) / len(last)
            if abs(cy - ref_cy) < max(ln.h, med_h) * 0.55:
                last.append(ln)
                continue
        rows.append([ln])

    # row texts first so headings can look ahead at the following row
    texts: list[str] = []
    for row in rows:
        row.sort(key=lambda l: l.x0)
        text = row[0].text
        for x, y in zip(row, row[1:]):
            text += (" | " if y.x0 - x.x1 > med_h * 3 else " ") + y.text
        texts.append(text)

    def looks_like_heading(i: int) -> bool:
        row = rows[i]
        text = texts[i]
        row_h = statistics.median([l.h for l in row])
        if len(text) >= 90 or text.rstrip().endswith((".", ",", ";", ":")) and len(text.split()) > 4:
            return False
        if row_h >= med_h * 1.2 and not text.rstrip().endswith((".", ",")):
            return True
        nxt = texts[i + 1] if i + 1 < len(texts) else ""
        return len(text.split()) <= 5 and not text.rstrip().endswith((".", ",", ";", "|")) and len(nxt) >= 1.6 * len(text) and " | " not in text

    out_lines: list[str] = []
    boxes: list[list] = []
    prev_bottom = None
    prev_heading = False
    for i, row in enumerate(rows):
        text = texts[i]
        top = min(l.y0 for l in row)
        bottom = max(l.y1 for l in row)
        is_heading = looks_like_heading(i)
        gap_v = (top - prev_bottom) if prev_bottom is not None else 0
        tabular = " | " in text
        bullet = text.lstrip().startswith(("-", "•", "*")) or text[:3].rstrip(".) ").isdigit()
        # wrapped lines of one paragraph touch/overlap (detector boxes are padded); real breaks leave a visible gap
        new_para = (not out_lines) or is_heading or prev_heading or tabular or bullet or gap_v > med_h * 0.12 or out_lines[-1] == ""
        if new_para:
            if out_lines and out_lines[-1] != "":
                out_lines.append("")
            out_lines.append(("# " + text) if is_heading else text)
        else:
            joined = out_lines[-1]
            out_lines[-1] = (joined[:-1] + text) if joined.endswith("-") and joined[-2:-1].isalpha() else joined + " " + text
        prev_bottom, prev_heading = bottom, is_heading
        for l in row:
            boxes.append([round(l.x0, 1), round(l.y0, 1), round(l.x1, 1), round(l.y1, 1), l.text, round(l.conf, 3)])
    conf = sum(l.conf for l in lines) / len(lines)
    return "\n".join(out_lines), boxes, conf
