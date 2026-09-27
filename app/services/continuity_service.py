"""Small local continuity index used before scene and shot generation.

This deliberately starts with deterministic lexical retrieval. It keeps the
workflow useful without a paid embedding key and provides the stable record
contract that remote embeddings/rerankers can implement later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ContinuityRecord:
    id: str
    text: str
    kind: str


def _terms(text: str) -> set[str]:
    return {
        token.casefold()
        for token in re.findall(r"[\w\u4e00-\u9fff]+", text or "")
        if len(token) > 1
    }


def rank_records(records: list[ContinuityRecord], query: str) -> list[ContinuityRecord]:
    query_terms = _terms(query)

    def score(record: ContinuityRecord) -> tuple[int, int]:
        overlap = len(query_terms & _terms(record.text))
        # Prefer durable entity records when scores tie; they are the most
        # useful anchors for character and location continuity.
        kind_bonus = 1 if record.kind in {"character", "location", "asset"} else 0
        return overlap, kind_bonus

    return sorted(records, key=score, reverse=True)


def context_for_scene(
    *,
    story: str,
    scenes: list[dict],
    characters: list[dict],
    assets: list[dict],
    limit: int = 8,
) -> list[ContinuityRecord]:
    records = [
        ContinuityRecord(f"character:{i}", f"{c.get('name', '')} {c.get('appearance', '')}", "character")
        for i, c in enumerate(characters)
    ]
    records.extend(
        ContinuityRecord(f"asset:{i}", f"{a.get('name', '')} {a.get('description', '')}", "asset")
        for i, a in enumerate(assets)
    )
    records.extend(
        ContinuityRecord(str(s.get("id", i)), f"{s.get('title', '')} {s.get('summary', '')}", "scene")
        for i, s in enumerate(scenes)
    )
    return rank_records(records, story)[:limit]
