"""In-process fake servers for the hosted-embeddings + remote-Qdrant setup (no conftest import, so they can be used by measurement scripts too)."""
from __future__ import annotations

import hashlib
import json
import re

import httpx
import numpy as np

DIM = 64


def fake_vec(text: str) -> list[float]:
    """Bag-of-words hashing embedding: texts sharing words are close in cosine distance."""
    v = np.zeros(DIM)
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        v[int(hashlib.md5(w.encode()).hexdigest(), 16) % DIM] += 1
    return v.tolist()


class FakeEmbeddingAPI:
    def __init__(self, fail_first: int = 0, dim: int = DIM):
        self.calls: list[dict] = []
        self.headers: list[dict] = []
        self.fail_first, self.dim = fail_first, dim

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls.append(body)
        self.headers.append(dict(request.headers))
        if self.fail_first > 0:
            self.fail_first -= 1
            return httpx.Response(429, headers={"retry-after": "0"}, json={"error": "slow down"})
        data = [{"index": i, "embedding": (fake_vec(t) + [0.0] * self.dim)[:self.dim]} for i, t in enumerate(body["input"])]
        return httpx.Response(200, json={"data": list(reversed(data))})            # out of order on purpose


class FakeQdrant:
    """Just enough of Qdrant's REST API, with official-model validation of every body."""

    def __init__(self, validate: bool = True):
        self.collections: dict[str, dict] = {}
        self.points: dict[str, dict[str, dict]] = {}
        self.requests: list[tuple[str, str]] = []
        self.validate = validate                                 # off for memory measurements: the official models are ~90 MB of RAM

    def _check(self, model: str, body: dict) -> None:
        if self.validate:
            from qdrant_client import models
            getattr(models, model).model_validate(body)

    @staticmethod
    def _passes(payload: dict, flt: dict | None) -> bool:
        for cond in (flt or {}).get("must", []):
            got = payload.get(cond["key"])
            m = cond["match"]
            if "value" in m and got != m["value"]:
                return False
            if "any" in m and got not in m["any"]:
                return False
        return True

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        body = json.loads(request.content) if request.content else {}
        self.requests.append((method, path))
        assert request.headers.get("api-key") == "qd-test-key"
        ok = lambda result=None: httpx.Response(200, json={"result": result, "status": "ok"})      # noqa: E731
        if path == "/collections" and method == "GET":
            return ok({"collections": [{"name": n} for n in self.collections]})
        m = re.fullmatch(r"/collections/([^/]+)(?:/(.*))?", path)
        assert m, path
        name, rest = m.group(1), m.group(2)
        if rest is None and method == "PUT":
            self._check("CreateCollection", body)
            self.collections[name] = body
            self.points[name] = {}
            return ok(True)
        assert name in self.collections, "collection used before it was created"
        pts = self.points[name]
        if rest == "index":
            self._check("CreateFieldIndex", body)
            return ok()
        if rest == "points":
            for p in body["points"]:
                self._check("PointStruct", p)
                pts[p["id"]] = p
            return ok()
        if rest == "points/delete":
            self._check("Filter", body["filter"])
            assert body["filter"]["must"]
            for k in [k for k, p in pts.items() if self._passes(p["payload"], body["filter"])]:
                del pts[k]
            return ok()
        if rest == "points/count":
            self._check("CountRequest", body)
            return ok({"count": sum(self._passes(p["payload"], body.get("filter")) for p in pts.values())})
        if rest == "points/query":
            self._check("QueryRequest", body)
            using, q = body["using"], body["query"]
            scored = []
            for p in pts.values():
                if using not in p["vector"] or not self._passes(p["payload"], body.get("filter")):
                    continue
                v = p["vector"][using]
                if using == "dense":
                    a, b = np.array(v), np.array(q)
                    s = float(a @ b / ((np.linalg.norm(a) * np.linalg.norm(b)) or 1))
                else:
                    qi = dict(zip(q["indices"], q["values"]))
                    s = sum(qi.get(i, 0) * x for i, x in zip(v["indices"], v["values"]))
                scored.append((s, p))
            scored.sort(key=lambda t: -t[0])
            return ok({"points": [{"id": p["id"], "score": s, "payload": {"chunk_id": p["payload"]["chunk_id"]}} for s, p in scored[:body["limit"]]]})
        raise AssertionError(f"unexpected request {method} {path}")
