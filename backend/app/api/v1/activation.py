from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.api import deps
from app.services import activation_service

router = APIRouter()


class ActivateRequest(BaseModel):
    license_key: str


@router.post("/activate")
async def activate(payload: ActivateRequest, db: Session = Depends(deps.get_db)):
    result = await activation_service.activate_key(payload.license_key, db)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.get("/status")
def get_status(db: Session = Depends(deps.get_db)):
    return activation_service.get_status(db)
