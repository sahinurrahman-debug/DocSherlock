"""Uncertainty engine: evidence-based confidence with itemised reasons and the five public levels.

Levels: HIGH | MEDIUM | LOW | CONFLICTED | INSUFFICIENT. The numeric score is an internal evidence-strength signal built from
term coverage, semantic similarity, corroboration, unknown terms, OCR quality and conflicts - it is *not* a probability, so the UI
leads with the level and the reasons.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.evidence import Context

ABSTAIN_BELOW = 0.40
HIGH_AT = 0.68
MEDIUM_AT = 0.50
MAX_CONF = 0.97


# ---------------------------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------------------------
def label_for(score: float) -> str:
    return "High" if score >= HIGH_AT else "Medium" if score >= MEDIUM_AT else "Low"


def confidence(ctx: Context, supporting_docs: int, min_ocr: float | None, has_conflict: bool, answered_values_diverge: bool = False) -> dict:
    """Confidence that the returned answer is supported by the documents (for conflicts: that a real, relevant conflict exists)."""
    reasons: list[dict] = []
    if has_conflict and ctx.conflicts:
        cl = ctx.conflicts[0]
        n_src = cl["n_sources"]
        s = 0.55 * cl["score"] + 0.45 * ctx.conflict_cov
        reasons.append({"text": f"{len(cl['positions'])} incompatible values for the same subject across {n_src} statements", "effect": "+"})
        reasons.append({"text": f"The conflicting statements cover {ctx.conflict_cov:.0%} of the question's key terms", "effect": "+" if ctx.conflict_cov >= 0.6 else "="})
        if cl["time_scoped"]:
            s -= 0.1
            reasons.append({"text": "At least one statement is tied to a specific period - values may be time-dependent rather than contradictory", "effect": "-"})
        if min_ocr is not None and min_ocr < 0.88:
            s -= (0.88 - min_ocr) * 0.6
            reasons.append({"text": f"A conflicting figure comes from a scan read at {min_ocr:.0%} OCR confidence", "effect": "-"})
        reasons.append({"text": "No single answer is justified - see the resolution notes", "effect": "="})
        s = max(0.0, min(MAX_CONF, s))
        return {"score": round(s, 3), "label": label_for(s), "kind": "conflict", "reasons": reasons}

    if not ctx.evidence:
        return {"score": 0.0, "label": "None", "kind": "answer", "reasons": [{"text": "No passage in the documents matches the question.", "effect": "-"}]}
    best_hit_rel = max((h.relevance for h in ctx.hits[:3]), default=0.0)
    rel = 0.65 * ctx.best_cov + 0.35 * best_hit_rel
    if ctx.union_cov > ctx.best_cov:
        rel = max(rel, 0.65 * ctx.union_cov + 0.35 * best_hit_rel)
    s = rel
    reasons.append({"text": f"Best passage covers {ctx.best_cov:.0%} of the question's key terms"
                            + (f" (semantic match {best_hit_rel:.0%})" if ctx.dense_active else ""), "effect": "+" if ctx.best_cov >= 0.6 else "-"})
    if supporting_docs >= 2:
        s += 0.08
        reasons.append({"text": f"Corroborated by {supporting_docs} documents", "effect": "+"})
    elif supporting_docs == 1 and ctx.n_docs_corpus > 1:
        reasons.append({"text": "Supported by a single document", "effect": "="})
    if ctx.missing_terms:
        frac = len(ctx.missing_terms) / max(len(ctx.info.terms), 1)
        s -= min(0.5, 0.75 * frac)
        reasons.append({"text": "Not found in any document: " + ", ".join(f"'{t}'" for t in ctx.missing_terms[:5]), "effect": "-"})
    if ctx.union_cov < 0.5:
        s -= (0.5 - ctx.union_cov) * 0.5
        reasons.append({"text": "Part of the question is not addressed by the retrieved text", "effect": "-"})
    if min_ocr is not None and min_ocr < 0.88:
        s -= (0.88 - min_ocr) * 0.8
        reasons.append({"text": f"Evidence comes from a scanned source read with {min_ocr:.0%} OCR confidence", "effect": "-"})
    elif min_ocr is not None:
        reasons.append({"text": f"Evidence read via OCR ({min_ocr:.0%} confidence)", "effect": "="})
    if answered_values_diverge:
        s = min(s, 0.6)
        reasons.append({"text": "Related passages mention different values", "effect": "-"})
    s = max(0.0, min(MAX_CONF, s))
    return {"score": round(s, 3), "label": label_for(s), "kind": "answer", "reasons": reasons}




def level_for(status: str, score: float) -> str:
    if status == "conflict":
        return "CONFLICTED"
    if status == "insufficient":
        return "INSUFFICIENT"
    return "HIGH" if score >= HIGH_AT else "MEDIUM" if score >= MEDIUM_AT else "LOW"
