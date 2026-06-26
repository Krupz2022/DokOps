# OpenAI-Compatible Endpoint

DokOps exposes a **drop-in replacement for the OpenAI chat API**. This lets you point any OpenAI-compatible tool (LangChain, LlamaIndex, Continue.dev, Open WebUI, the official OpenAI SDKs, custom scripts) at DokOps and have the DokOps AI — with full cluster access — answer.

> **Important — exact paths.** This router is mounted at `/v1` (not under `/api/v1`). The two endpoints are:
> - `POST /v1/chat/completions`
> - `GET /v1/models`
>
> So the OpenAI "base URL" you configure in tools is `http://localhost:8000/v1`.

---

## Authentication & enabling

This endpoint does **not** use your normal login token. It uses a dedicated **OpenAI-compatible API key** (prefixed `dokops_`), and the feature must be turned on.

1. Enable it: `PATCH /api/v1/system/openai-compat` with `{"enabled": true}` (or use the Settings page).
2. Generate a key: `POST /api/v1/system/openai-compat/regenerate-key` — the key is shown **once**.
3. Send the key as a Bearer token: `Authorization: Bearer dokops_your_key_here`.

If the feature is disabled you get `403`; a missing/wrong key gives `401`. Errors are returned in OpenAI's error format: `{"error": {"message": "...", "type": "...", "code": null}}`.

---

## GET /v1/models

**What this does:** Lists the available "models" — always just one, `dokops`. (Provided so OpenAI clients that probe `/models` work.)

**Auth required?** OpenAI-compat API key.

```bash
curl -H "Authorization: Bearer dokops_your_key_here" \
  http://localhost:8000/v1/models
```

**Example response (200):**

```json
{
  "object": "list",
  "data": [
    { "id": "dokops", "object": "model", "created": 0, "owned_by": "dokops" }
  ]
}
```

---

## POST /v1/chat/completions

**What this does:** Sends a chat message and gets the DokOps AI's answer back in OpenAI format. The AI can inspect your cluster while answering.

**Auth required?** OpenAI-compat API key.

**Request body** (JSON — OpenAI chat-completions shape):

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `model` | string | no | `dokops` | Ignored; DokOps always uses its configured provider. |
| `messages` | array | yes | – | The conversation. Each item is `{"role": "user"\|"assistant"\|"system", "content": "..."}`. |
| `stream` | boolean | no | `false` | `true` to stream the answer back token-by-token (SSE). |
| `temperature` | number | no | – | Accepted for compatibility. |
| `max_tokens` | integer | no | – | Accepted for compatibility. |

**Choosing a cluster:** add a system message containing `cluster_id: <name>` (or `cluster_name: <name>`). The hint is stripped before the AI sees your text. If no cluster is active and you give no hint, you get a `400` asking you to set one.

**curl example (non-streaming):**

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer dokops_your_key_here" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "dokops",
    "messages": [
      {"role": "system", "content": "cluster_id: prod-cluster"},
      {"role": "user", "content": "What pods are failing?"}
    ],
    "stream": false
  }'
```

**Example response (200):**

```json
{
  "id": "chatcmpl-abc123...",
  "object": "chat.completion",
  "created": 1748189000,
  "model": "dokops",
  "choices": [
    {
      "index": 0,
      "message": { "role": "assistant", "content": "Two pods are failing: ..." },
      "finish_reason": "stop"
    }
  ],
  "usage": { "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0 }
}
```

> Note: the `usage` token counts are returned as `0` by this endpoint.

**Streaming (`"stream": true`):** the response is Server-Sent Events. Progress steps are sent as SSE **comment** lines (`: Listing pods...`) and the answer arrives as `data: {chat.completion.chunk}` lines, ending with `data: [DONE]`.

```bash
curl -N -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer dokops_your_key_here" \
  -H "Content-Type: application/json" \
  -d '{"model":"dokops","messages":[{"role":"user","content":"Check cluster health"}],"stream":true}'
```

```
: Listing pods in all namespaces...
data: {"id":"chatcmpl-...","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"Checking"},"finish_reason":null}]}
data: {"id":"chatcmpl-...","choices":[{"index":0,"delta":{"content":" cluster"},"finish_reason":null}]}
data: {"id":"chatcmpl-...","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}
data: [DONE]
```

**Common errors:**

| Code | Meaning |
|------|---------|
| `401` | Missing or invalid OpenAI-compat API key. |
| `403` | The OpenAI-compatible API is disabled. Enable it in System settings. |
| `400` | No user message found, or no active cluster and no `cluster_id:` hint, or the named cluster wasn't found. |

---

## Using it from popular tools

**Python OpenAI SDK:**

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="dokops_your_key_here")
resp = client.chat.completions.create(
    model="dokops",
    messages=[
        {"role": "system", "content": "cluster_id: prod-cluster"},
        {"role": "user", "content": "List all CrashLoopBackOff pods"},
    ],
)
print(resp.choices[0].message.content)
```

**LangChain:**

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(base_url="http://localhost:8000/v1", api_key="dokops_your_key_here", model="dokops")
print(llm.invoke("What pods are failing in production?").content)
```

**Continue.dev** (`~/.continue/config.json`):

```json
{
  "models": [
    { "title": "DokOps (K8s AI)", "provider": "openai", "model": "dokops",
      "apiBase": "http://localhost:8000/v1", "apiKey": "dokops_your_key_here" }
  ]
}
```

**Open WebUI:** Settings → Connections → OpenAI → API Base `http://localhost:8000/v1`, API Key `dokops_your_key_here`, Model `dokops`.

---

## Notes

- The `model` field is ignored — DokOps always uses its configured AI provider.
- The AI has full read access to your cluster via its tools while answering.
- System messages are forwarded as extra context (with any `cluster_id:` hint removed first).
- Multi-turn conversations work via the `messages` array, but this endpoint does **not** save conversations. For persistent threads use the [Chat](./chat.md) endpoints.
