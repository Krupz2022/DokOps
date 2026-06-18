# backend/app/api/v1/chat.py
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.core.datetimes import utcnow

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import deps
from app.models.chat import ChatConversation, ChatMessage
from app.models.user import User
from app.services.ai_service import ai_service
from app.core.db import AsyncSessionLocal
from app.core.token_context import set_token_context

router = APIRouter()


# ── Conversation CRUD ──────────────────────────────────────────────────────────

@router.post("/conversations")
async def create_conversation(
    current_user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_async_db),
) -> Any:
    conv = ChatConversation(user_id=current_user.id)
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return {"id": conv.id, "title": conv.title, "created_at": conv.created_at, "updated_at": conv.updated_at}


@router.get("/conversations")
async def list_conversations(
    current_user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_async_db),
) -> Any:
    convs = (await db.exec(
        select(ChatConversation)
        .where(ChatConversation.user_id == current_user.id)
        .order_by(ChatConversation.updated_at.desc())
    )).all()
    result = []
    for c in convs:
        msgs = (await db.exec(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == c.id)
            .order_by(ChatMessage.created_at.desc())
        )).all()
        preview = msgs[0].content[:80] if msgs else ""
        result.append({
            "id": c.id,
            "title": c.title,
            "updated_at": c.updated_at,
            "message_count": len(msgs),
            "preview": preview,
            "is_compacted": c.is_compacted,
            "total_tokens": sum(m.token_count for m in msgs),
        })
    return result


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    current_user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_async_db),
) -> Any:
    conv = await db.get(ChatConversation, conversation_id)
    if not conv or conv.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    msgs = (await db.exec(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.created_at.asc())
    )).all()
    return {
        "id": conv.id,
        "title": conv.title,
        "created_at": conv.created_at,
        "updated_at": conv.updated_at,
        "is_compacted": conv.is_compacted,
        "summary": conv.summary,
        "total_tokens": sum(m.token_count for m in msgs),
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "message_type": m.message_type,
                "created_at": m.created_at,
                "is_compacted": m.is_compacted,
            }
            for m in msgs
        ],
    }


@router.patch("/conversations/{conversation_id}")
async def rename_conversation(
    conversation_id: str,
    title: str = Body(..., embed=True),
    current_user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_async_db),
) -> Any:
    conv = await db.get(ChatConversation, conversation_id)
    if not conv or conv.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conv.title = title
    conv.updated_at = utcnow()
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return {"id": conv.id, "title": conv.title}


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    current_user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_async_db),
) -> Any:
    conv = await db.get(ChatConversation, conversation_id)
    if not conv or conv.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    msgs = (await db.exec(select(ChatMessage).where(ChatMessage.conversation_id == conversation_id))).all()
    for m in msgs:
        await db.delete(m)
    await db.flush()  # push message deletes to DB before removing parent
    await db.delete(conv)
    await db.commit()
    return {"status": "deleted"}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _event_to_message_type(event_type: str) -> str:
    mapping = {
        "step": "step",
        "result": "text",
        "pending_operation": "pending_op",
    }
    return mapping.get(event_type, "text")


async def _build_history(conversation_id: str, db: AsyncSession) -> List[Dict]:
    """Return last 6 non-compacted messages as OpenAI-style history dicts."""
    msgs = (await db.exec(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .where(ChatMessage.is_compacted == False)  # noqa: E712
        .order_by(ChatMessage.created_at.asc())
    )).all()
    # Only include user/assistant text messages — exclude step noise and pending_op cards
    history = []
    for m in msgs:
        if m.message_type == "text":
            history.append({"role": m.role, "content": m.content})
    return history[-12:]  # last 6 pairs


async def _maybe_compact(conversation_id: str) -> None:
    """Compact conversation if total tokens exceed the configured threshold."""
    from app.services.context_manager import context_manager, CONTEXT_WINDOWS

    provider = ai_service._get_setting("ai_provider") or "OPENAI"
    limit = CONTEXT_WINDOWS.get(provider, 32_000)
    threshold_pct = float(context_manager._get_setting("ctx_compaction_threshold") or "70") / 100
    threshold_tokens = int(limit * threshold_pct)

    async with AsyncSessionLocal() as db:
        msgs = (await db.exec(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conversation_id)
            .where(ChatMessage.is_compacted == False)  # noqa: E712
            .order_by(ChatMessage.created_at.asc())
        )).all()

        total_tokens = sum(m.token_count for m in msgs)
        if total_tokens <= threshold_tokens:
            return

        keep = int(context_manager._get_setting("ctx_keep_recent") or "6")
        to_compact = msgs[:-keep] if len(msgs) > keep else []
        if not to_compact:
            return

        all_messages = [
            {"role": m.role, "content": m.content or ""}
            for m in msgs  # full list, not just to_compact
        ]
        caching_client = ai_service._get_caching_client()
        _, summary = await context_manager.compact_conversation(
            all_messages, provider, caching_client
        )
        if not summary:
            return

        conv = await db.get(ChatConversation, conversation_id)
        if not conv:
            return

        kept_msgs = msgs[-keep:]
        kept_content = " ".join(m.content or "" for m in kept_msgs)
        after_tokens = context_manager.count_tokens(summary + kept_content, provider)
        conv.summary = summary
        conv.is_compacted = True
        conv.updated_at = utcnow()
        db.add(conv)

        for m in to_compact:
            m.is_compacted = True
            db.add(m)

        banner = ChatMessage(
            conversation_id=conversation_id,
            role="assistant",
            content=(
                f"Context compacted — Tokens before: {total_tokens:,} · "
                f"After: {after_tokens:,} · Saved: {total_tokens - after_tokens:,}"
            ),
            message_type="compaction_banner",
            token_count=0,
        )
        db.add(banner)
        await db.commit()


async def _maybe_index_incident(conversation_id: str, result_text: str) -> None:
    """Background-safe: index the full conversation thread into the RAG incidents collection.

    Indexes the complete user+AI dialogue (not just the final answer) so that
    specific facts found mid-conversation (e.g. correct port numbers, patch
    values, root-cause details) are preserved in the vector store and
    retrievable by future queries.
    """
    try:
        from app.services.rag_service import rag_service
        if not await rag_service.is_enabled():
            return
        async with AsyncSessionLocal() as db:
            conv = await db.get(ChatConversation, conversation_id)
            title = conv.title if conv else conversation_id

            # Build a full dialogue transcript for richer retrieval.
            # Include "step" messages (tool outputs) so that raw resource data
            # such as configmap contents, port numbers, and patch values are indexed
            # alongside the user/AI text — not just the final summary.
            msgs = (await db.exec(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == conversation_id)
                .where(ChatMessage.message_type.in_(["text", "step"]))
                .order_by(ChatMessage.created_at.asc())
            )).all()

        parts: List[str] = []
        for m in msgs:
            if not m.content or not m.content.strip():
                continue
            if m.message_type == "step":
                parts.append("[Tool output]\n" + m.content.strip())
            else:
                prefix = "User: " if m.role == "user" else "AI: "
                parts.append(prefix + m.content.strip())

        full_text = "\n\n".join(parts) if parts else result_text

        await rag_service.ingest_incident(
            conversation_id=conversation_id,
            conversation_title=title,
            text=full_text,
        )
    except Exception:
        pass  # Never fail the chat stream due to RAG indexing errors


async def _stream_and_save(
    conversation_id: str,
    query: str,
    history: List[Dict],
    runbook_id: Optional[str],
    cluster_context: Optional[str],
    user_id: Optional[int] = None,
):
    """Async generator: streams SSE events, saves messages to DB, then emits token_usage.

    Rule 6 (SSE): we do NOT hold a session open across the whole stream.
    The pre-stream DB writes are done before this generator is called.
    Final writes (saving AI messages) open a fresh AsyncSessionLocal() block
    around a single atomic write — no session is held during the AI loop.
    """
    import asyncio
    set_token_context(user_id=user_id, source="chat")

    collected: List[Dict] = []

    inner = ai_service.run_global_agentic_loop(
        query, context=cluster_context, runbook_id=runbook_id, history=history
    )
    try:
        while True:
            try:
                event = await asyncio.wait_for(inner.__anext__(), timeout=20.0)
                collected.append(event)
                yield f"data: {json.dumps(event)}\n\n"
            except asyncio.TimeoutError:
                # Send SSE comment to keep the connection alive while AI is working
                yield ": keepalive\n\n"
            except StopAsyncIteration:
                break
    finally:
        await inner.aclose()
        if collected:
            result_message: Optional[str] = None
            output_tokens = 0
            for event in collected:
                if event.get("type") == "result":
                    result_message = event.get("message", json.dumps(event))
                tc = len(event.get("message", json.dumps(event))) // 4
                if event.get("type") in ("result", "step"):
                    output_tokens += tc

            # ── write AI messages and update conversation ──────────────────
            async with AsyncSessionLocal() as db:
                for event in collected:
                    msg_content = event.get("message", json.dumps(event))
                    tc = len(msg_content) // 4
                    msg = ChatMessage(
                        conversation_id=conversation_id,
                        role="assistant",
                        content=msg_content,
                        message_type=_event_to_message_type(event["type"]),
                        token_count=tc,
                    )
                    db.add(msg)

                conv = await db.get(ChatConversation, conversation_id)
                if conv:
                    conv.updated_at = utcnow()
                    db.add(conv)
                await db.commit()

                # Compute cumulative conversation total from DB
                all_msgs = (await db.exec(
                    select(ChatMessage).where(ChatMessage.conversation_id == conversation_id)
                )).all()
                conversation_total = sum(m.token_count for m in all_msgs)

            history_chars = sum(len(h.get("content") or "") for h in history)
            input_tokens = (len(query) + history_chars) // 4

            token_event: Dict = {
                "type": "token_usage",
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
                "conversation_total": conversation_total,
                "source": "estimate",
            }
            try:
                yield f"data: {json.dumps(token_event)}\n\n"
            except GeneratorExit:
                pass  # Client disconnected before receiving token_usage event

            await _maybe_compact(conversation_id)
            if result_message:
                await _maybe_index_incident(conversation_id, result_message)


# ── Message Endpoint ───────────────────────────────────────────────────────────

@router.post("/conversations/{conversation_id}/message")
async def send_message(
    conversation_id: str,
    content: str = Body(..., embed=True),
    runbook_id: Optional[str] = Body(None),
    current_user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_async_db),
    cluster_context: Optional[str] = Header(None, alias="X-Cluster-Context"),
) -> StreamingResponse:
    conv = await db.get(ChatConversation, conversation_id)
    if not conv or conv.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Auto-title from first user message
    if conv.title == "New Chat":
        conv.title = content[:60]
        conv.updated_at = utcnow()
        db.add(conv)

    # Save user message
    user_msg = ChatMessage(
        conversation_id=conversation_id,
        role="user",
        content=content,
        message_type="text",
        token_count=len(content) // 4,
    )
    db.add(user_msg)
    await db.commit()

    # Auto-match a runbook if none was explicitly provided
    if not runbook_id:
        try:
            from app.services.runbook_service import match_runbook_logic
            match = match_runbook_logic(content)
            if match.get("confidence") in ("high", "medium") and match.get("matched_runbook_id"):
                runbook_id = match["matched_runbook_id"]
        except Exception:
            pass  # Never block the chat stream due to runbook matching errors

    # Build history (summary + recent messages) — done before streaming starts
    history = []
    if conv.summary:
        history.append({"role": "system", "content": f"Previous conversation summary:\n{conv.summary}"})
    history.extend(await _build_history(conversation_id, db))

    return StreamingResponse(
        _stream_and_save(conversation_id, content, history, runbook_id, cluster_context, user_id=current_user.id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Compact Endpoint ───────────────────────────────────────────────────────────

@router.post("/conversations/{conversation_id}/compact")
async def compact_conversation(
    conversation_id: str,
    current_user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_async_db),
) -> Any:
    conv = await db.get(ChatConversation, conversation_id)
    if not conv or conv.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    await _maybe_compact(conversation_id)
    return {"status": "ok"}
