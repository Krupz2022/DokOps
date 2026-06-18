"""Chroma HTTP server connector — retrieve-only."""
import asyncio
from typing import List

import httpx

from app.core.ssrf import validate_url


def _build_headers(api_token: str) -> dict:
    headers: dict = {"Content-Type": "application/json"}
    if api_token:
        headers["Authorization"] = f"Bearer {api_token}"
    return headers


async def _resolve_collection_id(client: httpx.AsyncClient, endpoint: str, collection_name: str, headers: dict) -> str:
    resp = await client.get(f"{endpoint}/api/v1/collections/{collection_name}", headers=headers)
    resp.raise_for_status()
    return resp.json()["id"]


async def _query_one(client: httpx.AsyncClient, endpoint: str, collection_name: str, headers: dict, query: str, top_k: int) -> List[str]:
    collection_id = await _resolve_collection_id(client, endpoint, collection_name, headers)
    resp = await client.post(
        f"{endpoint}/api/v1/collections/{collection_id}/query",
        json={"query_texts": [query], "n_results": top_k, "include": ["documents"]},
        headers=headers,
    )
    resp.raise_for_status()
    documents = resp.json().get("documents", [[]])
    return [doc for doc in documents[0] if doc] if documents else []


async def retrieve(config: dict, query: str) -> List[str]:
    """Query one or more Chroma collections by text and return document strings."""
    endpoint = config["endpoint"].rstrip("/")
    validate_url(endpoint)
    api_token = config.get("api_token", "")
    top_k = int(config.get("top_k", 3))
    headers = _build_headers(api_token)
    collection_names = [n.strip() for n in config.get("collection_name", "").split(",") if n.strip()]

    async with httpx.AsyncClient(timeout=10.0) as client:
        results = await asyncio.gather(
            *[_query_one(client, endpoint, name, headers, query, top_k) for name in collection_names]
        )
    return [chunk for chunks in results for chunk in chunks]


async def test_connectivity(config: dict) -> None:
    """Resolve the first collection by name to verify connectivity. Raises on failure."""
    endpoint = config["endpoint"].rstrip("/")
    validate_url(endpoint)
    api_token = config.get("api_token", "")
    first = config.get("collection_name", "").split(",")[0].strip()
    headers = _build_headers(api_token)

    async with httpx.AsyncClient(timeout=10.0) as client:
        await _resolve_collection_id(client, endpoint, first, headers)

test_connectivity.__test__ = False
