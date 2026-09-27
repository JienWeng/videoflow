"""Deterministic shot dependency planning inspired by ViMax camera graphs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ShotDependency:
    shot_id: str
    depends_on: tuple[str, ...]
    layer: int


def build_shot_dependencies(shots: list[dict]) -> list[ShotDependency]:
    """Create a safe camera/continuity chain from ordered shot metadata.

    Explicit ``depends_on`` values are honoured when valid; otherwise each shot
    anchors to the previous shot. This gives providers a deterministic visual
    handoff while preserving a simple fallback for older scenes.
    """
    known = {str(shot["id"]) for shot in shots}
    result: list[ShotDependency] = []
    layers: dict[str, int] = {}
    for index, shot in enumerate(shots):
        shot_id = str(shot["id"])
        explicit = [str(item) for item in shot.get("depends_on", []) if str(item) in known and str(item) != shot_id]
        parents = tuple(dict.fromkeys(explicit or ([str(shots[index - 1]["id"])] if index else [])))
        layer = max((layers[parent] for parent in parents), default=-1) + 1
        layers[shot_id] = layer
        result.append(ShotDependency(shot_id, parents, layer))
    return result


def select_best_candidate(scores: list[float]) -> int:
    """Return the stable best-of-k candidate index, rejecting empty scores."""
    if not scores:
        raise ValueError("at least one candidate score is required")
    return max(range(len(scores)), key=lambda index: (scores[index], -index))
