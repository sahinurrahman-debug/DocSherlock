"""Format-specific text extraction. Every extractor returns page-structured text with '# ' heading markers."""
from __future__ import annotations

import csv
import email
import email.policy
import io
import json
import re
import statistics
import unicodedata
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path

from . import config, ocr
from .facts import parse_dates
from .models import Extracted, PageText


class ExtractionError(Exception):
    """Raised when a document cannot be read at all (corrupt, encrypted, unsupported...)."""


# ---------------------------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------------------------
def extract(filename: str, data: bytes) -> Extracted:
    ext = Path(filename).suffix.lower()
    if ext not in config.ALLOWED_EXTENSIONS:
        raise ExtractionError(f"Unsupported file type '{ext or 'unknown'}'. Supported: {', '.join(sorted(config.ALLOWED_EXTENSIONS))}")
    if not data:
        raise ExtractionError("The file is empty.")
    try:
        if ext == ".pdf":
            res = _pdf(data)
        elif ext == ".docx":
            res = _docx(data)
        elif ext in config.IMAGE_EXTENSIONS:
            res = _image(data)
        elif ext in (".csv", ".tsv"):
            res = _csv(data, "\t" if ext == ".tsv" else None)
        elif ext == ".xlsx":
            res = _xlsx(data)
        elif ext in (".html", ".htm"):
            res = _html(data)
        elif ext == ".json":
            res = _json(data)
        elif ext == ".eml":
            res = _eml(data)
        else:
            res = _text(data)
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError(f"Could not read {ext} file: {exc.__class__.__name__}: {exc}") from exc

    if not any(p.text.strip() for p in res.pages):
        if ext in config.IMAGE_EXTENSIONS or ext == ".pdf":
            reason = ocr.unavailable_reason()
            res.warnings.append("No text could be extracted." + (f" {reason}" if reason else " The image may contain no legible text."))
        else:
            res.warnings.append("No text could be extracted from this file.")
    return res


# ---------------------------------------------------------------------------------------------
# Plain text family
# ---------------------------------------------------------------------------------------------
def decode_bytes(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _clean(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)          # ligatures (fi), full-width forms, nbsp ...
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _text(data: bytes) -> Extracted:
    return Extracted([PageText(1, _clean(decode_bytes(data)))], paged=False)


def _json(data: bytes) -> Extracted:
    raw = decode_bytes(data)
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return Extracted([PageText(1, _clean(raw))], paged=False, warnings=["Invalid JSON - indexed as plain text."])
    lines: list[str] = []

    def walk(o, path):
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, f"{path}.{k}" if path else str(k))
        elif isinstance(o, list):
            for i, v in enumerate(o[:2000]):
                walk(v, f"{path}[{i}]")
        else:
            lines.append(f"{path}: {o}")

    walk(obj, "")
    return Extracted([PageText(1, "\n".join(lines))], paged=False)


_UNIT_HDR = re.compile(r"\s*\(\s*(%|\$|usd|eur|gbp|inr|€|£|₹|days?|hours?|months?|years?)\s*\)\s*$", re.I)


def _with_unit(header: str, value: str) -> tuple[str, str]:
    """'On-time rate (%)' + '96.2' -> ('On-time rate', '96.2%') so the unit survives into the sentence."""
    m = _UNIT_HDR.search(header)
    if not m or not value or not re.fullmatch(r"[\d.,]+", value):
        return header, value
    u = m.group(1).lower()
    base = header[: m.start()].strip()
    if u == "%":
        return base, f"{value}%"
    if u in ("$", "usd", "eur", "gbp", "inr") or u in ("€", "£", "₹"):
        sym = {"usd": "$", "eur": "€", "gbp": "£", "inr": "₹"}.get(u, u)
        return base, f"{sym}{value}"
    return base, f"{value} {u}"


def _rows_to_text(rows: list[list[str]], title: str | None = None) -> str:
    rows = [[(c or "").strip() for c in r] for r in rows if any((c or "").strip() for c in r)]
    if not rows:
        return ""
    header = rows[0]
    looks_header = len(rows) > 1 and all(h and not re.fullmatch(r"[\d.,%$\s-]+", h) for h in header) and len(set(header)) == len(header)
    out = [f"# {title}"] if title else []
    if looks_header:
        for r in rows[1:]:
            out.append("; ".join(f"{h2}: {v2}" for h2, v2 in (_with_unit(h, v) for h, v in zip(header, r)) if v2))
    else:
        out.extend(" | ".join(r) for r in rows)
    return "\n".join(out)


def _csv(data: bytes, delim: str | None) -> Extracted:
    raw = decode_bytes(data)
    if delim is None:
        try:
            delim = csv.Sniffer().sniff(raw[:4096], delimiters=",;|\t").delimiter
        except csv.Error:
            delim = ","
    rows = list(csv.reader(io.StringIO(raw), delimiter=delim))
    warnings = []
    if len(rows) > 5000:
        rows = rows[:5000]
        warnings.append("Only the first 5000 rows were indexed.")
    return Extracted([PageText(1, _rows_to_text(rows))], paged=False, warnings=warnings)


def _xlsx(data: bytes) -> Extracted:
    try:
        import openpyxl
    except ImportError as exc:
        raise ExtractionError("openpyxl is required for .xlsx files") from exc
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    pages = []
    warnings = []
    for i, ws in enumerate(wb.worksheets, 1):
        rows = []
        for r in ws.iter_rows(values_only=True):
            rows.append(["" if c is None else str(c) for c in r])
            if len(rows) >= 5000:
                warnings.append(f"Sheet '{ws.title}' truncated to 5000 rows.")
                break
        pages.append(PageText(i, _rows_to_text(rows, title=ws.title), method="xlsx"))
    return Extracted(pages or [PageText(1, "")], paged=True, warnings=warnings)


class _HTMLText(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "section", "article", "table", "ul", "ol", "header", "footer"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0
        self.title: str | None = None
        self._in_title = False
        self._heading = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg"):
            self.skip += 1
        elif tag == "title":
            self._in_title = True
        elif re.fullmatch(r"h[1-6]", tag):
            self.out.append("\n\n# ")
            self._heading = True
        elif tag in ("td", "th"):
            self.out.append(" | ")
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg"):
            self.skip = max(0, self.skip - 1)
        elif tag == "title":
            self._in_title = False
        elif re.fullmatch(r"h[1-6]", tag):
            self.out.append("\n")
            self._heading = False
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if self.skip:
            return
        if self._in_title:
            self.title = (self.title or "") + data
            return
        self.out.append(data)


def _html(data: bytes) -> Extracted:
    p = _HTMLText()
    p.feed(decode_bytes(data))
    text = "".join(p.out)
    text = re.sub(r"\n[ \t]*\|\s*", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    meta = {"title": p.title.strip()} if p.title else {}
    return Extracted([PageText(1, _clean(text))], paged=False, meta=meta)


def _eml(data: bytes) -> Extracted:
    msg = email.message_from_bytes(data, policy=email.policy.default)
    body = msg.get_body(preferencelist=("plain", "html"))
    text = ""
    if body is not None:
        content = body.get_content()
        if body.get_content_type() == "text/html":
            p = _HTMLText()
            p.feed(content)
            content = "".join(p.out)
        text = content
    head = []
    for h in ("From", "To", "Cc", "Date", "Subject"):
        if msg[h]:
            head.append(f"{h}: {msg[h]}")
    meta = {}
    if msg["Subject"]:
        meta["title"] = str(msg["Subject"])
    try:
        if msg["Date"]:
            meta["date"] = parsedate_to_datetime(str(msg["Date"])).date().isoformat()
    except (TypeError, ValueError):
        pass
    warnings = []
    atts = [p.get_filename() for p in msg.iter_attachments() if p.get_filename()]
    if atts:
        warnings.append("Attachments not indexed (upload them separately): " + ", ".join(atts))
    return Extracted([PageText(1, _clean("\n".join(head) + "\n\n" + text))], paged=False, meta=meta, warnings=warnings)


# ---------------------------------------------------------------------------------------------
# Images / OCR
# ---------------------------------------------------------------------------------------------
def _image(data: bytes) -> Extracted:
    from PIL import Image, ImageSequence

    img = Image.open(io.BytesIO(data))
    frames = [f.copy() for f in ImageSequence.Iterator(img)][:30] if getattr(img, "n_frames", 1) > 1 else [img]
    pages: list[PageText] = []
    warnings: list[str] = []
    if not ocr.available():
        return Extracted([PageText(1, "", method="ocr")], warnings=[ocr.unavailable_reason() or "OCR unavailable."])
    for i, frame in enumerate(frames, 1):
        lines, w, h = ocr.ocr_pil(frame)
        text, boxes, conf = ocr.lines_to_text(lines)
        pages.append(PageText(i, text, ocr_conf=conf, method="ocr", boxes=boxes, width=w, height=h))
    confs = [p.ocr_conf for p in pages if p.ocr_conf is not None]
    if confs and statistics.mean(confs) < 0.75:
        warnings.append(f"Low OCR confidence ({statistics.mean(confs):.0%}); extracted values may contain errors.")
    return Extracted(pages, paged=True, warnings=warnings)


# ---------------------------------------------------------------------------------------------
# PDF (born-digital text with heading detection, tables, and per-page OCR fallback for scans)
# ---------------------------------------------------------------------------------------------
def _pdf(data: bytes) -> Extracted:
    import pymupdf

    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise ExtractionError(f"Corrupt or unreadable PDF ({exc})") from exc
    if doc.needs_pass:
        raise ExtractionError("The PDF is password protected.")
    n = doc.page_count
    warnings: list[str] = []
    if n > config.MAX_PDF_PAGES:
        warnings.append(f"Only the first {config.MAX_PDF_PAGES} of {n} pages were indexed.")
        n = config.MAX_PDF_PAGES
    pages: list[PageText] = []
    meta = {}
    title = (doc.metadata or {}).get("title")
    if title and len(title.strip()) > 3:
        meta["title"] = title.strip()
    ocr_pages = 0
    for i in range(n):
        page = doc[i]
        text = _pdf_page_text(page)
        digital_chars = len(re.sub(r"\s", "", text))
        needs_ocr = digital_chars < 40
        if not needs_ocr:
            img_area = _image_coverage(page)
            if img_area > 0.5 and digital_chars < 250:
                needs_ocr = True
        if needs_ocr and ocr.available():
            pix = page.get_pixmap(dpi=200)
            png = pix.tobytes("png")
            lines, w, h = ocr.ocr_image_bytes(png)
            otext, boxes, conf = ocr.lines_to_text(lines)
            if len(re.sub(r"\s", "", otext)) > digital_chars:
                pages.append(PageText(i + 1, otext, ocr_conf=conf, method="ocr", boxes=boxes, width=w, height=h))
                ocr_pages += 1
                continue
        pages.append(PageText(i + 1, text, method="text"))
    if ocr_pages:
        warnings.append(f"{ocr_pages} scanned page(s) were read with OCR.")
        low = [p.ocr_conf for p in pages if p.ocr_conf is not None and p.ocr_conf < 0.75]
        if low:
            warnings.append("Some pages have low OCR confidence; extracted values may contain errors.")
    elif not any(p.text.strip() for p in pages) and not ocr.available():
        warnings.append(ocr.unavailable_reason())
    return Extracted(pages, paged=True, warnings=warnings, meta=meta)


def _image_coverage(page) -> float:
    try:
        total = page.rect.width * page.rect.height or 1
        area = 0.0
        for info in page.get_image_info():
            x0, y0, x1, y1 = info["bbox"]
            area += max(0, x1 - x0) * max(0, y1 - y0)
        return min(1.0, area / total)
    except Exception:
        return 0.0


def _pdf_page_text(page) -> str:
    d = page.get_text("dict")
    sizes: list[tuple[float, int]] = []
    for b in d["blocks"]:
        if b.get("type") != 0:
            continue
        for ln in b["lines"]:
            for sp in ln["spans"]:
                sizes.append((sp["size"], len(sp["text"])))
    if not sizes:
        return ""
    weights: dict[float, int] = {}
    for s, c in sizes:
        weights[round(s, 1)] = weights.get(round(s, 1), 0) + c
    body = max(weights, key=weights.get)

    table_boxes, table_items = [], []
    try:
        for t in page.find_tables().tables:
            rows = t.extract()
            txt = _rows_to_text([[c or "" for c in r] for r in rows])
            if txt:
                table_boxes.append(pymupdf_rect(t.bbox))
                table_items.append((t.bbox[1], t.bbox[0], txt))
    except Exception:
        table_boxes, table_items = [], []

    items: list[tuple[float, float, str]] = list(table_items)
    for b in d["blocks"]:
        if b.get("type") != 0:
            continue
        x0, y0, x1, y1 = b["bbox"]
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        if any(r[0] <= cx <= r[2] and r[1] <= cy <= r[3] for r in table_boxes):
            continue
        para_lines: list[str] = []
        heading_flags: list[bool] = []
        for ln in b["lines"]:
            txt = "".join(sp["text"] for sp in ln["spans"]).strip()
            if not txt:
                continue
            ln_size = max((sp["size"] for sp in ln["spans"]), default=body)
            bold = all(("bold" in sp["font"].lower() or sp["flags"] & 16) for sp in ln["spans"] if sp["text"].strip())
            heading_flags.append(ln_size >= body * 1.18 or (bold and len(txt) < 80 and not txt.endswith((".", ","))))
            para_lines.append(txt)
        if not para_lines:
            continue
        if all(heading_flags) and len(" ".join(para_lines)) < 140:
            items.append((y0, x0, "# " + " ".join(para_lines)))
        elif heading_flags[0] and len(para_lines[0]) < 100 and len(para_lines) > 1 and not any(heading_flags[1:]):
            items.append((y0, x0, "# " + para_lines[0] + "\n" + _join_wrapped(para_lines[1:])))
        else:
            items.append((y0, x0, _join_wrapped(para_lines)))
    items.sort(key=lambda t: (round(t[0] / 4), t[1]))
    return _clean("\n\n".join(t[2] for t in items))


def pymupdf_rect(b):
    return (b[0], b[1], b[2], b[3])


def _join_wrapped(lines: list[str]) -> str:
    """Join hard-wrapped PDF lines into a paragraph, but keep bullets / short list-like lines separate."""
    out: list[str] = []
    for ln in lines:
        if out and not re.match(r"^(?:[•\-–*]|\d+[.)])\s", ln) and not out[-1].endswith((":",)):
            if out[-1].endswith("-") and out[-1][-2:-1].isalpha():
                out[-1] = out[-1][:-1] + ln
            else:
                out[-1] += " " + ln
        else:
            out.append(ln)
    return "\n".join(out)


# ---------------------------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------------------------
def _docx(data: bytes) -> Extracted:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        d = docx.Document(io.BytesIO(data))
    except Exception as exc:
        raise ExtractionError(f"Corrupt or unreadable DOCX ({exc})") from exc
    lines: list[str] = []
    for child in d.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(child, d)
            txt = p.text.strip()
            if not txt:
                lines.append("")
                continue
            style = (p.style.name or "").lower() if p.style is not None else ""
            if style.startswith("heading") or style == "title":
                lines.append("\n# " + txt)
            elif "list" in style:
                lines.append("- " + txt)
            else:
                lines.append(txt)
        elif tag == "tbl":
            t = Table(child, d)
            rows = [[c.text.replace("\n", " ") for c in r.cells] for r in t.rows]
            # merged cells repeat; drop consecutive duplicates
            rows = [[c for i, c in enumerate(r) if i == 0 or c != r[i - 1]] for r in rows]
            lines.append(_rows_to_text(rows))
            lines.append("")
    warnings: list[str] = []
    meta = {}
    cp = d.core_properties
    if cp.title and len(cp.title.strip()) > 3:
        meta["title"] = cp.title.strip()
    # text inside embedded images (screenshots, scans)
    if ocr.available():
        extra = []
        confs = []
        for rel in d.part.rels.values():
            if "image" in rel.reltype:
                try:
                    ln, _, _ = ocr.ocr_image_bytes(rel.target_part.blob)
                    t, _, c = ocr.lines_to_text(ln)
                    if t.strip():
                        extra.append(t)
                        confs.append(c)
                except Exception:
                    continue
        if extra:
            lines.append("\n# Text recovered from embedded images\n" + "\n\n".join(extra))
            warnings.append(f"Text from {len(extra)} embedded image(s) was read with OCR.")
    text = _clean("\n".join(lines))
    page = PageText(1, text, method="docx")
    return Extracted([page], paged=False, warnings=warnings, meta=meta)


# ---------------------------------------------------------------------------------------------
# Document date detection (used to explain conflicts: "B is newer than A")
# ---------------------------------------------------------------------------------------------
_CUE = re.compile(
    r"(?:\bdated?\b|\beffective(?:\s+date)?\b|\bas\s+of\b|\bupdated?\b|\blast\s+(?:updated|revised|modified)\b|\brevised\b|\bissued?\b|"
    r"\bmeeting\s+(?:held\s+)?on\b|\bsigned(?:\s+on)?\b|\bpublished\b|\bversion\s+date\b)[\s:,\-]*$", re.I)


def detect_doc_date(filename: str, extracted: Extracted) -> tuple[str | None, str | None]:
    if extracted.meta.get("date"):
        return extracted.meta["date"], "email header"
    first = next((p.text for p in extracted.pages if p.text.strip()), "")
    head = first[:2500]
    cued: list[tuple[int, str]] = []
    for iso, a, b in parse_dates(head):
        if _CUE.search(head[max(0, a - 30):a]):
            cued.append((a, iso))
    if cued:
        return min(cued)[1], "stated in document"
    near = [(a, iso) for iso, a, b in parse_dates(head[:500])]
    if near:
        return min(near)[1], "first date in document"
    m = re.search(r"(?<!\d)((?:19|20)\d{2})[-_.]?(0[1-9]|1[0-2])[-_.]?(0[1-9]|[12]\d|3[01])(?!\d)", filename)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}", "file name"
    m = re.search(r"(?<!\d)((?:19|20)\d{2})(?!\d)", filename)
    if m:
        return m.group(1), "file name (year only)"
    return None, None
