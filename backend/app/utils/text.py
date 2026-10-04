"""Tokenisation, light stemming, sentence splitting and other text helpers (no external NLP deps)."""
from __future__ import annotations

import re
from typing import Iterable

STOPWORDS = frozenset(
    """a about above after again all also am an and any are as at be because been before being below between both but by
    can could did do does doing down during each either else few for from further had has have having he her here hers him
    his how i if in into is it its itself just me more most my no nor not of off on once only or other our out over own same
    shall she should so some such than that the their them then there these they this those through to too under until up
    upon very was we were what when where which while who whom whose why will with within without would you your yours
    per via etc eg ie may might must one two three however thus therefore hereby herein thereof whereas pursuant
    approximately approx around currently also still yet already""".split()
)

# Words that are retained in questions but carry no topical content.
QUESTION_FILLER = frozenset(
    """tell show give list explain describe please find say state according document documents file files source sources
    mention mentioned mentions stated says often long many much""".split()
)

_NEGATIONS = re.compile(r"\b(?:not|no|never|neither|nor|cannot|without|none|nothing|isn't|aren't|wasn't|weren't|won't|"
                        r"doesn't|don't|didn't|hasn't|haven't|hadn't|can't|couldn't|shouldn't|wouldn't|unable|failed to|fails to)\b|n't\b",
                        re.IGNORECASE)

_WORD_RE = re.compile(r"[a-z0-9]+(?:\.\d+)?")


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def stem(word: str) -> str:
    """Very light, deterministic suffix stripper (good enough for matching 'terminate/terminated/termination')."""
    w = word
    if len(w) <= 3 or w.isdigit() or any(c.isdigit() for c in w):
        return w
    if w.endswith("sses"):
        w = w[:-2]
    elif w.endswith("ies") and len(w) > 4:
        w = w[:-3] + "y"
    elif w.endswith(("xes", "ches", "shes", "zes")):
        w = w[:-2]
    elif w.endswith("s") and not w.endswith(("ss", "us", "is")):
        w = w[:-1]
    for _ in range(2):
        for suf, rep in (("ational", "at"), ("ations", "at"), ("ation", "at"), ("ments", ""), ("ment", ""), ("ingly", ""), ("edly", ""),
                         ("ions", ""), ("ion", ""), ("ings", ""), ("ing", ""), ("ers", ""), ("er", ""), ("ed", ""), ("ly", ""), ("ity", ""),
                         ("ive", ""), ("ous", ""), ("al", "")):
            if w.endswith(suf) and len(w) - len(suf) >= 3:
                w = w[: -len(suf)] + rep
                break
    if w.endswith("e") and len(w) > 4:
        w = w[:-1]
    if len(w) > 3 and w[-1] == w[-2] and w[-1] not in "ls":
        w = w[:-1]
    return w


def tokenize(text: str) -> list[str]:
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text.lower())
    text = text.replace("'", "").replace("’", "")
    return _WORD_RE.findall(text)


def content_stems(text: str, extra_stop: Iterable[str] = ()) -> list[str]:
    extra = set(extra_stop)
    out = []
    for t in tokenize(text):
        if t in STOPWORDS or t in extra:
            continue
        if len(t) == 1 and not t.isdigit():
            continue
        out.append(stem(t))
    return out


def question_stems(question: str) -> list[str]:
    return content_stems(question, QUESTION_FILLER)


def negation_count(text: str) -> int:
    return len(_NEGATIONS.findall(text))


# ---------------------------------------------------------------------------------------------
# Sentence splitting (returns spans so callers can map back to character offsets)
# ---------------------------------------------------------------------------------------------
_ABBREV = {"mr", "mrs", "ms", "dr", "prof", "inc", "ltd", "co", "corp", "no", "nos", "vs", "etc", "approx", "fig", "sec",
           "st", "jr", "sr", "e.g", "i.e", "u.s", "cf", "al", "dept", "est", "vol", "pp", "ca", "jan", "feb", "mar", "apr",
           "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec", "rs", "ref", "art", "para", "cl"}

_SPLIT_RE = re.compile(r"(?<=[.!?])[\"')\]]*(?=\s+(?:[A-Z0-9\"'(\[•\-–]))")


def split_sentences(text: str) -> list[tuple[int, int]]:
    """Return (start, end) spans of sentences. Newlines always end a sentence (lists, table rows, headings)."""
    spans: list[tuple[int, int]] = []
    pos = 0
    for line in text.split("\n"):
        line_start = pos
        pos += len(line) + 1
        if not line.strip():
            continue
        cuts = [0]
        for m in _SPLIT_RE.finditer(line):
            end = m.end()
            head = line[cuts[-1]:end].rstrip(" \"')]")
            last_tok = re.findall(r"[A-Za-z.]+$", head)
            lt = last_tok[0].lower().rstrip(".") if last_tok else ""
            if lt in _ABBREV or (len(lt) == 1 and lt.isalpha()):
                continue
            # decimal numbers like "3. 5" are not boundaries
            if re.search(r"\d\.$", head) and re.match(r"\s*\d", line[end:end + 3]):
                continue
            cuts.append(end)
        cuts.append(len(line))
        for a, b in zip(cuts, cuts[1:]):
            seg = line[a:b]
            lead = len(seg) - len(seg.lstrip())
            seg_s = seg.strip()
            if seg_s:
                spans.append((line_start + a + lead, line_start + a + lead + len(seg_s)))
    return spans


def sentences(text: str) -> list[str]:
    return [text[a:b] for a, b in split_sentences(text)]


def clip(text: str, n: int = 220) -> str:
    text = normalize_ws(text)
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def find_span(haystack: str, needle: str) -> tuple[int, int] | None:
    """Find `needle` in `haystack` ignoring whitespace differences; returns span in haystack."""
    if not needle:
        return None
    i = haystack.find(needle)
    if i >= 0:
        return i, i + len(needle)
    parts = [re.escape(p) for p in needle.split()]
    if not parts:
        return None
    m = re.search(r"\s+".join(parts), haystack, flags=re.IGNORECASE)
    return (m.start(), m.end()) if m else None


def contains_quote(passage: str, quote: str) -> bool:
    """True if `quote` appears verbatim (whitespace/case/quote-style insensitive) in `passage`."""
    def norm(s: str) -> str:
        s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
        s = s.replace("–", "-").replace("—", "-")
        return normalize_ws(s).lower().strip(" .…\"'")
    q = norm(quote)
    if len(q) < 8:
        return False
    return q in norm(passage)


# ---- text that tries to instruct an AI -------------------------------------------------------------------------------
# High-precision patterns only (an ordinary contract never says these). This is one layer: document text is also always sent to the model as
# quoted data, quotes are verified verbatim, and the model cannot change a verified conflict. Detection lets the product go further - such a
# sentence is never used as evidence, is hidden from the model, and is reported to the user as a security finding.
_INJECTION = re.compile(
    r"\b(?:ignore|disregard|forget|override)\b[^.\n]{0,40}\b(?:previous|prior|above|earlier|all)\b[^.\n]{0,30}\b(?:instructions?|prompts?|rules|guidelines|context)\b"
    r"|\b(?:notes?|messages?|instructions?|notices?)\s+(?:to|for)\s+(?:the\s+)?(?:ai|a\.i\.|llm|language models?|assistants?|chat ?bots?|models?)\b"
    r"|\b(?:reveal|print|show|repeat|output|leak)\b[^.\n]{0,30}\b(?:system|developer)\s+prompt\b|\byour (?:system|developer) prompt\b"
    r"|\bas an ai (?:language )?model\b"
    r"|\byou are (?:now )?(?:an?|the) (?:ai|llm|chat ?bot|language model)\b",
    re.IGNORECASE,
)
INJECTION_PLACEHOLDER = "[sentence addressed to AI assistants removed]"


def looks_like_injection(sentence: str) -> bool:
    return bool(_INJECTION.search(sentence))


def find_injections(text: str) -> list[tuple[int, int]]:
    """Spans of sentences that try to give instructions to an AI assistant."""
    return [(a, b) for a, b in split_sentences(text) if _INJECTION.search(text[a:b])]


def redact_injections(text: str) -> str:
    """The text with injection sentences replaced by a neutral placeholder (used only for what is sent to the language model)."""
    spans = find_injections(text)
    for a, b in reversed(spans):
        text = text[:a] + INJECTION_PLACEHOLDER + text[b:]
    return text
