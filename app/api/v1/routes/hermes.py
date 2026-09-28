from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from app.api.deps import get_llm_client
from app.api.v1.schemas.hermes import HermesAgentRequest
from app.api.v1.services.hermes_agent import HermesAgentService
from app.core.database import async_session_factory

router = APIRouter(prefix="/agent", tags=["Hermes Agent"])


@router.post(
    "/hermes",
    summary="Hermes Agent Evidence Pipeline",
    description=(
        "Evaluate a student's attempt, diagnose misconceptions, decide the next "
        "intervention, and update mastery state — streamed as SSE or returned as one "
        "JSON response."
    ),
    status_code=status.HTTP_200_OK,
)
async def execute_hermes_agent(request: HermesAgentRequest):
    llm_client = get_llm_client()

    if not request.stream:
        async with async_session_factory() as db:
            service = HermesAgentService(db, llm_client)
            try:
                return await service.process_sync(request)
            except ValueError as exc:
                raise HTTPException(status_code=_status_for(exc), detail=str(exc)) from exc

    # SSE: StreamingResponse returns before this generator body runs, so a
    # Depends(get_db)-yielded session would already be closed by then — the
    # session must be opened manually inside the generator instead.
    async def event_source():
        async with async_session_factory() as db:
            service = HermesAgentService(db, llm_client)
            async for chunk in service.generate_stream(request):
                yield chunk

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Content-Type": "text/event-stream",
        },
    )


def _status_for(exc: ValueError) -> int:
    if "does not belong to" in str(exc):
        return status.HTTP_403_FORBIDDEN
    return status.HTTP_404_NOT_FOUND
