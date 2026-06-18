"""Azure AI Search retrieval connector — retrieve-only, no indexing."""
import asyncio
from typing import List

import httpx

from app.core.ssrf import validate_url


async def _query_one(client: httpx.AsyncClient, endpoint: str, index_name: str, api_key: str, query: str, top_k: int, semantic_config: str) -> List[str]:
    url = f"{endpoint}/indexes/{index_name}/docs/search?api-version=2023-11-01"
    body: dict = {"search": query, "top": top_k, "select": "content"}
    if semantic_config:
        body["queryType"] = "semantic"
        body["semanticConfiguration"] = semantic_config
    resp = await client.post(url, json=body, headers={"api-key": api_key, "Content-Type": "application/json"})
    resp.raise_for_status()
    return [h["content"] for h in resp.json().get("value", []) if h.get("content")]


async def retrieve(config: dict, query: str) -> List[str]:
    """Query one or more Azure AI Search indexes and return content chunks."""
    endpoint = config["endpoint"].rstrip("/")
    validate_url(endpoint)
    api_key = config["api_key"]
    top_k = int(config.get("top_k", 3))
    semantic_config = config.get("semantic_config", "")
    index_names = [n.strip() for n in config.get("index_name", "").split(",") if n.strip()]

    async with httpx.AsyncClient(timeout=10.0) as client:
        results = await asyncio.gather(
            *[_query_one(client, endpoint, name, api_key, query, top_k, semantic_config) for name in index_names]
        )
    return [chunk for chunks in results for chunk in chunks]
