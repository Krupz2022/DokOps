# Knowledge Sources

Knowledge Sources lets you connect existing external knowledge stores to DokOps. The AI queries them automatically during every conversation — no ingestion, no indexing, no duplication of your data.

This is different from the [Knowledge Base](knowledge-base.md), which ingests and stores documents locally in ChromaDB. Knowledge Sources connect to stores you already own and retrieve from them live.

---

## Supported Providers

| Provider | Type | Multi-index |
|----------|------|-------------|
| **Azure AI Search** | Full-text / semantic | Yes — comma-separated index names |
| **Qdrant** | Vector | Yes — comma-separated collection names |
| **Pinecone** | Vector | Single index host per source |
| **Weaviate** | Vector + GraphQL nearText | Yes — comma-separated collection names |
| **OpenSearch** | Full-text (BM25) | Yes — native comma-joined index URL |
| **Chroma** | Vector + text | Yes — comma-separated collection names |

---

## Adding a Source

1. Go to **Knowledge Sources** in the sidebar.
2. Click **+ Add Source**.
3. Select a **Provider** from the dropdown.
4. Fill in the connection fields (endpoint, API key, index/collection name).
5. Click **Test Connection** to verify before saving.
6. Click **Save**.

Sources are enabled by default. Use the toggle on any source card to pause retrieval without deleting the connection.

---

## Provider Configuration

### Azure AI Search

| Field | Description |
|-------|-------------|
| Endpoint URL | `https://your-search.search.windows.net` |
| API Key | Azure AI Search admin or query key |
| Index Name(s) | One or more index names, comma-separated (e.g. `company-kb, ops-kb`) |
| Top-K Results | Number of chunks to retrieve per query (default: 3) |
| Semantic Config | Optional — name of a semantic configuration for semantic ranking |

### Qdrant

> Requires the DokOps embedding service to be configured (Settings → AI → Embedding).

| Field | Description |
|-------|-------------|
| Endpoint URL | `https://xyz.qdrant.tech` or self-hosted URL |
| API Key | Qdrant API key |
| Collection Name(s) | One or more collection names, comma-separated |
| Text Field | Payload field containing the document text (default: `content`) |
| Top-K Results | Vectors returned per collection per query (default: 3) |

### Pinecone

> Requires the DokOps embedding service to be configured (Settings → AI → Embedding).

| Field | Description |
|-------|-------------|
| Index Host | Full index URL, e.g. `https://my-index-xyz.svc.pinecone.io` |
| API Key | Pinecone API key |
| Namespace | Optional — leave blank for the default namespace |
| Metadata Text Field | Metadata key holding document text (default: `text`) |
| Top-K Results | Vectors returned per query (default: 3) |

### Weaviate

| Field | Description |
|-------|-------------|
| Endpoint URL | `https://my-cluster.weaviate.network` or self-hosted URL |
| API Key | Weaviate API key |
| Collection Name(s) | One or more Weaviate class names, comma-separated (e.g. `CompanyDocs, OpsKB`) |
| Text Property | Property name containing document text (default: `content`) |
| Top-K Results | Objects returned per collection per query (default: 3) |

### OpenSearch

| Field | Description |
|-------|-------------|
| Endpoint URL | `https://my-opensearch.example.com` |
| Username | OpenSearch username |
| Password | OpenSearch password |
| Index Name(s) | One or more index names, comma-separated (e.g. `company-kb, ops-kb`) |
| Text Field | Field to match and return (default: `content`) |
| Top-K Results | Hits returned per query (default: 3) |

OpenSearch uses BM25 full-text matching. Multiple index names are passed natively as a comma-joined URL (`/kb1,kb2/_search`) — one request covers all indexes.

### Chroma

| Field | Description |
|-------|-------------|
| Endpoint URL | `http://chroma-host:8000` |
| API Token | Optional — leave blank if auth is disabled |
| Collection Name(s) | One or more collection names, comma-separated |
| Top-K Results | Documents returned per collection per query (default: 3) |

Chroma collection names are resolved to UUIDs at query time. Each collection name results in one UUID-lookup call followed by one query call.

---

## Multi-Index / Multi-Collection Queries

For all providers that support it, enter multiple index or collection names in one field, separated by commas:

```
company-kb, ops-kb, incident-history
```

DokOps queries all named indexes in **parallel** using `asyncio.gather` and merges the results before injecting them into the AI's context. This means latency is bounded by the slowest index, not the sum of all.

---

## Embedding Requirement for Vector Providers

Qdrant and Pinecone are vector-only stores — they require a pre-computed query vector. DokOps automatically embeds the user's query using the embedding service configured in **Settings → AI**. If no embedding service is configured, vector provider sources are skipped for that query with a warning in the logs.

The other four providers (Azure AI Search, Weaviate, OpenSearch, Chroma) accept text queries directly — no embedding service required.

---

## How the AI Uses Knowledge Sources

Every time you send a message in AI Chat:

1. DokOps fetches all enabled Knowledge Sources from the database.
2. If any vector provider is present, the query is embedded once (reused across all vector sources).
3. All sources are queried **in parallel** — the total overhead is the latency of the slowest source, not the sum.
4. Retrieved chunks are injected into the AI's system prompt as:

```xml
<retrieved_document index="1" source="Ops Wiki (azure_ai_search)">
... document content ...
</retrieved_document>
```

5. The AI treats this context as authoritative and cites it in its response.

Failures from individual sources are isolated — if one source is unreachable, the others still contribute context and the AI continues normally.

---

## Security

- All API keys, passwords, and tokens are encrypted at rest using Fernet symmetric encryption before storage.
- Secret fields are masked as `••••••` in all API responses and the UI — they are never returned in plaintext after saving.
- All external endpoint URLs are validated through the SSRF guard before any HTTP request is made. Private IP ranges are blocked unless `ALLOW_PRIVATE_CLUSTER_IPS=true` is set.
- Only **Admin** users can create, edit, delete, or test Knowledge Sources. Any user can trigger retrieval via AI Chat.

---

## API Reference

All endpoints are under `/api/v1/knowledge-sources`.

```bash
# List all sources (masks secrets)
GET /api/v1/knowledge-sources

# Create a source
POST /api/v1/knowledge-sources
{
  "name": "Ops Wiki",
  "provider": "azure_ai_search",
  "config": {
    "endpoint": "https://ops.search.windows.net",
    "api_key": "...",
    "index_name": "company-kb, ops-kb",
    "top_k": 5
  }
}

# Test a config before saving
POST /api/v1/knowledge-sources/test-config
{
  "provider": "opensearch",
  "config": { "endpoint": "...", "username": "...", "password": "...", "index_name": "kb" }
}

# Test an existing saved source
POST /api/v1/knowledge-sources/{source_id}/test

# Update a source
PUT /api/v1/knowledge-sources/{source_id}

# Enable / disable a source
PATCH /api/v1/knowledge-sources/{source_id}/toggle
{ "enabled": false }

# Delete a source
DELETE /api/v1/knowledge-sources/{source_id}
```

---

## Differences from the Knowledge Base

| | Knowledge Base | Knowledge Sources |
|---|---|---|
| **Data location** | Stored locally in ChromaDB | Stays in your own store |
| **Ingestion** | You upload / ingest documents | No ingestion — retrieve-only |
| **Indexing** | DokOps creates embeddings | Your store handles indexing |
| **Best for** | Runbooks, ad-hoc docs, small sets | Large existing stores (Confluence exports, Elastic indexes, Qdrant clusters) |
| **Providers** | ChromaDB only | Azure AI Search, Qdrant, Pinecone, Weaviate, OpenSearch, Chroma |
