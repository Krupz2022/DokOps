# RAG (Knowledge Base)

RAG stands for "Retrieval-Augmented Generation" — (in plain terms) it's a way to feed the AI your own documents so it can answer using your internal knowledge. These endpoints upload documents and connect Confluence.

> **Shared note:** All endpoints require a token (any logged-in user), except the Confluence **config save** and **test** which are admin-only.

---

## GET /api/v1/rag/documents

**What this does:** Lists documents that have been added to the knowledge base.

**Auth required?** Token.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/rag/documents
```

**Example response (200):** array of `{ "id": "doc_1", "title": "Runbook: DB outage", "source": "upload", "chunks": 14 }`.

---

## DELETE /api/v1/rag/documents/{doc_id}

**What this does:** Removes a document from the knowledge base.

**Auth required?** Token. **Path:** `doc_id` (string, required).

```bash
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/rag/documents/doc_1
```

**Example response (200):** `{ "status": "deleted" }`

---

## POST /api/v1/rag/ingest/upload

**What this does:** Uploads a file (PDF, markdown, text, etc.) into the knowledge base.

**Auth required?** Token.

**Request body** (`multipart/form-data`):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `file` | file | yes | The document to ingest. |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -F "file=@/home/me/runbook.pdf" \
  http://localhost:8000/api/v1/rag/ingest/upload
```

**Example response (200):** `{ "job_id": "job_123", "status": "processing" }` — track progress with `GET /rag/jobs/{job_id}`.

---

## POST /api/v1/rag/ingest/url

**What this does:** Ingests a web page by its URL.

**Auth required?** Token.

**Request body** (JSON):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `url` | string | yes | The page to fetch and ingest. |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/rag/ingest/url \
  -d '{"url":"https://docs.example.com/runbook"}'
```

**Example response (200):** `{ "job_id": "job_124", "status": "processing" }`

---

## POST /api/v1/rag/ingest/runbooks

**What this does:** Ingests the built-in/local runbooks into the knowledge base in one go.

**Auth required?** Token. No body.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/rag/ingest/runbooks
```

**Example response (200):** `{ "status": "started", "count": 5 }`

---

## GET /api/v1/rag/jobs/{job_id}

**What this does:** Checks the progress/status of an ingest job started above.

**Auth required?** Token. **Path:** `job_id` (string, required).

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/rag/jobs/job_123
```

**Example response (200):** `{ "id": "job_123", "status": "completed", "chunks": 14 }`

---

## POST /api/v1/rag/test-connection

**What this does:** Tests the connection to the vector store / embeddings backend used by RAG.

**Auth required?** Token. No body.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/rag/test-connection
```

**Example response (200):** `{ "success": true }`

---

## GET /api/v1/rag/confluence/config

**What this does:** Shows the saved Confluence connection settings (secrets masked).

**Auth required?** Token.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/rag/confluence/config
```

**Example response (200):** `{ "base_url": "https://acme.atlassian.net/wiki", "instance_type": "cloud", "configured": true }`

---

## POST /api/v1/rag/confluence/config

**What this does:** Saves Confluence connection settings so DokOps can ingest your wiki.

**Auth required?** Admin / Superuser.

**Request body** (JSON):

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `instance_type` | string | no | `cloud` | `cloud` or `server`/`datacenter`. |
| `base_url` | string | yes | – | Your Confluence base URL. |
| `email` | string | no | – | Account email (Cloud). |
| `username` | string | no | – | Username (Server). |
| `api_token` | string | no | – | API token / password. |
| `sync_spaces` | array of strings | no | `[]` | Space keys to auto-sync. |
| `sync_interval_hours` | integer | no | `24` | How often to re-sync. |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/rag/confluence/config \
  -d '{"base_url":"https://acme.atlassian.net/wiki","email":"me@acme.com","api_token":"...","sync_spaces":["OPS"]}'
```

**Example response (200):** `{ "status": "saved" }`

---

## POST /api/v1/rag/confluence/test

**What this does:** Tests the saved Confluence credentials.

**Auth required?** Admin / Superuser. No body.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/rag/confluence/test
```

**Example response (200):** `{ "success": true }`

---

## POST /api/v1/rag/ingest/confluence/space

**What this does:** Ingests an entire Confluence space (all its pages) into the knowledge base.

**Auth required?** Token.

**Request body** (JSON):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `space_key` | string | yes | The Confluence space key (e.g. `OPS`). |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/rag/ingest/confluence/space \
  -d '{"space_key":"OPS"}'
```

**Example response (200):** `{ "job_id": "job_200", "status": "processing" }`

---

## POST /api/v1/rag/ingest/confluence/page

**What this does:** Ingests a single Confluence page by its URL.

**Auth required?** Token.

**Request body** (JSON):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `url` | string | yes | The Confluence page URL. |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/rag/ingest/confluence/page \
  -d '{"url":"https://acme.atlassian.net/wiki/spaces/OPS/pages/123/Runbook"}'
```

**Example response (200):** `{ "job_id": "job_201", "status": "processing" }`
