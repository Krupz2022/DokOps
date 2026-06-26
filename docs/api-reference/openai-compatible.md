# OpenAI-Compatible Endpoint

> **Moved & corrected.** The full, up-to-date documentation now lives at
> [**endpoints/openai-compatible.md**](./endpoints/openai-compatible.md).
>
> **Correction:** the real path is `POST /v1/chat/completions` and `GET /v1/models`
> (OpenAI base URL `http://localhost:8000/v1`) — verified against
> `backend/app/main.py` (`app.include_router(openai_compat_router, prefix="/v1")`).
> An earlier draft of this page used `/api/openai/v1/...`, which is **not** a real route.

DokOps exposes a drop-in replacement for the OpenAI chat completions API. This lets you use DokOps as a backend for any tool that supports OpenAI — including LangChain, LlamaIndex, Continue.dev, Open WebUI, and custom scripts.

See [endpoints/openai-compatible.md](./endpoints/openai-compatible.md) for:

- Exact paths and request/response shapes
- How to enable the feature and generate the `dokops_` API key
- Non-streaming and streaming examples
- Selecting a cluster via a `cluster_id:` system message
- Ready-to-paste configs for the OpenAI SDK, LangChain, Continue.dev, and Open WebUI
