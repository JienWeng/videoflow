"""Relationship graph endpoint: characters → assets → scenes → shots → outputs."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.database import get_session
from app.models import Asset, Character, RenderJob, RenderOutput, Scene, Shot
from app.services import project_service

router = APIRouter(tags=["graph"])


@router.get("/graph")
def graph(session: Session = Depends(get_session)) -> dict:
    # Active-project scoping: only the active project's entities appear.
    pid = project_service.active_project_id(session)
    nodes: list[dict] = []
    edges: list[dict] = []

    def node(id: str, type_: str, label: str, **data) -> None:
        nodes.append({"id": id, "type": type_, "label": label, "data": data})

    def edge(source: str, target: str, label: str = "") -> None:
        edges.append({"source": source, "target": target, "label": label})

    characters = session.exec(
        select(Character).where(Character.project_id == pid)
    ).all()
    for c in characters:
        node(c.id, "character", c.name)

    for a in session.exec(select(Asset).where(Asset.project_id == pid)).all():
        node(a.id, "asset", a.name or a.id, file_path=a.file_path, asset_type=a.type)
        if a.character_id:
            edge(a.character_id, a.id, "reference")
        # Storyboards and registered render videos link to their scene only
        # through metadata; without this they float as orphan canvas nodes.
        meta_scene = (a.metadata_json or {}).get("scene_id")
        if meta_scene:
            edge(meta_scene, a.id, a.type)
    # Reference assets linked only via the character's id list.
    seen = {(e["source"], e["target"]) for e in edges}
    for c in characters:
        for aid in c.reference_asset_ids_json or []:
            if (c.id, aid) not in seen:
                edge(c.id, aid, "reference")

    scene_ids: set[str] = set()
    for s in session.exec(select(Scene).where(Scene.project_id == pid)).all():
        scene_ids.add(s.id)
        node(s.id, "scene", s.title or s.id,
             aspect_ratio=s.aspect_ratio, duration=s.duration, summary=s.summary)
        for cid in s.character_ids_json or []:
            edge(s.id, cid, "casts")
        for aid in s.asset_ids_json or []:
            edge(s.id, aid, "uses")

    for sh in session.exec(select(Shot)).all():
        if sh.scene_id not in scene_ids:
            continue
        node(sh.id, "shot", f"#{sh.shot_order + 1} {sh.prompt[:40]}",
             scene_id=sh.scene_id, shot_order=sh.shot_order, duration=sh.duration,
             prompt=sh.prompt, camera=sh.camera, movement=sh.movement)
        edge(sh.scene_id, sh.id, "shot")
        for aid in sh.asset_ids_json or []:
            edge(sh.id, aid, "uses")

    job_ids: set[str] = set()
    for j in session.exec(select(RenderJob).where(RenderJob.project_id == pid)).all():
        job_ids.add(j.id)
        node(j.id, "render_job", f"{j.status.value} ({j.model.split('/')[-1]})",
             status=j.status.value)
        edge(j.shot_id or j.scene_id, j.id, "render")

    for o in session.exec(select(RenderOutput)).all():
        if o.render_job_id not in job_ids:
            continue
        node(o.id, "output", o.video_path.rsplit("/", 1)[-1] if o.video_path else o.id,
             video_path=o.video_path, thumbnail_path=o.thumbnail_path,
             captioned_path=o.captioned_path, score=o.score,
             qa_issues=(o.qa_json or {}).get("issues", []),
             render_job_id=o.render_job_id)
        edge(o.render_job_id, o.id, "output")

    known = {n["id"] for n in nodes}
    edges = [e for e in edges if e["source"] in known and e["target"] in known]

    return {"nodes": nodes, "edges": edges}
