"""Qdrant vector search connector — retrieve-only."""
import asyncio
from typing import List

import httpx

from app.core.ssrf import validate_url


async def _query_one(client: httpx.AsyncClient, endpoint: str, collection_name: str, api_key: str, query_vector: List[float], top_k: int, text_field: str) -> List[str]:
    resp = await client.post(
        f"{endpoint}/collections/{collection_name}/points/search",
        json={"vector": query_vector, "limit": top_k, "with_payload": True},
        headers={"api-key": api_key, "Content-Type": "application/json"},
    )
    resp.raise_for_status()
    results = resp.json().get("result", [])
    return [r["payload"][text_field] for r in results if r.get("payload", {}).get(text_field)]


async def retrieve(config: dict, query_vector: List[float]) -> List[str]:
    """Search one or more Qdrant collections by vector and return text payloads."""
    endpoint = config["endpoint"].rstrip("/")
    validate_url(endpoint)
    api_key = config["api_key"]
    top_k = int(config.get("top_k", 3))
    text_field = config.get("text_field", "content")
    collection_names = [n.strip() for n in config.get("collection_name", "").split(",") if n.strip()]

    async with httpx.AsyncClient(timeout=10.0) as client:
        results = await asyncio.gather(
            *[_query_one(client, endpoint, name, api_key, query_vector, top_k, text_field) for name in collection_names]
        )
    return [chunk for chunks in results for chunk in chunks]


async def test_connectivity(config: dict) -> None:
    """Verify the first listed Qdrant collection exists. Raises on failure."""
    endpoint = config["endpoint"].rstrip("/")
    validate_url(endpoint)
    api_key = config["api_key"]
    first = config.get("collection_name", "").split(",")[0].strip()

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{endpoint}/collections/{first}",
            headers={"api-key": api_key},
        )
        resp.raise_for_status()

test_connectivity.__test__ = False
