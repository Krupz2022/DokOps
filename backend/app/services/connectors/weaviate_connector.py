"""Weaviate GraphQL nearText connector — retrieve-only."""
import asyncio
from typing import List

import httpx

from app.core.ssrf import validate_url


async def _query_one(client: httpx.AsyncClient, endpoint: str, api_key: str, collection_name: str, query: str, top_k: int, text_property: str) -> List[str]:
    graphql_query = (
        "{ Get { "
        f"{collection_name}("
        f'nearText: {{concepts: ["{query}"]}}, '
        f"limit: {top_k}"
        f") {{ {text_property} }} }}"
    )
    resp = await client.post(
        f"{endpoint}/v1/graphql",
        json={"query": graphql_query},
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    resp.raise_for_status()
    objects = resp.json().get("data", {}).get("Get", {}).get(collection_name, [])
    return [obj[text_property] for obj in objects if obj.get(text_property)]


async def retrieve(config: dict, query: str) -> List[str]:
    """Search one or more Weaviate collections with nearText and return text property values."""
    endpoint = config["endpoint"].rstrip("/")
    validate_url(endpoint)
    api_key = config["api_key"]
    text_property = config.get("text_property", "content")
    top_k = int(config.get("top_k", 3))
    collection_names = [n.strip() for n in config.get("collection_name", "").split(",") if n.strip()]

    async with httpx.AsyncClient(timeout=10.0) as client:
        results = await asyncio.gather(
            *[_query_one(client, endpoint, api_key, name, query, top_k, text_property) for name in collection_names]
        )
    return [chunk for chunks in results for chunk in chunks]


async def test_connectivity(config: dict) -> None:
    """Check the first collection exists in Weaviate schema. Raises on failure."""
    endpoint = config["endpoint"].rstrip("/")
    validate_url(endpoint)
    first = config.get("collection_name", "").split(",")[0].strip()

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{endpoint}/v1/schema/{first}",
            headers={"Authorization": f"Bearer {config['api_key']}"},
        )
        resp.raise_for_status()

test_connectivity.__test__ = False
