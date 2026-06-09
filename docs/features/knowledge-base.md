# Knowledge Base (RAG)

The Knowledge Base allows you to give the AI long-term memory by ingesting documents into a **ChromaDB vector store**. The AI automatically retrieves relevant documents as context before answering your questions — this is called Retrieval-Augmented Generation (RAG).

---

## What to Store in the Knowledge Base

The knowledge base is most useful for:

- **Internal runbooks and playbooks** (Markdown or PDF)
- **Architecture documents** (how your services connect)
- **Post-incident reports** (so the AI learns from past failures)
- **SLO/SLA documents** (so the AI understands your reliability targets)
- **Custom tool documentation** (CLI tools, scripts)
- **Team knowledge base exports** (Confluence, Notion, etc.)

---

## Adding Documents

Go to **Knowledge Base** in the sidebar.

### Option 1 — Upload a File

1. Click **Upload Document**.
2. Select a `.md`, `.txt`, `.pdf`, or `.docx` file.
3. Give it a title (auto-detected from filename if omitted).
4. Click **Ingest** — DokOps chunks the document and stores embeddings in ChromaDB.

### Option 2 — Ingest from URL

1. Click **Ingest from URL**.
2. Paste a URL (internal or external documentation page).
3. DokOps fetches the page content and ingests it.

> **SSRF Protection**: DokOps validates URLs before fetching. Private IP ranges (`10.0.0.0/8`, `192.168.0.0/16`, `172.16.0.0/12`, `169.254.0.0/16`) are blocked unless `ALLOW_PRIVATE_CLUSTER_IPS=true` is set.

### Option 3 — Ingest All Runbooks

Click **Ingest Runbooks** to bulk-ingest all Markdown files from `backend/app/runbooks/` at once. Useful after writing custom runbooks.

### Option 4 — Confluence (Cloud or Server/DC)

Connect your Confluence instance to sync pages directly into the knowledge base.

#### Connecting Confluence

1. Go to **Knowledge Base** → **Confluence** tab.
2. Fill in:

| Field | Description |
|-------|-------------|
| **Base URL** | Your Confluence URL (e.g. `https://mycompany.atlassian.net` or `https://wiki.example.com`) |
| **Instance Type** | `cloud` (Atlassian Cloud) or `server` (Server/Data Center) |
| **Email / Username** | Your Atlassian account email (Cloud) or Confluence username (Server) |
| **API Token / Password** | API token (Cloud) or password/PAT (Server) |

3. Click **Test Connection** — DokOps verifies credentials before saving.
4. Click **Save**.

#### Syncing Content

- **Sync Space** — enter a space key (e.g. `OPS`) to bulk-ingest all pages in that space.
- **Sync Page** — paste the full Confluence page URL to ingest a single page.
- **Scheduled Sync** — set a cron expression on the Confluence config card to keep the knowledge base in sync automatically (e.g. `0 3 * * *` for nightly).

Confluence page content (including child pages) is extracted from Confluence's Storage Format XML and cleaned to plain text before chunking and embedding.

---

### Background Ingest & Job Tracking

File uploads and URL ingestion run in the background — the API returns a `job_id` immediately so the browser is never blocked:

```json
{
  "job_id": "4f2e1a9c",
  "status": "queued",
  "title": "Redis Connection Triage"
}
```

Poll `GET /api/v1/rag/jobs/{job_id}` to track progress:

```json
{"status": "running", "progress": "embedding chunk 12/48"}
{"status": "done", "doc_id": 17}
{"status": "error", "detail": "Unsupported file type"}
```

The Knowledge Base page polls automatically and shows a progress indicator in the document list.

> **Chunk limit removed**: URL ingestion no longer has a hard 25-chunk cap. Large pages are fully ingested up to the provider's token limit.

---

### Via API

```bash
# Upload a file (returns job_id)
curl -X POST http://localhost:8000/api/v1/rag/ingest/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@my-runbook.md" \
  -F "title=Redis Connection Triage"

# Ingest from URL (returns job_id)
curl -X POST http://localhost:8000/api/v1/rag/ingest/url \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://wiki.example.com/on-call-guide", "title": "On-Call Guide"}'

# Poll job status
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/rag/jobs/{job_id}
```

---

## Viewing Documents

The Knowledge Base page lists all ingested documents with:
- Title
- Source type (file upload, URL, runbook)
- Ingestion date
- Character count

Click any document to preview its content.

---

## Deleting Documents

Click the trash icon next to any document to remove it from the knowledge base. This deletes both the database record and the ChromaDB embedding.

---

## How the AI Uses the Knowledge Base

When you ask a question in AI Chat, the AI:

1. Generates an embedding for your question.
2. Queries ChromaDB for the top-N most similar document chunks.
3. Includes those chunks as additional context in the prompt.
4. Answers using both its training knowledge and your documents.

The AI signals when it's using knowledge base content:

```
User: "What's our procedure when Redis is down?"

AI: Based on your 'Redis Connection Triage' runbook in the knowledge base:

    Step 1: Check if the Redis pod is running...
    Step 2: Check for recent config changes...
    ...
```

---

## ChromaDB Configuration

The knowledge base always connects to a ChromaDB server. Configure via environment variables or **Settings → Knowledge Base**:

```env
DOKOPS_RAG_CHROMA_HOST=chroma.internal
DOKOPS_RAG_CHROMA_PORT=8000
```

The Helm 4-service chart includes a ChromaDB deployment configured automatically. For local development, the `docker-compose.yml` starts ChromaDB alongside the backend.
