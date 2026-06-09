# OpenAI-Compatible Endpoint

DokOps exposes a drop-in replacement for the OpenAI chat completions API. This lets you use DokOps as a backend for any tool that supports OpenAI — including LangChain, LlamaIndex, Continue.dev, Open WebUI, and custom scripts.

---

## Endpoint

```
POST /api/openai/v1/chat/completions
```

This endpoint accepts requests in the exact same format as OpenAI's `POST /v1/chat/completions`.

---

## Authentication

Generate an API key from **Admin** → **Settings** → **OpenAI-Compatible API**:

1. Click **Settings** in the sidebar.
2. Find the **OpenAI-Compatible API** section.
3. Click **Generate Key** — a key prefixed `dokops_` is created.
4. Copy the key — it's shown only once.

Use the key as a Bearer token:

```
Authorization: Bearer dokops_abc123...
```

---

## Configuration

From the Settings page, you can configure:

- **Enable/disable** the endpoint
- **Rate limiting** (requests per minute)
- **Regenerate key** if compromised

---

## Example: Direct API Call

```bash
KEY="dokops_your_key_here"

curl -X POST http://localhost:8000/api/openai/v1/chat/completions \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "dokops",
    "messages": [
      {
        "role": "user",
        "content": "What pods are failing in my cluster?"
      }
    ],
    "stream": false
  }'

# Response (OpenAI format)
{
  "id": "chatcmpl-abc123",
  "object": "chat.completion",
  "created": 1748189000,
  "model": "dokops",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "I checked your cluster and found the following failing pods..."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 120,
    "completion_tokens": 350,
    "total_tokens": 470
  }
}
```

---

## Streaming

```bash
curl -X POST http://localhost:8000/api/openai/v1/chat/completions \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "dokops",
    "messages": [{"role": "user", "content": "Check cluster health"}],
    "stream": true
  }'

# Streaming response (SSE chunks)
data: {"id":"chatcmpl-...","choices":[{"delta":{"content":"Checking"},"index":0}]}
data: {"id":"chatcmpl-...","choices":[{"delta":{"content":" cluster"},"index":0}]}
...
data: [DONE]
```

---

## Using with LangChain

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    base_url="http://localhost:8000/api/openai/v1",
    api_key="dokops_your_key_here",
    model="dokops",
)

response = llm.invoke("What pods are failing in the production namespace?")
print(response.content)
```

---

## Using with Continue.dev (VS Code)

In your Continue config (`~/.continue/config.json`):

```json
{
  "models": [
    {
      "title": "DokOps (K8s AI)",
      "provider": "openai",
      "model": "dokops",
      "apiBase": "http://localhost:8000/api/openai/v1",
      "apiKey": "dokops_your_key_here"
    }
  ]
}
```

Now you can ask DokOps questions directly from VS Code.

---

## Using with Open WebUI

1. In Open WebUI, go to **Settings** → **Connections** → **OpenAI**.
2. Set API Base: `http://localhost:8000/api/openai/v1`
3. Set API Key: `dokops_your_key_here`
4. Set Model: `dokops`
5. Save — DokOps appears as a model in Open WebUI.

---

## Using with Python OpenAI SDK

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/api/openai/v1",
    api_key="dokops_your_key_here",
)

response = client.chat.completions.create(
    model="dokops",
    messages=[
        {"role": "system", "content": "You are a Kubernetes expert."},
        {"role": "user", "content": "List all CrashLoopBackOff pods"}
    ]
)

print(response.choices[0].message.content)
```

---

## Notes

- The `model` field in requests is ignored — DokOps always uses its configured AI provider.
- The AI has full access to your cluster via the K8s tools during the response.
- System messages are forwarded to the AI as additional context.
- Conversation history (multi-turn) is supported via the `messages` array.
- The endpoint does not persist conversations to the database — use `/api/v1/chat` for persistent conversations.
