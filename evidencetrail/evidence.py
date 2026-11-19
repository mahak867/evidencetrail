"""Evidence store and the evidence gate.

Rule: no evidence, no claim. A claim survives only if every evidence ID it cites
was actually fetched during this investigation, and (when it quotes text) the
quoted text really appears in that evidence item.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field


@dataclass
class Item:
    id: str
    kind: str  # log | metric | trace | change
    ref: str   # human pointer: payment.log:1834, trace:abc..., payment.error_ratio
    text: str
    meta: dict


@dataclass
class EvidenceStore:
    items: dict[str, Item] = field(default_factory=dict)

    def add(self, kind: str, ref: str, text: str, meta: dict | None = None) -> str:
        h = hashlib.sha1(f"{kind}|{ref}|{text}".encode()).hexdigest()[:6]
        eid = f"{kind[0].upper()}-{h}"
        self.items[eid] = Item(eid, kind, ref, text, meta or {})
        return eid

    def get(self, eid: str) -> Item | None:
        return self.items.get(eid)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


@dataclass
class GateResult:
    kept: list[dict]
    dropped: list[dict]

    @property
    def precision(self) -> float:
        n = len(self.kept) + len(self.dropped)
        return len(self.kept) / n if n else 0.0


def gate(claims: list[dict], store: EvidenceStore) -> GateResult:
    kept, dropped = [], []
    for c in claims:
        ids = c.get("evidence_ids") or []
        problems = []
        if not ids:
            problems.append("no evidence cited")
        for eid in ids:
            item = store.get(eid)
            if item is None:
                problems.append(f"{eid} was never fetched (fabricated citation)")
        quote = (c.get("quote") or "").strip()
        if quote and ids and not problems:
            if not any(_norm(quote) in _norm(store.get(e).text) for e in ids):
                problems.append("quoted text not found in cited evidence")
        if problems:
            dropped.append({**c, "rejected_because": problems})
        else:
            kept.append({**c, "evidence": [vars(store.get(e)) for e in ids]})
    return GateResult(kept, dropped)
