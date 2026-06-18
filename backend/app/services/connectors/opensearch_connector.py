"""OpenSearch full-text search connector — retrieve-only."""
from typing import List

import httpx

from app.core.ssrf import validate_url


async def retrieve(config: dict, query: str) -> List[str]:
    """Search one or more OpenSearch indexes with BM25 match query, return source text."""
    endpoint = config["endpoint"].rstrip("/")
    validate_url(endpoint)
    username = config["username"]
    password = config["password"]
    text_field = config.get("text_field", "content")
    top_k = int(config.get("top_k", 3))
    # OpenSearch natively supports comma-joined index names in the URL
    index_names = ",".join(n.strip() for n in config.get("index_name", "").split(",") if n.strip())

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{endpoint}/{index_names}/_search",
            json={"query": {"match": {text_field: query}}, "size": top_k, "_source": [text_field]},
            headers={"Content-Type": "application/json"},
            auth=(username, password),
        )
        resp.raise_for_status()

    hits = resp.json().get("hits", {}).get("hits", [])
    return [h["_source"][text_field] for h in hits if h.get("_source", {}).get(text_field)]


async def test_connectivity(config: dict) -> None:
    """Call _count on the first index to verify connectivity. Raises on failure."""
    endpoint = config["endpoint"].rstrip("/")
    validate_url(endpoint)
    first = config.get("index_name", "").split(",")[0].strip()

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{endpoint}/{first}/_count",
            auth=(config["username"], config["password"]),
        )
        resp.raise_for_status()

test_connectivity.__test__ = False
