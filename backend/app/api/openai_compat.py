import hashlib
import hmac
import json
import re
import time
import uuid
from typing import AsyncGenerator, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api import deps
from app.models.setting import SystemSetting
from app.services.ai_service import ai_service
from app.services.k8s_service import k8s_service

router = APIRouter()

_CLUSTER_RE = re.compile(r"cluster[_\s]*(id|name)?\s*[:=]\s*(\S+)", re.IGNORECASE)


# ── Settings helpers ───────────────────────────────────────────────────────────

def _get_setting(key: str, db: Session) -> Optional[str]:
    row = db.exec(select(SystemSetting).where(SystemSetting.key == key)).first()
    return row.value if row else None


# ── Auth + enable checks ───────────────────────────────────────────────────────

def _oa_error(message: str, error_type: str, status: int) -> HTTPException:
    return HTTPException(
        status_code=status,
        detail={"error": {"message": message, "type": error_type, "code": None}},
    )


def _check_enabled(db: Session) -> None:
    if _get_setting("openai_compat_enabled", db) != "true":
        raise _oa_error("OpenAI-compatible API is disabled.", "server_error", 403)


def _validate_api_key(authorization: Optional[str], db: Session) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise _oa_error("Missing API key.", "authentication_error", 401)
    provided = authorization[len("Bearer "):]
    stored_hash = _get_setting("openai_compat_api_key_hash", db)
    if not stored_hash:
        raise _oa_error("No API key configured.", "authentication_error", 401)
    if not hmac.compare_digest(hashlib.sha256(provided.encode()).hexdigest(), stored_hash):
        raise _oa_error("Invalid API key.", "authentication_error", 401)


# ── Cluster resolution ─────────────────────────────────────────────────────────

def _extract_cluster_hint(messages: List["OAMessage"]) -> Optional[str]:
    for msg in messages:
        if msg.role == "system":
            m = _CLUSTER_RE.search(msg.content)
            if m:
                return m.group(2)
    return None


def _strip_cluster_hint(content: str) -> str:
    return _CLUSTER_RE.sub("", content).strip()


def _resolve_cluster(hint: Optional[str]) -> str:
    if hint:
        available = k8s_service.get_contexts()
        match = next((c for c in available if c == hint or c.lower() == hint.lower()), None)
        if not match:
            raise _oa_error(f"Cluster '{hint}' not found in DokOps.", "invalid_request_error", 400)
        return match
    if k8s_service.mock_mode:
        raise _oa_error(
            "No active cluster. Set an active cluster in DokOps or add 'cluster_id: X' to your system message.",
            "invalid_request_error",
            400,
        )
    return k8s_service.default_context


# ── Request / response models ──────────────────────────────────────────────────

class OAMessage(BaseModel):
    role: str
    content: str


class OAChatRequest(BaseModel):
    model: str = "dokops"
    messages: List[OAMessage]
    stream: bool = False
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


def _messages_to_query(messages: List[OAMessage]):
    """Returns (last_user_query: str, history: list) with cluster hint stripped from system messages."""
    history = []
    query = ""
    for msg in messages:
        if msg.role == "system":
            cleaned = _strip_cluster_hint(msg.content)
            if cleaned:
                history.append({"role": "system", "content": cleaned})
        else:
            if msg.role == "user":
                query = msg.content
            history.append({"role": msg.role, "content": msg.content})
    # Remove only the last user message (the query itself) from history
    for i in reversed(range(len(history))):
        if history[i]["role"] == "user" and history[i]["content"] == query:
            history = history[:i] + history[i + 1:]
            break
    return query, history


def _build_response(content: str, model: str) -> dict:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


# ── Agentic loop wrappers ──────────────────────────────────────────────────────

async def _collect_final_answer(query: str, context: str, history: list) -> str:
    final = ""
    async for event in ai_service.run_global_agentic_loop(query, context=context, history=history):
        if event.get("type") == "result":
            final = event.get("message", "")
    return final or "No answer produced."


async def _stream_oa_chunks(
    query: str, context: str, history: list, model: str
) -> AsyncGenerator[str, None]:
    cid = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    ts = int(time.time())
    async for event in ai_service.run_global_agentic_loop(query, context=context, history=history):
        msg = event.get("message", "")
        if not msg:
            continue
        event_type = event.get("type", "")
        if event_type == "step":
            # Emit as SSE comment so clients receive progress without it polluting content
            yield f": {msg}\n\n"
            continue
        chunk = {
            "id": cid,
            "object": "chat.completion.chunk",
            "created": ts,
            "model": model,
            "choices": [{"index": 0, "delta": {"content": msg}, "finish_reason": None}],
        }
        yield f"data: {json.dumps(chunk)}\n\n"
    done = {
        "id": cid,
        "object": "chat.completion.chunk",
        "created": ts,
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    yield f"data: {json.dumps(done)}\n\n"
    yield "data: [DONE]\n\n"


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("/models")
async def list_models(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(deps.get_db),
):
    _check_enabled(db)
    _validate_api_key(authorization, db)
    return {
        "object": "list",
        "data": [{"id": "dokops", "object": "model", "created": 0, "owned_by": "dokops"}],
    }


@router.post("/chat/completions")
async def chat_completions(
    request: OAChatRequest,
    authorization: Optional[str] = Header(None),
    db: Session = Depends(deps.get_db),
):
    _check_enabled(db)
    _validate_api_key(authorization, db)
    hint = _extract_cluster_hint(request.messages)
    cluster = _resolve_cluster(hint)
    query, history = _messages_to_query(request.messages)
    if not query:
        raise _oa_error("No user message found in messages.", "invalid_request_error", 400)
    if request.stream:
        return StreamingResponse(
            _stream_oa_chunks(query, cluster, history, request.model),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    content = await _collect_final_answer(query, cluster, history)
    return JSONResponse(_build_response(content, request.model))
