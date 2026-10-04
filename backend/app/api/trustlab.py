"""Trust Lab: run the adversarial stress test against this deployment and read the last report."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.services import trustlab

router = APIRouter(prefix="/api/trustlab", tags=["trust"])


@router.get("")
def overview():
    """The cases the lab runs, and the most recent report (null until someone has run it)."""
    return {"cases": trustlab.catalogue(), "last": trustlab.last_result()}


@router.post("/run")
def run():
    """Run every case in a throwaway workspace (a few seconds; no API key or network needed). Nothing of the visitor's own data is touched."""
    try:
        return trustlab.run_suite()
    except trustlab.Busy as exc:
        raise HTTPException(409, str(exc))
