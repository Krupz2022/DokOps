"""Pinecone vector search connector — retrieve-only."""
from typing import List

import httpx

from app.core.ssrf import validate_url

_PINECONE_API_VERSION = "2025-04"


async def retrieve(config: dict, query_vector: List[float]) -> List[str]:
    """Query a Pinecone index by vector and return metadata text fields."""
    index_host = config["index_host"].rstrip("/")
    validate_url(index_host)
    api_key = config["api_key"]
    namespace = config.get("namespace", "")
    top_k = int(config.get("top_k", 3))
    text_field = config.get("metadata_text_field", "text")

    body: dict = {"vector": query_vector, "topK": top_k, "includeMetadata": True, "includeValues": False}
    if namespace:
        body["namespace"] = namespace

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{index_host}/query",
            json=body,
            headers={"Api-Key": api_key, "Content-Type": "application/json", "X-Pinecone-API-Version": _PINECONE_API_VERSION},
        )
        resp.raise_for_status()

    matches = resp.json().get("matches", [])
    return [m["metadata"][text_field] for m in matches if m.get("metadata", {}).get(text_field)]


async def test_connectivity(config: dict) -> None:
    """Call describe_index_stats to verify connectivity. Raises on failure."""
    index_host = config["index_host"].rstrip("/")
    validate_url(index_host)

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{index_host}/describe_index_stats",
            headers={"Api-Key": config["api_key"], "X-Pinecone-API-Version": _PINECONE_API_VERSION},
        )
        resp.raise_for_status()

test_connectivity.__test__ = False
