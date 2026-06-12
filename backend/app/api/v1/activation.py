from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import deps
from app.services import activation_service

router = APIRouter()


class ActivateRequest(BaseModel):
    license_key: str


@router.post("/activate")
async def activate(payload: ActivateRequest, db: AsyncSession = Depends(deps.get_async_db)):
    result = await activation_service.activate_key(payload.license_key, db)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.get("/status")
async def get_status(db: AsyncSession = Depends(deps.get_async_db)):
    return await activation_service.get_status(db)
