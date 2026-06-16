"""
Azure AI Search retrieval connector — retrieve-only, no indexing.
"""
from typing import List

import requests

from app.core.ssrf import validate_url


def retrieve(config: dict, query: str) -> List[str]:
    """Query an Azure AI Search index and return content chunks."""
    endpoint = config["endpoint"].rstrip("/")
    validate_url(endpoint)

    index_name = config["index_name"]
    api_key = config["api_key"]
    top_k = int(config.get("top_k", 3))
    semantic_config = config.get("semantic_config", "")

    url = f"{endpoint}/indexes/{index_name}/docs/search?api-version=2023-11-01"
    body: dict = {"search": query, "top": top_k, "select": "content"}
    if semantic_config:
        body["queryType"] = "semantic"
        body["semanticConfiguration"] = semantic_config

    resp = requests.post(
        url,
        json=body,
        headers={"api-key": api_key, "Content-Type": "application/json"},
        timeout=10,
    )
    resp.raise_for_status()

    hits = resp.json().get("value", [])
    return [h["content"] for h in hits if h.get("content")]
