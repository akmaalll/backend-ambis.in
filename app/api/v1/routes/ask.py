import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_llm_client
from app.core.database import get_db
from app.core.llm_client import LLMClient, LLMResponseError
from app.core.visual_spec import fallback_note_spec
from app.api.v1.schemas.ask import AskRequest, AskResponse, VisualAskRequest, VisualAskResponse
from app.api.v1.services.ask import AskService
from app.api.v1.services.visual_ask import VisualAskService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ask", tags=["Ask"])


@router.post("/", response_model=AskResponse)
async def ask_question(request: AskRequest, db: AsyncSession = Depends(get_db)):
    service = AskService(db)
    return await service.process(request)


@router.post("/visual", response_model=VisualAskResponse)
async def ask_visual(
    request: VisualAskRequest,
    db: AsyncSession = Depends(get_db),
    llm_client: LLMClient = Depends(get_llm_client),
):
    start = time.time()
    try:
        result = await VisualAskService(db, llm_client).process(request.question)
    except LLMResponseError as exc:
        logger.warning("visual ask fell back to a note: %s", exc)
        fallback = fallback_note_spec(
            "explanation", "Maaf, aku belum bisa membuat gambarnya. Coba tanyakan dengan kalimat lain ya."
        )
        return VisualAskResponse(
            visual=fallback.to_payload(),
            degraded=True,
            processing_time_ms=int((time.time() - start) * 1000),
        )
    return VisualAskResponse(
        visual=result.visual.to_payload(),
        references=result.references,
        processing_time_ms=result.processing_time_ms,
    )
