"""Typed fact extraction: money, percentages, durations, dates and plain numbers found in sentences.

These typed values are what make *deterministic* conflict detection possible: two sentences about the same
subject that carry incompatible values of the same kind are a conflict candidate.
"""
from __future__ import annotations

import re
from datetime import date

from app.domain import Quantity, Fact
from app.utils.text import STOPWORDS, stem, tokenize, negation_count

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"], 1)}
_MON_ABBR = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12}
MONTHS = {**MONTHS, **_MON_ABBR}
_MON = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"

_ONES = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
         "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
         "seventeen": 17, "eighteen": 18, "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_NW = "|".join(sorted({*_ONES, *_TENS, "hundred", "thousand"}, key=len, reverse=True))
_NUMWORD = rf"(?:(?:{_NW})(?:[\s-]+(?:and\s+)?(?:{_NW}))*)"
_DIGITS = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
_NUM = rf"(?:{_DIGITS}|{_NUMWORD})"
_NUM_PAREN = rf"{_NUM}(?:\s*\(\s*(?:{_DIGITS})\s*\))?"

_MULT = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "bn": 1e9, "b": 1e9, "billion": 1e9,
         "lakh": 1e5, "lakhs": 1e5, "crore": 1e7, "crores": 1e7}
_CUR_SYM = {"$": "USD", "us$": "USD", "usd": "USD", "€": "EUR", "eur": "EUR", "£": "GBP", "gbp": "GBP",
            "₹": "INR", "inr": "INR", "rs": "INR", "rs.": "INR"}
_CUR_WORD = {"dollars": "USD", "dollar": "USD", "euros": "EUR", "euro": "EUR", "pounds": "GBP", "rupees": "INR", "usd": "USD",
             "eur": "EUR", "gbp": "GBP", "inr": "INR"}

_DUR_UNIT = {"day": ("day", 1), "week": ("day", 7), "month": ("day", 30), "year": ("day", 365), "quarter": ("day", 91),
             "hour": ("hour", 1), "minute": ("minute", 1)}

_SECTION_CTX = re.compile(
    r"(?:section|sec|clause|article|page|pg|pp|p|figure|fig|table|appendix|annex|schedule|exhibit|no|nos|number|item|step|chapter|"
    r"para|paragraph|version|ver|v|rev|revision|ref|id|ticket|invoice|po|order|#|phase|part|row|line)\.?\s*#?\s*$", re.IGNORECASE)


def words_to_number(s: str) -> float | None:
    toks = [t for t in re.split(r"[\s-]+", s.lower()) if t and t != "and"]
    if not toks:
        return None
    total, cur = 0, 0
    for t in toks:
        if t in _ONES:
            cur += _ONES[t]
        elif t in _TENS:
            cur += _TENS[t]
        elif t == "hundred":
            cur = max(cur, 1) * 100
        elif t == "thousand":
            total += max(cur, 1) * 1000
            cur = 0
        else:
            return None
    return float(total + cur)


def _to_number(raw: str) -> float | None:
    raw = raw.strip()
    m = re.search(r"\(\s*(" + _DIGITS + r")\s*\)", raw)       # "sixty (60)" -> 60
    if m:
        return float(m.group(1).replace(",", ""))
    if re.fullmatch(_DIGITS, raw):
        return float(raw.replace(",", ""))
    return words_to_number(raw)


def _iso(y: int, m: int | None = None, d: int | None = None) -> str | None:
    try:
        if m is None:
            return f"{y:04d}"
        if d is None:
            date(y, m, 1)
            return f"{y:04d}-{m:02d}"
        date(y, m, d)
        return f"{y:04d}-{m:02d}-{d:02d}"
    except ValueError:
        return None


_DATE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "ymd"),
    (re.compile(rf"\b({_MON})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I), "mdy"),
    (re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MON})\.?,?\s+(\d{{4}})\b", re.I), "dmy"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})\b"), "slash"),
    (re.compile(rf"\b({_MON})\.?,?\s+(\d{{4}})\b", re.I), "my"),
]


def parse_dates(text: str) -> list[tuple[str, int, int]]:
    """Return [(iso, start, end)] for every date expression, non-overlapping, in order."""
    found: list[tuple[str, int, int]] = []
    taken: list[tuple[int, int]] = []
    for pat, kind in _DATE_PATTERNS:
        for m in pat.finditer(text):
            if any(m.start() < b and m.end() > a for a, b in taken):
                continue
            g = m.groups()
            iso = None
            if kind == "ymd":
                iso = _iso(int(g[0]), int(g[1]), int(g[2]))
            elif kind == "mdy":
                iso = _iso(int(g[2]), MONTHS[g[0][:3].lower()], int(g[1]))
            elif kind == "dmy":
                iso = _iso(int(g[2]), MONTHS[g[1][:3].lower()], int(g[0]))
            elif kind == "slash":
                a, b, y = int(g[0]), int(g[1]), int(g[2])
                y = y + 2000 if y < 100 else y
                iso = _iso(y, a, b) if a <= 12 else _iso(y, b, a)
                if iso is None:
                    iso = _iso(y, b, a)
            elif kind == "my":
                iso = _iso(int(g[1]), MONTHS[g[0][:3].lower()])
            if iso:
                found.append((iso, m.start(), m.end()))
                taken.append((m.start(), m.end()))
    found.sort(key=lambda x: x[1])
    return found


def date_sort_key(iso: str | None) -> str:
    if not iso:
        return ""
    parts = iso.split("-")
    parts += ["01"] * (3 - len(parts))
    return "-".join(parts)


def dates_compatible(a: str, b: str) -> bool:
    """'2023-03' is compatible with '2023-03-04' (coarser precision); otherwise dates must match."""
    return a == b or a.startswith(b) or b.startswith(a)


_MONEY_PRE = re.compile(
    rf"(?P<cur>US\$|[$€£₹]|\b(?:USD|EUR|GBP|INR)\b|\bRs\.?)\s?(?P<num>{_DIGITS})\s?(?P<mult>\b(?:million|billion|thousand|lakhs?|crores?|mn|bn|k|m|b)\b|(?<=\d)[kKmMbB]\b)?",
    re.I)
_MONEY_POST = re.compile(rf"(?P<num>{_DIGITS})\s?(?P<mult>million|billion|thousand|lakhs?|crores?|mn|bn|k)?\s?(?P<cur>dollars?|euros?|pounds|rupees|USD|EUR|GBP|INR)\b", re.I)
_PERCENT = re.compile(rf"(?P<num>{_DIGITS})\s?(?:%|percent\b|per\s?cent\b|pct\b)|(?P<num2>{_NUMWORD})\s+(?:percent|per\s?cent)\b", re.I)
_DURATION = re.compile(
    rf"(?P<num>{_NUM_PAREN})[\s-]*(?:(?P<qual>business|working|calendar)\s+)?(?P<unit>day|week|month|year|hour|minute|quarter)s?\b", re.I)
_NET = re.compile(r"\bnet[\s-]?(\d{1,3})\b", re.I)
_FREQ_WORD = re.compile(r"\b(hourly|daily|weekly|monthly|quarterly|annually|yearly|biweekly|fortnightly)\b", re.I)
_FREQ_EACH = re.compile(r"\b(?:every|each)\s+(?:single\s+)?(day|week|month|quarter|year|hour)\b", re.I)
_FREQ_DAYS = {"hourly": ("hour", 1), "daily": ("day", 1), "weekly": ("day", 7), "monthly": ("day", 30), "quarterly": ("day", 91),
              "annually": ("day", 365), "yearly": ("day", 365), "biweekly": ("day", 14), "fortnightly": ("day", 14)}
_NUMBER = re.compile(rf"(?<![\w.])(?P<num>{_DIGITS})(?![\w]|\.\d)")


def extract_quantities(sentence: str) -> list[Quantity]:
    qs: list[Quantity] = []
    taken: list[tuple[int, int]] = []

    def free(a: int, b: int) -> bool:
        return not any(a < y and b > x for x, y in taken)

    def add(kind, value, unit, a, b, raw=None):
        qs.append(Quantity(kind, value, unit, raw or sentence[a:b].strip(), a, b))
        taken.append((a, b))

    for iso, a, b in parse_dates(sentence):
        add("date", iso, "", a, b)

    for m in _MONEY_PRE.finditer(sentence):
        if not free(m.start(), m.end()):
            continue
        cur = _CUR_SYM.get(m.group("cur").lower().strip(), "USD")
        v = float(m.group("num").replace(",", ""))
        mult = (m.group("mult") or "").lower()
        v *= _MULT.get(mult, 1)
        add("money", v, cur, m.start(), m.end())
    for m in _MONEY_POST.finditer(sentence):
        if not free(m.start(), m.end()):
            continue
        v = float(m.group("num").replace(",", "")) * _MULT.get((m.group("mult") or "").lower(), 1)
        add("money", v, _CUR_WORD.get(m.group("cur").lower(), "USD"), m.start(), m.end())

    for m in _PERCENT.finditer(sentence):
        if not free(m.start(), m.end()):
            continue
        v = float(m.group("num").replace(",", "")) if m.group("num") else words_to_number(m.group("num2"))
        if v is not None:
            add("percent", v, "%", m.start(), m.end())

    for m in _DURATION.finditer(sentence):
        if not free(m.start(), m.end()):
            continue
        v = _to_number(m.group("num"))
        if v is None:
            continue
        unit, factor = _DUR_UNIT[m.group("unit").lower()]
        qual = (m.group("qual") or "").lower()
        if qual in ("business", "working"):
            unit = "business " + unit
        add("duration", v * factor, unit, m.start(), m.end())
    for m in _NET.finditer(sentence):
        if free(m.start(), m.end()):
            add("duration", float(m.group(1)), "day", m.start(), m.end())
    for m in _FREQ_WORD.finditer(sentence):         # recurrence: "tested weekly" == every 7 days
        if free(m.start(), m.end()):
            unit, days = _FREQ_DAYS[m.group(1).lower()]
            add("duration", float(days), unit, m.start(), m.end())
    for m in _FREQ_EACH.finditer(sentence):         # "every day" (a number between every and the unit is handled above)
        if free(m.start(), m.end()):
            unit, factor = _DUR_UNIT[m.group(1).lower()]
            add("duration", float(factor), unit, m.start(), m.end())

    for m in _NUMBER.finditer(sentence):
        if not free(m.start(), m.end()):
            continue
        raw = m.group("num")
        before = sentence[: m.start()]
        if _SECTION_CTX.search(before[-18:]):
            continue
        if re.match(r"^\s*[.)]\s", sentence[m.end():m.end() + 3]) and m.start() <= 1:      # list enumerator "1. ..."
            continue
        digits = raw.replace(",", "")
        if re.fullmatch(r"(19|20)\d{2}", digits) and "," not in raw:                       # a bare year is context, not a value
            continue
        if len(digits.replace(".", "")) >= 9:                                              # phone / id-like
            continue
        if re.match(r"\s*(?:st|nd|rd|th)\b", sentence[m.end():m.end() + 4], re.I):          # ordinals
            continue
        if re.match(r"\s*[:/]\s*\d", sentence[m.end():m.end() + 3]) or re.search(r"\d[:/]$", before[-2:]):   # times, ratios, dates
            continue
        add("number", float(digits), "", m.start(), m.end(), raw=raw + _unit_noun(sentence[m.end():]))
    qs.sort(key=lambda q: q.start)
    return qs


_UNIT_NOUN = re.compile(r"^\s+([A-Za-z][A-Za-z\-]{1,13})(?:\s+([A-Za-z][A-Za-z\-]{1,13}))?")


def _unit_noun(rest: str) -> str:
    """The word(s) naming what a bare number counts, for display only: '142' -> '142 employees', '3' -> '3 safety officers'."""
    m = _UNIT_NOUN.match(rest)
    if not m:
        return ""
    w1, w2 = m.group(1), m.group(2)
    if w1.lower() in STOPWORDS:
        return ""
    out = " " + w1
    if w2 and not w1.lower().endswith("s") and w2.lower() not in STOPWORDS:
        out += " " + w2
    return out


def years_in(text: str) -> set[str]:
    return set(re.findall(r"\b((?:19|20)\d{2})\b", text))


_QUALIFIER_RE = re.compile(r"\b(Q[1-4]|FY\d{2,4}|H[12]|[A-Z][a-z]{2,}(?:[A-Z][a-z]+)*)\b")
_NOT_QUALIFIERS = {"the", "this", "that", "these", "those", "any", "all", "each", "every", "such", "with", "for", "and", "per", "our", "its",
                   "agreement", "contract", "company", "party", "parties", "client", "vendor", "supplier", "customer", "section", "clause",
                   "policy", "document", "report", "notice", "payment", "terms", "net", "total", "annual", "monthly", "employees",
                   "employee", "staff", "headcount", "invoice", "invoices", "amendment", "schedule", "appendix", "article", "board",
                   "management", "minutes", "meeting", "incident", "security", "password", "passwords", "access", "data", "system"}


def qualifiers(sentence: str, quantity_spans: list[tuple[int, int]]) -> frozenset:
    """Entities / periods that scope a statement (names, quarters, fiscal years, bare years)."""
    out = set()
    for m in _QUALIFIER_RE.finditer(sentence):
        a, b = m.span()
        if any(a < y and b > x for x, y in quantity_spans):
            continue
        w = m.group(1)
        if re.match(r"\s*:", sentence[b:b + 3]):                       # "Target: 95%" - a field label, not an entity
            continue
        if a == 0 or re.search(r"[.!?:]\s*$", sentence[:a]):          # sentence-initial capital
            if not re.fullmatch(r"Q[1-4]|FY\d{2,4}|H[12]", w):
                continue
        lw = w.lower()
        if lw in STOPWORDS or lw in _NOT_QUALIFIERS:
            continue
        out.add(lw)
    for m in re.finditer(r"\b((?:19|20)\d{2})\b", sentence):          # a year inside a date VALUE is the value, not its scope
        if not any(m.start() < y and m.end() > x for x, y in quantity_spans):
            out.add(m.group(1))
    return frozenset(out)


_FILLER = {"approximately", "approx", "stated", "agreed", "currently", "shall", "must", "set", "equal", "equals"}

# Synonym groups collapsed to one concept so "headcount 128" and "142 employees" talk about the same subject.
_CANON_GROUPS = {
    "employe": ["employee", "employ", "employed", "employs", "staff", "headcount", "workforce", "personnel", "worker", "people"],
    "due": ["payable", "due", "owed", "overdue"],
    "rotate": ["rotate", "rotation", "expire", "expiry", "renew", "reset", "chang"],
    "start": ["start", "begin", "commence", "began", "begun", "started", "commenced"],
    "terminat": ["terminat", "cancel", "cancell"],
    "price": ["price", "cost", "worth"],
}
CANON = {stem(w): k for k, ws in _CANON_GROUPS.items() for w in ws}
CANON.update({w: k for k, ws in _CANON_GROUPS.items() for w in ws})


def canon(t: str) -> str:
    st = stem(t)
    return CANON.get(st, CANON.get(t, st))


def subject_stems(sentence: str, quantities: list[Quantity]) -> frozenset:
    chars = list(sentence)
    for q in quantities:
        for i in range(q.start, min(q.end, len(chars))):
            chars[i] = " "
    out = set()
    for t in tokenize("".join(chars)):
        if t in STOPWORDS or t in _FILLER:
            continue
        if len(t) == 1 or t.isdigit():
            continue
        out.add(canon(t))
    return frozenset(out)


_STATIVE = re.compile(r"\b(?:has|have|had|employs?|employed|is|are|was|were|totals?|totalled|stands?\s+at|comprises?|numbers?|counts?|"
                      r"represents?|equals?|amounts?\s+to|reached|reports?|increased\s+to|decreased\s+to|capped\s+at)\b", re.I)
_SCOPE_DATE = re.compile(r"(?:as\s+of|as\s+at|year\s+ended|period\s+ended|ended|during|at\s+the\s+end\s+of|from|through|since|until|"
                         r"for\s+(?:the\s+)?(?:year|quarter|month|period|fy)|in|valid\s+(?:until|through))\s*$", re.I)
_WORD = re.compile(r"[A-Za-z][A-Za-z\-']*")


def annotate_quantities(sentence: str, quantities: list[Quantity]) -> None:
    """Attach local context (clause-level stems), the anchor noun, stativity and date-scope to every quantity."""
    toks = []
    for m in _WORD.finditer(sentence):
        w = m.group(0).lower().replace("'", "")
        if w in STOPWORDS or w in _FILLER or len(w) < 2:
            continue
        if any(q.start <= m.start() < q.end for q in quantities):
            continue
        toks.append((canon(w), m.start(), m.end()))
    for q in quantities:
        left = [t for t in toks if t[2] <= q.start and not re.search(r"[;|]|\.\s", sentence[t[2]:q.start])]
        right = [t for t in toks if t[1] >= q.end and not re.search(r"[;|]|\.\s", sentence[q.end:t[1]])]
        left, right = left[-5:], right[:3]
        q.ctx = frozenset(t[0] for t in left + right)
        near_right = [t for t in right if t[1] - q.end <= 14]
        near_left = [t for t in left if q.start - t[2] <= 14]
        q.anchor = near_right[0][0] if near_right else (near_left[-1][0] if near_left else "")
        before = sentence[max(0, q.start - 45):q.start]
        before = re.split(r"[;|]", before)[-1]
        q.stative = bool(_STATIVE.search(before))
        if q.kind == "date":
            q.scope_date = bool(_SCOPE_DATE.search(sentence[max(0, q.start - 24):q.start]))


def build_fact(fid: str, chunk, sent_start: int, sent_end: int, sentence: str, heading: str, doc_title: str | None) -> Fact | None:
    quantities = extract_quantities(sentence)
    annotate_quantities(sentence, quantities)
    neg = negation_count(sentence)
    stems = subject_stems(sentence, quantities)
    if len(stems) < 2:
        return None
    heading_stems = frozenset(canon(t) for t in tokenize(heading) if t not in STOPWORDS and len(t) > 1) if heading else frozenset()
    spans = [(q.start, q.end) for q in quantities]
    return Fact(
        id=fid, doc_id=chunk.doc_id, doc_name=chunk.doc_name, chunk_id=chunk.id, page=chunk.page, paged=chunk.paged,
        section=heading, sentence=sentence, start=chunk.start + sent_start, end=chunk.start + sent_end, quantities=quantities,
        stems=stems, heading_stems=heading_stems, qualifiers=qualifiers(sentence, spans), negations=neg,
        ocr_conf=chunk.ocr_conf, doc_date=chunk.doc_date, doc_title=doc_title,
        tabular=bool(" | " in sentence or (sentence.count(";") >= 1 and sentence.count(": ") >= 2)),
    )
