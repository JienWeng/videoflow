"""Router registration. Routers are added per milestone."""

from __future__ import annotations

from fastapi import FastAPI


def register_routers(app: FastAPI) -> None:
    from app.api import assets, characters, chat, events, graph, render, scenes, style

    app.include_router(assets.router)
    app.include_router(characters.router)
    app.include_router(scenes.router)
    app.include_router(render.router)
    app.include_router(style.router)
    app.include_router(graph.router)
    app.include_router(chat.router)
    app.include_router(events.router)
