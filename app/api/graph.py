"""Relationship graph endpoint: characters → assets → scenes → shots → outputs."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.database import get_session
from app.models import Asset, Character, RenderJob, RenderOutput, Scene, Shot

router = APIRouter(tags=["graph"])


@router.get("/graph")
def graph(session: Session = Depends(get_session)) -> dict:
    nodes: list[dict] = []
    edges: list[dict] = []

    def node(id: str, type_: str, label: str) -> None:
        nodes.append({"id": id, "type": type_, "label": label})

    def edge(source: str, target: str, label: str = "") -> None:
        edges.append({"source": source, "target": target, "label": label})

    characters = session.exec(select(Character)).all()
    for c in characters:
        node(c.id, "character", c.name)

    for a in session.exec(select(Asset)).all():
        node(a.id, "asset", a.name or a.id)
        if a.character_id:
            edge(a.character_id, a.id, "reference")
    # Reference assets linked only via the character's id list.
    seen = {(e["source"], e["target"]) for e in edges}
    for c in characters:
        for aid in c.reference_asset_ids_json or []:
            if (c.id, aid) not in seen:
                edge(c.id, aid, "reference")

    for s in session.exec(select(Scene)).all():
        node(s.id, "scene", s.title or s.id)
        for cid in s.character_ids_json or []:
            edge(s.id, cid, "casts")
        for aid in s.asset_ids_json or []:
            edge(s.id, aid, "uses")

    for sh in session.exec(select(Shot)).all():
        node(sh.id, "shot", f"#{sh.shot_order + 1} {sh.prompt[:40]}")
        edge(sh.scene_id, sh.id, "shot")
        for aid in sh.asset_ids_json or []:
            edge(sh.id, aid, "uses")

    for j in session.exec(select(RenderJob)).all():
        node(j.id, "render_job", f"{j.status} ({j.model.split('/')[-1]})")
        edge(j.shot_id or j.scene_id, j.id, "render")

    for o in session.exec(select(RenderOutput)).all():
        node(o.id, "output", o.video_path.rsplit("/", 1)[-1] if o.video_path else o.id)
        edge(o.render_job_id, o.id, "output")

    return {"nodes": nodes, "edges": edges}
