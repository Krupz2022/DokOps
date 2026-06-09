import json
import logging
from typing import Any, Dict, Optional, Tuple

import httpx

from app.services.integrations.base import BaseIntegrationService

logger = logging.getLogger(__name__)


class ElasticsearchService(BaseIntegrationService):

    async def test_connection(self, base_url: str, headers: Dict[str, str]) -> Tuple[bool, str]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(base_url.rstrip("/"), headers=headers)
            if resp.status_code == 200:
                return True, "Connected"
            return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
        except Exception as e:
            return False, str(e)

    def get_tool_registry(self, base_url: str, headers: Dict[str, str]) -> Dict[str, Any]:
        url = base_url.rstrip("/")
        req_headers = {"Content-Type": "application/json", **headers}

        # Redact auth header for logging
        _safe_headers = {k: ("***REDACTED***" if k.lower() in ("authorization", "x-api-key") else v)
                         for k, v in headers.items()}

        async def elasticsearch_search(
            index: str,
            query_json: str,
            size: int = 20,
        ) -> Dict[str, Any]:
            """Execute an Elasticsearch query DSL search."""
            endpoint = f"{url}/{index}/_search"
            try:
                # Try standard JSON; fall back to ast.literal_eval for Python-dict strings (single quotes etc.)
                try:
                    body = json.loads(query_json)
                except json.JSONDecodeError as _je:
                    import ast as _ast
                    try:
                        body = _ast.literal_eval(query_json)
                        logger.debug("[ES] query_json was not valid JSON, recovered via ast.literal_eval")
                    except Exception:
                        return {
                            "success": False, "data": None,
                            "error": (
                                f"query_json is not valid JSON (error: {_je}). "
                                "Use double-quoted keys and string values. "
                                'Example: {"query":{"bool":{"must":[{"match":{"message":"error"}}]}}}'
                            ),
                        }
                body.setdefault("size", int(size) if isinstance(size, str) else size)

                logger.debug("[ES] POST %s | headers: %s | body: %s",
                            endpoint, _safe_headers, json.dumps(body)[:500])

                # expand_wildcards=open,hidden ensures data stream backing indices (.ds-*) are included
                _search_params = {"expand_wildcards": "open,hidden"}
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(
                        endpoint,
                        headers=req_headers,
                        content=json.dumps(body),
                        params=_search_params,
                    )

                logger.debug("[ES] POST %s -> HTTP %d | body[:500]: %s",
                            endpoint, resp.status_code, resp.text[:500])

                if resp.status_code == 404:
                    return {"success": False, "data": None, "error": f"Index '{index}' not found in Elasticsearch. Use elasticsearch_list_indices to see available indices."}
                if resp.status_code not in (200, 201):
                    try:
                        err_body = resp.json().get("error", {})
                        # Dig into root_cause for the real reason (ES nests it)
                        root_causes = err_body.get("root_cause", [])
                        if root_causes:
                            cause = root_causes[0]
                            err_detail = f"{cause.get('type', 'unknown')}: {cause.get('reason', '')}. Fix hint: if using wildcard/term on a text field, append .keyword (e.g. kubernetes.namespace.keyword)"
                        else:
                            err_detail = err_body.get("reason", resp.text[:300])
                    except Exception:
                        err_detail = resp.text[:300]
                    return {"success": False, "data": None, "error": f"HTTP {resp.status_code}: {err_detail}"}

                body_resp = resp.json()
                hits = body_resp.get("hits", {})
                total = hits.get("total", {}).get("value", 0) if isinstance(hits.get("total"), dict) else hits.get("total", 0)
                results = [h.get("_source", h) for h in hits.get("hits", [])]

                logger.debug("[ES] search result: total=%d returned=%d", total, len(results))
                return {"success": True, "data": results, "total": total, "error": None}

            except json.JSONDecodeError as e:
                logger.error("[ES] POST %s | invalid query JSON: %s", endpoint, e)
                return {"success": False, "data": None, "error": f"Invalid query JSON: {e}"}
            except Exception as e:
                logger.error("[ES] POST %s | exception: %s", endpoint, e)
                return {"success": False, "data": None, "error": str(e)}

        async def elasticsearch_list_indices() -> Dict[str, Any]:
            """List all Elasticsearch indices and data streams with document count and size."""
            results: list = []
            total_raw = 0

            async with httpx.AsyncClient(timeout=15.0) as client:
                # --- Regular indices ---
                ep_idx = f"{url}/_cat/indices"
                params_idx = {"format": "json", "h": "index,docs.count,store.size,health"}
                logger.debug("[ES] GET %s | params: %s | headers: %s", ep_idx, params_idx, _safe_headers)
                try:
                    r_idx = await client.get(ep_idx, headers=headers, params=params_idx)
                    logger.debug("[ES] GET %s -> HTTP %d | body[:500]: %s", ep_idx, r_idx.status_code, r_idx.text[:500])
                    if r_idx.status_code == 200:
                        raw_idx = r_idx.json() or []
                        total_raw += len(raw_idx)
                        for r in raw_idx:
                            name = r.get("index", "")
                            # Skip hidden/system indices (dot-prefixed) and data stream backing indices
                            if name and not name.startswith(".") and not name.startswith(".ds-"):
                                results.append({
                                    "name": name,
                                    "type": "index",
                                    "docs": r.get("docs.count"),
                                    "size": r.get("store.size"),
                                    "health": r.get("health"),
                                })
                except Exception as e:
                    logger.error("[ES] indices fetch error: %s", e)

                # --- Data streams (/_data_stream is more reliable than _cat/data_streams) ---
                ep_ds = f"{url}/_data_stream"
                logger.debug("[ES] GET %s", ep_ds)
                try:
                    r_ds = await client.get(ep_ds, headers=headers)
                    logger.debug("[ES] GET %s -> HTTP %d | body[:500]: %s", ep_ds, r_ds.status_code, r_ds.text[:500])
                    if r_ds.status_code == 200:
                        raw_ds = r_ds.json().get("data_streams", [])
                        total_raw += len(raw_ds)
                        for r in raw_ds:
                            name = r.get("name", "")
                            if name and not r.get("hidden", False):
                                results.append({
                                    "name": name,
                                    "type": "data_stream",
                                    "backing_indices": len(r.get("indices", [])),
                                    "status": r.get("status"),
                                })
                except Exception as e:
                    logger.error("[ES] data_streams fetch error: %s", e)

            results = results[:50]
            logger.debug("[ES] list_indices+streams final: count=%d names=%s",
                           len(results), [i["name"] for i in results])

            if not results:
                return {"success": True, "data": [], "total": total_raw, "error": None}

            return {"success": True, "data": results, "total": total_raw, "error": None}

        async def elasticsearch_get_documents(
            index: str,
            size: int = 10,
            sort_field: str = "@timestamp",
            sort_order: str = "desc",
        ) -> Dict[str, Any]:
            """Fetch the latest documents from an index or data stream without needing query DSL."""
            endpoint = f"{url}/{index}/_search"
            body: Dict[str, Any] = {
                "query": {"match_all": {}},
                "size": int(size) if isinstance(size, str) else size,
            }
            # Only add sort if the field exists — use try/ignore pattern
            body["sort"] = [{sort_field: {"order": sort_order, "unmapped_type": "date"}}]
            logger.debug("[ES] POST %s (get_documents size=%s sort=%s:%s)", endpoint, size, sort_field, sort_order)
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(endpoint, headers=req_headers, content=json.dumps(body))
                logger.debug("[ES] POST %s -> HTTP %d | body[:500]: %s",
                               endpoint, resp.status_code, resp.text[:500])
                if resp.status_code == 404:
                    return {"success": False, "data": None,
                            "error": f"Index or data stream '{index}' not found."}
                if resp.status_code not in (200, 201):
                    try:
                        err = resp.json().get("error", {})
                        root = err.get("root_cause", [{}])[0]
                        detail = f"{root.get('type','')}: {root.get('reason','')}"
                    except Exception:
                        detail = resp.text[:300]
                    return {"success": False, "data": None, "error": f"HTTP {resp.status_code}: {detail}"}
                hits = resp.json().get("hits", {})
                total = hits.get("total", {}).get("value", 0) if isinstance(hits.get("total"), dict) else hits.get("total", 0)
                docs = [h.get("_source", h) for h in hits.get("hits", [])]
                logger.debug("[ES] get_documents: total=%d returned=%d", total, len(docs))
                return {"success": True, "data": docs, "total": total, "error": None}
            except Exception as e:
                logger.error("[ES] get_documents error: %s", e)
                return {"success": False, "data": None, "error": str(e)}

        async def elasticsearch_list_data_streams(pattern: str = "*") -> Dict[str, Any]:
            """List Elasticsearch data streams, optionally filtered by pattern."""
            endpoint = f"{url}/_data_stream/{pattern}"
            logger.debug("[ES] GET %s (list data streams pattern=%s)", endpoint, pattern)
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get(endpoint, headers=headers)
                logger.debug("[ES] GET %s -> HTTP %d | body[:500]: %s",
                               endpoint, resp.status_code, resp.text[:500])
                if resp.status_code == 404:
                    return {"success": True, "data": [], "total": 0, "error": None}
                if resp.status_code != 200:
                    return {"success": False, "data": None, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
                raw = resp.json().get("data_streams", [])
                streams = [
                    {
                        "name": s.get("name"),
                        "status": s.get("status"),
                        "backing_indices": len(s.get("indices", [])),
                        "hidden": s.get("hidden", False),
                        "template": s.get("template"),
                        "ilm_policy": s.get("ilm_policy"),
                    }
                    for s in raw
                    if not s.get("hidden", False)
                ]
                logger.debug("[ES] data streams found: %d names=%s",
                               len(streams), [s["name"] for s in streams[:20]])
                return {"success": True, "data": streams, "total": len(raw), "error": None}
            except Exception as e:
                logger.error("[ES] list_data_streams error: %s", e)
                return {"success": False, "data": None, "error": str(e)}

        async def elasticsearch_resolve_index(pattern: str) -> Dict[str, Any]:
            """Resolve which actual indices/data streams a wildcard pattern expands to in Elasticsearch.
            Use this to diagnose why a search returns 0 results — shows the exact index list ES would search."""
            endpoint = f"{url}/_resolve/index/{pattern}"
            logger.debug("[ES] GET %s (resolve index pattern)", endpoint)
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(endpoint, headers=headers,
                                            params={"expand_wildcards": "open,hidden,all"})
                logger.debug("[ES] GET %s -> HTTP %d | body[:1000]: %s",
                               endpoint, resp.status_code, resp.text[:1000])
                if resp.status_code != 200:
                    return {"success": False, "data": None, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
                body = resp.json()
                indices   = [i.get("name") for i in body.get("indices", [])]
                aliases   = [a.get("name") for a in body.get("aliases", [])]
                streams   = [s.get("name") for s in body.get("data_streams", [])]
                result = {
                    "pattern": pattern,
                    "indices": indices[:30],
                    "aliases": aliases[:10],
                    "data_streams": streams[:30],
                    "total_indices": len(indices),
                    "total_data_streams": len(streams),
                }
                logger.debug("[ES] resolve result: %s", result)
                return {"success": True, "data": result, "total": len(indices) + len(streams), "error": None}
            except Exception as e:
                logger.error("[ES] resolve error: %s", e)
                return {"success": False, "data": None, "error": str(e)}

        async def elasticsearch_get_mapping(index: str) -> Dict[str, Any]:
            """Get field mappings for an index or data stream to discover available field names and types."""
            endpoint = f"{url}/{index}/_mapping"
            logger.debug("[ES] GET %s (mapping discovery)", endpoint)
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get(endpoint, headers=headers)
                logger.debug("[ES] GET %s -> HTTP %d", endpoint, resp.status_code)
                if resp.status_code == 404:
                    return {"success": False, "data": None, "error": f"Index '{index}' not found."}
                if resp.status_code != 200:
                    return {"success": False, "data": None, "error": f"HTTP {resp.status_code}"}
                body = resp.json()
                # Flatten all field names and types across all indices in the pattern
                fields: Dict[str, str] = {}
                for idx_data in body.values():
                    mappings = idx_data.get("mappings", {})
                    def _extract(props: dict, prefix: str = "") -> None:
                        for fname, fdata in props.items():
                            full = f"{prefix}{fname}"
                            ftype = fdata.get("type", "object")
                            fields[full] = ftype
                            nested = fdata.get("properties") or fdata.get("fields")
                            if nested:
                                _extract(nested, f"{full}.")
                    _extract(mappings.get("properties", {}))
                    break  # one index mapping is enough for pattern discovery
                # Return only fields relevant to log analysis (cap at 80)
                log_fields = {k: v for k, v in fields.items()
                              if any(kw in k for kw in ("kubernetes", "message", "log", "timestamp", "namespace", "pod", "container", "level", "severity", "stream"))}
                summary = dict(list(log_fields.items())[:80]) or dict(list(fields.items())[:80])
                return {"success": True, "data": summary, "total": len(fields), "error": None}
            except Exception as e:
                logger.error("[ES] mapping fetch error: %s", e)
                return {"success": False, "data": None, "error": str(e)}

        return {
            "elasticsearch_get_documents": {
                "function": elasticsearch_get_documents,
                "description": (
                    "Fetch the latest documents from an Elasticsearch index or data stream. "
                    "No query DSL needed — just provide the index/stream name and how many docs you want. "
                    "index: name or pattern e.g. 'logs-myapp-default', 'filebeat-*'. "
                    "size: number of documents to return (default 10). "
                    "sort_field: field to sort by (default @timestamp). "
                    "sort_order: 'desc' for newest first (default), 'asc' for oldest first."
                ),
                "inputs": ["index", "size", "sort_field", "sort_order"],
                "operation_type": "read",
                "requires_confirmation": False,
            },
            "elasticsearch_search": {
                "function": elasticsearch_search,
                "description": (
                    "Search Elasticsearch using Query DSL. Works on indices and data streams. "
                    "index: index pattern e.g. 'logs-*', 'filebeat-*'. "
                    "query_json: valid JSON string with double quotes. "
                    "ALWAYS use field-scoped query_string for pod/namespace/container filters — "
                    'pod name filter: {"query_string":{"query":"kubernetes.pod.name:*myapp* AND kubernetes.namespace:*uat34*"}} '
                    "NOT a bare term or default_field. "
                    "size: max results (default 20)."
                ),
                "inputs": ["index", "query_json", "size"],
                "operation_type": "read",
                "requires_confirmation": False,
            },
            "elasticsearch_list_indices": {
                "function": elasticsearch_list_indices,
                "description": (
                    "List available Elasticsearch indices AND data streams with document count and size. "
                    "Returns both regular indices (type=index) and data streams (type=data_stream). "
                    "Use to discover which indices/streams contain logs before querying. "
                    "Both types are searchable with elasticsearch_search using the same name as index pattern."
                ),
                "inputs": [],
                "operation_type": "read",
                "requires_confirmation": False,
            },
            "elasticsearch_resolve_index": {
                "function": elasticsearch_resolve_index,
                "description": (
                    "Resolve which actual indices and data streams a wildcard pattern expands to. "
                    "Use when elasticsearch_search returns 0 results unexpectedly — "
                    "this shows you exactly what ES would search for a given pattern. "
                    "pattern: index pattern e.g. 'logs-*', '*', 'filebeat-*'."
                ),
                "inputs": ["pattern"],
                "operation_type": "read",
                "requires_confirmation": False,
            },
            "elasticsearch_list_data_streams": {
                "function": elasticsearch_list_data_streams,
                "description": (
                    "List all Elasticsearch data streams (modern log/metric storage format used by Elastic Agent, Fleet, APM). "
                    "Returns name, status (GREEN/YELLOW/RED), backing index count, ILM policy. "
                    "Optionally filter by pattern e.g. 'logs-*', 'metrics-*', 'traces-*'. "
                    "Data streams are searchable with elasticsearch_search using their name as the index parameter."
                ),
                "inputs": ["pattern"],
                "operation_type": "read",
                "requires_confirmation": False,
            },
            "elasticsearch_get_mapping": {
                "function": elasticsearch_get_mapping,
                "description": (
                    "Get field names and types for an Elasticsearch index or pattern. "
                    "Call this when a search returns 0 results to verify the correct field names. "
                    "Returns relevant fields (kubernetes.*, message, log.*, @timestamp etc). "
                    "index: exact index name or pattern e.g. 'logs-*', 'filebeat-8.14.1'."
                ),
                "inputs": ["index"],
                "operation_type": "read",
                "requires_confirmation": False,
            },
        }
