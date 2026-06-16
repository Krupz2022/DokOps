"""
External Knowledge Sources — retrieve-only external RAG connections (e.g. Azure AI Search).
"""
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api import deps
from app.models.user import User
from app.services.external_rag_service import external_rag_service
from app.core.encryption import decrypt

router = APIRouter()


class SourceIn(BaseModel):
    name: str
    provider: str
    config: dict


class ConfigIn(BaseModel):
    endpoint: str
    api_key: str
    index_name: str
    top_k: int = 3
    semantic_config: str = ""


class ToggleIn(BaseModel):
    enabled: bool


def _require_superuser(current_user: User = Depends(deps.get_current_user)) -> User:
    """Dependency that enforces superuser access and returns 403 (not 400) on failure."""
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Superuser privileges required",
        )
    return current_user


def _mask_config(config_dict: dict) -> dict:
    masked = dict(config_dict)
    if masked.get("api_key"):
        masked["api_key"] = "••••••"
    return masked


def _source_response(source) -> dict:
    try:
        config_dict = json.loads(decrypt(source.config))
    except Exception:
        config_dict = {}
    return {
        "id": source.id,
        "name": source.name,
        "provider": source.provider,
        "enabled": source.enabled,
        "config": _mask_config(config_dict),
        "created_at": source.created_at,
    }


@router.get("")
def list_sources(current_user: User = Depends(deps.get_current_user)) -> Any:
    return [_source_response(s) for s in external_rag_service.list_sources()]


@router.post("")
def create_source(
    body: SourceIn,
    current_user: User = Depends(_require_superuser),
) -> Any:
    source = external_rag_service.create_source(body.name, body.provider, body.config)
    return _source_response(source)


@router.put("/{source_id}")
def update_source(
    source_id: str,
    body: SourceIn,
    current_user: User = Depends(_require_superuser),
) -> Any:
    source = external_rag_service.update_source(
        source_id, name=body.name, config_dict=body.config
    )
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    return _source_response(source)


@router.delete("/{source_id}")
def delete_source(
    source_id: str,
    current_user: User = Depends(_require_superuser),
) -> Any:
    if not external_rag_service.delete_source(source_id):
        raise HTTPException(status_code=404, detail="Source not found")
    return {"status": "deleted"}


# IMPORTANT: /test-config must be declared BEFORE /{source_id}/test to avoid
# FastAPI matching "test-config" as a source_id path parameter.
@router.post("/test-config")
def test_config(
    body: ConfigIn,
    current_user: User = Depends(_require_superuser),
) -> Any:
    try:
        external_rag_service.test_config(body.model_dump())
        return {"status": "connected"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.post("/{source_id}/test")
def test_source(
    source_id: str,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    try:
        external_rag_service.test_source(source_id)
        return {"status": "connected"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.patch("/{source_id}/toggle")
def toggle_source(
    source_id: str,
    body: ToggleIn,
    current_user: User = Depends(_require_superuser),
) -> Any:
    source = external_rag_service.update_source(source_id, enabled=body.enabled)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    return _source_response(source)
