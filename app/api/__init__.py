"""Router registration. Routers are added per milestone."""

from __future__ import annotations

from fastapi import FastAPI


def register_routers(app: FastAPI) -> None:
    from app.api import assets, characters, graph, render, scenes

    app.include_router(assets.router)
    app.include_router(characters.router)
    app.include_router(scenes.router)
    app.include_router(render.router)
    app.include_router(graph.router)
