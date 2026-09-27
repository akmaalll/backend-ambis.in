"""
models.py - Endpoint untuk daftar model AI yang tersedia.

GET /api/v1/models  ->  list model yang bisa dipilih user
"""
from fastapi import APIRouter
from pydantic import BaseModel

from app.api.v1.services.multi_ai import AVAILABLE_MODELS, DEFAULT_MODEL_ID

router = APIRouter(prefix="/models", tags=["Models"])


class ModelInfo(BaseModel):
    id: str
    name: str
    provider: str
    provider_label: str
    description: str
    is_free: bool
    icon: str


class ModelsResponse(BaseModel):
    models: list[ModelInfo]
    default_model_id: str


@router.get("/", response_model=ModelsResponse)
async def list_models():
    """Mengembalikan daftar model AI gratis yang tersedia."""
    return ModelsResponse(
        models=[ModelInfo(**m) for m in AVAILABLE_MODELS],
        default_model_id=DEFAULT_MODEL_ID,
    )
