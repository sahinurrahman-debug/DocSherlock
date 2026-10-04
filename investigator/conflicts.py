"""Cross-document conflict detection.

Two statements conflict when they are about the *same subject* but assert *incompatible values*.
Pipeline (all deterministic, no LLM required):

1. Candidate generation via an inverted index over subject stems.
2. Subject similarity - IDF-weighted overlap, with section headings as weaker context.
3. Scope guards - statements scoped to different entities / periods are NOT conflicts
   ("Q1 revenue $5M" vs "Q2 revenue $7M", "Alice's salary" vs "Bob's salary").
4. Value comparison by kind (money / percent / duration / date / number) with unit-aware tolerances.
5. Assertion polarity (negation / antonyms) for statements without numbers.
6. Explanations: which source is newer, supersession cues ("amended", "supersedes"), time-scoped values.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict

from .facts import canon, dates_compatible, date_sort_key
from .models import Fact, Quantity
from .textutil import STOPWORDS, clip, tokenize

_GENERIC_INITIALS = {"section", "article", "clause", "payment", "invoice", "invoices", "notice", "termination", "passwords", "password"}
MIN_SHARED = 2
MIN_OVERLAP = 0.55

_SUPERSEDE = re.compile(r"\b(supersed\w*|replac(?:e|es|ed|ing|ement)|amend(?:s|ed|ment|ments)?|revis(?:e|es|ed|ion)|updat(?:e|es|ed)|"
                        r"in lieu of|no longer|hereby modif\w*|restat\w*|overrid\w*|effective (?:from|as of|immediately)|changed (?:to|from)|"
                        r"instead of|obsolete|deprecated)\b", re.I)
_DRAFT = re.compile(r"\b(draft|preliminary|proposed|tentative|superseded|obsolete|old|outdated)\b", re.I)
_FINAL = re.compile(r"\b(final|signed|executed|approved|amend\w*|addendum|revised|v\d+|rev\d*)\b", re.I)

_ANTONYMS = [
    ("approved", "rejected"), ("approved", "denied"), ("approved", "declined"), ("passed", "failed"), ("compliant", "non-compliant"),
    ("increase", "decrease"), ("increased", "decreased"), ("increased", "declined"), ("higher", "lower"), ("allowed", "prohibited"),
    ("permitted", "prohibited"), ("permitted", "forbidden"), ("required", "optional"), ("mandatory", "optional"), ("active", "inactive"),
    ("open", "closed"), ("enabled", "disabled"), ("profit", "loss"), ("accepted", "rejected"), ("granted", "denied"),
    ("confirmed", "denied"), ("completed", "pending"), ("completed", "cancelled"), ("resolved", "unresolved"), ("valid", "invalid"),
    ("secure", "vulnerable"), ("encrypted", "unencrypted"), ("yes", "no"), ("true", "false"), ("included", "excluded"),
    ("breach", "no breach"), ("signed", "unsigned"), ("exceeded", "met"), ("satisfied", "unsatisfied"), ("on track", "delayed"),
]


@dataclass
class FactRef:
    fact_id: str
    doc_id: str
    doc_name: str
    page: int | None
    section: str
    sentence: str
    start: int
    end: int
    chunk_id: str
    value: str                  # human readable value(s) in conflict
    doc_date: str | None
    ocr_conf: float | None

    def to_dict(self):
        return asdict(self)


@dataclass
class Conflict:
    id: str
    kind: str                   # value | date | assertion
    topic: list[str]
    a: FactRef
    b: FactRef
    score: float
    severity: str               # high | medium | low
    explanation: str
    hints: list[str] = field(default_factory=list)
    same_document: bool = False
    time_scoped: bool = False
    value_kind: str = ""

    def to_dict(self):
        d = asdict(self)
        return d


def _fmt(q: Quantity) -> str:
    return q.raw


def _values_equal(a: Quantity, b: Quantity) -> bool:
    if a.kind != b.kind:
        return False
    if a.kind == "date":
        return dates_compatible(a.value, b.value)
    if a.kind == "money":
        return a.unit == b.unit and math.isclose(a.value, b.value, rel_tol=0.01)
    if a.kind == "duration":
        return a.unit == b.unit and math.isclose(a.value, b.value, rel_tol=0.03)
    if a.kind == "percent":
        return abs(a.value - b.value) < 0.05
    return math.isclose(a.value, b.value, rel_tol=0.005)


def _comparable(a: Quantity, b: Quantity) -> bool:
    if a.kind != b.kind:
        return False
    if a.kind in ("money", "duration"):
        return a.unit == b.unit
    return True


class ConflictEngine:
    def __init__(self, facts: list[Fact], idf: dict[str, float] | None = None):
        self.facts = facts
        self.idf = idf or self._idf(facts)
        # words seen in lower case somewhere in the corpus are common words; a capitalised sentence-initial word
        # that is never seen in lower case is a proper noun ("Alice earns ..." vs "Bob earns ...").
        self._lower = {w for f in facts for w in re.findall(r"(?<![A-Za-z])[a-z]{3,}(?![A-Za-z])", f.sentence)}
        self._initial_cache: dict[str, str | None] = {}

    @staticmethod
    def _idf(facts: list[Fact]) -> dict[str, float]:
        df: Counter = Counter()
        for f in facts:
            df.update(f.stems)
        n = max(len(facts), 1)
        return {t: math.log(1 + n / (1 + c)) for t, c in df.items()}

    def w(self, t: str) -> float:
        return self.idf.get(t, 1.0)

    # -- similarity ---------------------------------------------------------------------------
    def subject_overlap(self, a: Fact, b: Fact) -> tuple[float, int, list[str]]:
        sa, sb = a.stems, b.stems
        shared_sentence = sa & sb
        if not shared_sentence:
            return 0.0, 0, []
        ha, hb = a.stems | a.heading_stems, b.stems | b.heading_stems
        shared = ha & hb
        wa = sum(self.w(t) for t in ha)
        wb = sum(self.w(t) for t in hb)
        ws = sum(self.w(t) for t in shared)
        denom = min(wa, wb) or 1.0
        topic = sorted(shared, key=lambda t: -self.w(t))[:5]
        return ws / denom, len(shared), topic

    def _initial_name(self, f: Fact) -> str | None:
        if f.id in self._initial_cache:
            return self._initial_cache[f.id]
        m = re.match(r"^\W*([A-Z][a-z]{2,})(?:['’]s)?(?![A-Za-z])", f.sentence)
        name = None
        if m and not re.match(r"\s*[:=|]", f.sentence[m.end():m.end() + 3]):      # "Metric: ..." is a table label, not an entity
            w = m.group(1).lower()
            if w not in self._lower and w not in STOPWORDS and w not in _GENERIC_INITIALS:
                name = w
        self._initial_cache[f.id] = name
        return name

    def qualifier_clash(self, a: Fact, b: Fact) -> bool:
        qa, qb = set(a.qualifiers), set(b.qualifiers)
        na, nb = self._initial_name(a), self._initial_name(b)
        if na and nb and na != nb:
            return True                      # "Alice earns ..." vs "Bob earns ...": different subjects
        return bool(qa - qb) and bool(qb - qa)

    # -- main scan ----------------------------------------------------------------------------
    def scan(self) -> list[Conflict]:
        inv: dict[str, list[int]] = defaultdict(list)
        for i, f in enumerate(self.facts):
            for t in f.stems | {t for q in f.quantities for t in q.ctx}:
                inv[t].append(i)
        n = len(self.facts)
        common = {t for t, ids in inv.items() if len(ids) > max(40, 0.35 * n)}
        seen: set[tuple[int, int]] = set()
        out: dict[tuple[str, str, str], Conflict] = {}
        for i, f in enumerate(self.facts):
            counts: Counter = Counter()
            for t in f.stems | {t for q in f.quantities for t in q.ctx}:
                if t in common:
                    continue
                for j in inv[t]:
                    if j > i:
                        counts[j] += 1
            for j in counts:
                if (i, j) in seen:
                    continue
                seen.add((i, j))
                for conf in self.compare(f, self.facts[j]):
                    key = (conf.a.fact_id, conf.b.fact_id, conf.value_kind or conf.kind)
                    if key not in out or out[key].score < conf.score:
                        out[key] = conf
        res = sorted(out.values(), key=lambda c: (-{"high": 2, "medium": 1, "low": 0}[c.severity], -c.score))
        return self._dedupe(res)

    @staticmethod
    def _dedupe(conflicts: list[Conflict]) -> list[Conflict]:
        """Keep the strongest conflict per (sentence pair, kind)."""
        best: dict[tuple, Conflict] = {}
        for c in conflicts:
            ka = (c.a.doc_id, c.a.start, c.a.end)
            kb = (c.b.doc_id, c.b.start, c.b.end)
            key = (tuple(sorted([ka, kb])), c.value_kind or c.kind)
            if key not in best:
                best[key] = c
        return list(best.values())

    def compare(self, a: Fact, b: Fact) -> list[Conflict]:
        if a.sentence.strip().lower() == b.sentence.strip().lower():
            return []
        same_doc = a.doc_id == b.doc_id
        if same_doc and (a.tabular or b.tabular):
            return []                               # rows of one table naturally carry different values
        if self.qualifier_clash(a, b):
            return []
        sim, n_shared, topic = self.subject_overlap(a, b)
        out = self._value_conflicts(a, b, sim, n_shared, topic, same_doc)
        if out:
            return out
        if n_shared < MIN_SHARED or sim < 0.5:
            return []
        conf = self._assertion_conflict(a, b, sim, topic, same_doc)
        return [conf] if conf else []

    # local (clause-level) subject match between two specific values
    def _local_match(self, x: Quantity, y: Quantity, a: Fact, b: Fact):
        cx, cy = x.ctx | a.heading_stems, y.ctx | b.heading_stems
        shared = cx & cy
        if len(shared) >= 2 and (x.ctx & y.ctx):
            wx, wy = sum(self.w(t) for t in cx), sum(self.w(t) for t in cy)
            coef = sum(self.w(t) for t in shared) / (min(wx, wy) or 1.0)
            if coef >= 0.6 or (len(shared) >= 3 and coef >= 0.4) or (x.kind == "money" and coef >= 0.4):
                return max(coef, 0.55), sorted(shared, key=lambda t: -self.w(t))[:5]
        # same head noun of a standing quantity: "has 142 employees" vs "has 128 employees"
        if x.kind == "number" and x.anchor and x.anchor == y.anchor and x.stative and y.stative and self.w(x.anchor) > 0.5:
            return 0.7, [x.anchor]
        return None

    def _value_conflicts(self, a: Fact, b: Fact, sim: float, n_shared: int, topic: list[str], same_doc: bool) -> list[Conflict]:
        out: list[Conflict] = []
        global_ok_base = n_shared >= MIN_SHARED and sim >= MIN_OVERLAP
        for kind in ("money", "percent", "duration", "date", "number"):
            qa = [q for q in a.quantities if q.kind == kind]
            qb = [q for q in b.quantities if q.kind == kind]
            if kind == "date":                      # only event dates are comparable; as-of / period dates scope a statement
                qa, qb = [q for q in qa if not q.scope_date], [q for q in qb if not q.scope_date]
            if kind in ("money", "duration"):
                units = {q.unit for q in qa} & {q.unit for q in qb}
                qa, qb = [q for q in qa if q.unit in units], [q for q in qb if q.unit in units]
            if not qa or not qb:
                continue
            if any(_values_equal(x, y) for x in qa for y in qb):
                continue                            # at least one shared value => compatible
            # money / percentages are distinctive enough that three shared subject words at 45% overlap are convincing
            global_ok = global_ok_base or (kind in ("money", "percent") and n_shared >= 3 and sim >= 0.45)
            local = []
            for x in qa:
                for y in qb:
                    m = self._local_match(x, y, a, b)
                    if m:
                        local.append(m)
            if not (global_ok or local):
                continue
            score_sim, why = sim, topic
            if local:
                best = max(local, key=lambda t: t[0])
                if not global_ok or best[0] > sim:
                    score_sim, why = best[0], best[1]
            # time scoping: both statements anchored to different periods => not a contradiction
            time_scoped = False
            if kind != "date":
                sa = [q for q in a.quantities if q.kind == "date" and q.scope_date]
                sb = [q for q in b.quantities if q.kind == "date" and q.scope_date]
                if sa and sb and not any(dates_compatible(x.value, y.value) for x in sa for y in sb):
                    continue
                time_scoped = bool(sa) != bool(sb)
            if kind == "number" and min(len(a.stems), len(b.stems)) < 3 and score_sim < 0.8 and not local:
                continue
            va = ", ".join(q.raw for q in qa[:3])
            vb = ", ".join(q.raw for q in qb[:3])
            label = {"money": "amounts", "percent": "percentages", "duration": "durations/periods", "date": "dates", "number": "figures"}[kind]
            out.append(self._make("date" if kind == "date" else "value", kind, a, b, va, vb, score_sim, why, same_doc, time_scoped,
                                  f"The sources give different {label} for the same subject: {va} vs {vb}."))
        return out

    def _assertion_conflict(self, a: Fact, b: Fact, sim: float, topic: list[str], same_doc: bool):
        if len(a.stems & b.stems) < 3:
            return None
        if {q.kind for q in a.quantities} & {q.kind for q in b.quantities}:
            return None
        la, lb = a.sentence.lower(), b.sentence.lower()
        reason = None
        for x, y in _ANTONYMS:
            ax, ay = re.search(rf"\b{re.escape(x)}\b", la), re.search(rf"\b{re.escape(y)}\b", la)
            bx, by = re.search(rf"\b{re.escape(x)}\b", lb), re.search(rf"\b{re.escape(y)}\b", lb)
            if ((ax and by) or (ay and bx)) and not (ax and ay) and not (bx and by):
                reason = f"opposite assertions ('{x}' vs '{y}')"
                break
        if reason is None and (a.negations % 2) != (b.negations % 2) and sim >= 0.7:
            jacc = len(a.stems & b.stems) / len(a.stems | b.stems)
            if jacc >= 0.6:
                reason = "one source affirms what the other negates"
        if reason is None:
            return None
        return self._make("assertion", "assertion", a, b, clip(a.sentence, 80), clip(b.sentence, 80), sim * 0.9, topic, same_doc, False,
                          f"The sources make {reason} about the same subject.")

    # -- assembly -----------------------------------------------------------------------------
    def _make(self, kind, value_kind, a: Fact, b: Fact, va: str, vb: str, sim: float, topic, same_doc, time_scoped, explanation) -> Conflict:
        # order: older first when dates are known, else by doc name
        ka, kb = date_sort_key(a.doc_date), date_sort_key(b.doc_date)
        if ka and kb and ka > kb:
            a, b, va, vb = b, a, vb, va
        elif not (ka and kb) and (a.doc_name, a.start) > (b.doc_name, b.start):
            a, b, va, vb = b, a, vb, va
        surface: dict[str, str] = {}
        for t in tokenize(f"{a.sentence} {b.sentence} {a.section} {b.section}"):
            surface.setdefault(canon(t), t)
        topic = [surface.get(t, t) for t in topic]          # show readable words, not stems ("employe" -> "employees")
        hints = self._hints(a, b, same_doc, time_scoped)
        score = round(min(1.0, sim) * (0.85 if same_doc else 1.0) * (0.85 if time_scoped else 1.0), 3)
        if same_doc:
            severity = "medium" if score >= 0.6 else "low"
        elif score >= 0.75 and not time_scoped and n_good_topic(topic):
            severity = "high"
        else:
            severity = "medium" if score >= 0.55 else "low"
        cid = hashlib.sha1(f"{a.id}|{b.id}|{value_kind}".encode()).hexdigest()[:10]
        return Conflict(
            id=cid, kind=kind, topic=topic, a=_ref(a, va), b=_ref(b, vb), score=score, severity=severity,
            explanation=explanation, hints=hints, same_document=same_doc, time_scoped=time_scoped, value_kind=value_kind,
        )

    @staticmethod
    def _hints(a: Fact, b: Fact, same_doc: bool, time_scoped: bool) -> list[str]:
        hints: list[str] = []
        if same_doc:
            hints.append("Both statements are in the same document - this may be an internal inconsistency or a typo.")
        da, db = a.doc_date, b.doc_date
        if da and db and da != db and not same_doc:
            newer, older = (b, a) if date_sort_key(db) > date_sort_key(da) else (a, b)
            hints.append(f"'{newer.doc_name}' is dated {newer.doc_date}, newer than '{older.doc_name}' ({older.doc_date}); "
                         f"the values may reflect a change over time rather than an error.")
        for f in (a, b):
            m = _SUPERSEDE.search(f.sentence)
            if m:
                hints.append(f"'{f.doc_name}' uses change/supersession language (\"{m.group(0)}\"), suggesting it modifies an earlier position.")
        for f in (a, b):
            if _DRAFT.search(f.doc_name) or (f.doc_title and _DRAFT.search(f.doc_title)):
                hints.append(f"'{f.doc_name}' appears to be a draft/outdated version based on its name.")
        ka, kb = authority(a), authority(b)
        if ka != kb and not same_doc:
            hi, lo = (a, b) if ka > kb else (b, a)
            hints.append(f"'{hi.doc_name}' looks like a formal document while '{lo.doc_name}' looks informal (email/notes), so the formal one is the more authoritative source.")
        if time_scoped:
            hints.append("At least one statement is tied to a specific period, so the values may describe different points in time.")
        if (a.ocr_conf is not None and a.ocr_conf < 0.85) or (b.ocr_conf is not None and b.ocr_conf < 0.85):
            hints.append("One source was read via OCR with modest confidence - verify the figure on the original image.")
        return hints


_FORMAL = re.compile(r"agreement|contract|amendment|addendum|policy|handbook|regulation|report|minutes|statute|spec|standard|terms", re.I)
_INFORMAL = re.compile(r"email|e-mail|\.eml|thread|chat|notes?|memo|draft|message|slack", re.I)


def authority(f: Fact) -> int:
    if _INFORMAL.search(f.doc_name):
        return 0
    return 1 if _FORMAL.search(f.doc_name) else 0


def n_good_topic(topic: list[str]) -> bool:
    return len(topic) >= 2


def _ref(f: Fact, value: str) -> FactRef:
    return FactRef(fact_id=f.id, doc_id=f.doc_id, doc_name=f.doc_name, page=f.page if f.paged else None, section=f.section,
                   sentence=f.sentence, start=f.start, end=f.end, chunk_id=f.chunk_id, value=value, doc_date=f.doc_date,
                   ocr_conf=f.ocr_conf)


# ---------------------------------------------------------------------------------------------
# Clusters: pairwise conflicts about the same subject are merged into one "disputed point" with N positions
# (contract says Net 30, amendment says Net 45, an email says Net 30 again => 2 positions, 3 sources).
# ---------------------------------------------------------------------------------------------
def _qkey(ref: FactRef, value_kind: str, kind: str) -> tuple:
    from .facts import extract_quantities
    from .textutil import normalize_ws
    if kind == "assertion":
        return ("s", normalize_ws(ref.sentence).lower())
    qs = extract_quantities(ref.value)
    pick = [q for q in qs if q.kind == value_kind] or qs
    if pick:
        q = pick[0]
        return (q.kind, q.value if isinstance(q.value, str) else round(float(q.value), 2), q.unit)
    return ("raw", ref.value.lower())


_SEV = {"high": 2, "medium": 1, "low": 0}
_LABEL = {"money": "amounts", "percent": "percentages", "duration": "durations/periods", "date": "dates", "number": "figures", "assertion": "statements"}


def cluster_conflicts(conflicts: list[Conflict]) -> list[dict]:
    parent: dict[tuple, tuple] = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def node(c: Conflict, ref: FactRef):
        return (c.value_kind or c.kind, ref.doc_id, ref.start, ref.end)

    for c in conflicts:
        parent[find(node(c, c.a))] = find(node(c, c.b))
    comps: dict[tuple, list[Conflict]] = defaultdict(list)
    for c in conflicts:
        comps[find(node(c, c.a))].append(c)

    out = []
    for members in comps.values():
        refs: dict[tuple, FactRef] = {}
        for c in members:
            for ref in (c.a, c.b):
                refs.setdefault(node(c, ref), ref)
        vk = members[0].value_kind or members[0].kind
        groups: dict[tuple, list[FactRef]] = defaultdict(list)
        for n, ref in refs.items():
            groups[_qkey(ref, vk, members[0].kind)].append(ref)
        positions = []
        for key, rs in groups.items():
            rs.sort(key=lambda r: (date_sort_key(r.doc_date), r.doc_name))
            positions.append({"value": rs[0].value, "sources": [r.to_dict() for r in rs]})
        positions.sort(key=lambda p: (min(date_sort_key(s["doc_date"]) or "9999" for s in p["sources"]), p["value"]))
        if len(positions) < 2:
            continue
        best = max(members, key=lambda c: c.score)
        hints: list[str] = []
        for c in members:
            for h in c.hints:
                if h not in hints:
                    hints.append(h)
        same_doc = all(c.same_document for c in members)
        time_scoped = any(c.time_scoped for c in members)
        vals = " vs ".join(f"\"{p['value']}\"" for p in positions[:4]) if members[0].kind != "assertion" else "opposing statements"
        sev = max((c.severity for c in members), key=lambda s: _SEV[s])
        cid = hashlib.sha1("|".join(sorted(str(n) for n in refs)).encode()).hexdigest()[:10]
        out.append({
            "id": cid, "kind": members[0].kind, "value_kind": vk, "topic": best.topic, "severity": sev, "score": best.score,
            "explanation": f"The sources give {len(positions)} different {_LABEL.get(vk, 'values')} for the same subject: {vals}.",
            "hints": hints, "same_document": same_doc, "time_scoped": time_scoped, "positions": positions,
            "n_sources": len(refs),
            "resolution": resolution_text(positions, same_doc, time_scoped),
        })
    out.sort(key=lambda c: (-_SEV[c["severity"]], -c["score"]))
    return out


_INFORMAL_NAME = re.compile(r"email|e-mail|\.eml|thread|chat|notes?|memo|message|slack|draft", re.I)
_AMEND_NAME = re.compile(r"amend|addendum|revis|supersed|update|v\d|rev\d", re.I)


def resolution_text(positions: list[dict], same_doc: bool, time_scoped: bool) -> str:
    """Explain what *might* reconcile the positions, clearly separated from what the documents actually state."""
    if same_doc:
        return "All statements are in one document, so this is more likely an internal inconsistency or typo than a revision."

    def info(p):
        srcs = p["sources"]
        formal = [s for s in srcs if not _INFORMAL_NAME.search(s["doc_name"])]
        dated = [date_sort_key(s["doc_date"]) for s in srcs if s["doc_date"]]
        fdated = [date_sort_key(s["doc_date"]) for s in formal if s["doc_date"]]
        sup = any(_SUPERSEDE.search(s["sentence"]) or _AMEND_NAME.search(s["doc_name"]) for s in srcs)
        return {"p": p, "newest": max(dated) if dated else "", "fnewest": max(fdated) if fdated else "", "formal": bool(formal), "sup": sup,
                "newest_src": max(srcs, key=lambda s: date_sort_key(s["doc_date"]))}

    infos = [info(p) for p in positions]
    # a position that carries amendment language and post-dates every formal source of the others
    for me in infos:
        others = [o for o in infos if o is not me]
        ref_dates = [o["fnewest"] or o["newest"] for o in others]
        if me["sup"] and me["fnewest"] and all(me["fnewest"] > d for d in ref_dates if d) and all(d for d in ref_dates):
            src = max([s for s in me["p"]["sources"] if s["doc_date"]], key=lambda s: date_sort_key(s["doc_date"]))
            txt = (f"\"{me['p']['value']}\" is the most likely current position: **{src['doc_name']}** (dated {src['doc_date']}) uses amendment/supersession wording "
                   f"and post-dates the other formal source(s). No document explicitly states which value prevails, so confirm before relying on it.")
            later = [(o, s) for o in others for s in o["p"]["sources"] if s["doc_date"] and date_sort_key(s["doc_date"]) > me["fnewest"]]
            if later:
                o, s = later[0]
                txt += (f" Note: **{s['doc_name']}** ({s['doc_date']}) still says \"{o['p']['value']}\"; informal messages don't override a formal amendment, "
                        f"but it suggests the change may not have been applied in practice.")
            return txt
    dated_all = [i for i in infos if i["newest"]]
    if len(dated_all) == len(infos):
        order = sorted(infos, key=lambda i: i["newest"], reverse=True)
        if order[0]["newest"] > order[1]["newest"]:
            s = order[0]["newest_src"]
            txt = (f"\"{order[0]['p']['value']}\" comes from the most recent source (**{s['doc_name']}**, {s['doc_date']}), so it may be the more current figure - "
                   f"but nothing in the documents says it replaces the earlier one.")
            if time_scoped:
                txt += " The values may also simply describe different points in time."
            return txt
    return "The documents carry no dates or wording that show which statement takes precedence, so I can't tell which is correct."
