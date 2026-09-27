"""Optional OpenRouter retrieval primitives for long-form continuity."""

from __future__ import annotations

from app.providers.openrouter_client import OpenRouterClient


class OpenRouterRetrieval:
    def __init__(self, client: OpenRouterClient | None = None) -> None:
        self.client = client or OpenRouterClient()

    async def embed(self, texts: list[str], model: str) -> list[list[float]]:
        body = await self.client.create_embeddings({"model": model, "input": texts})
        return [item["embedding"] for item in body.get("data", [])]

    async def rerank(self, query: str, documents: list[str], model: str, top_n: int = 5) -> list[dict]:
        body = await self.client.rerank({"model": model, "query": query, "documents": documents, "top_n": top_n})
        return list(body.get("results", []))
