from fastapi import APIRouter, status
from fastapi.responses import StreamingResponse
from app.api.v1.schemas.hermes import HermesAgentRequest, HermesNonStreamResponse
from app.api.v1.services.hermes_agent import HermesAgentService

router = APIRouter(prefix="/agent", tags=["Hermes Agent"])


@router.post(
    "/hermes",
    summary="Hermes Agent Reasoning & Execution Stream",
    description="Endpoint interface for Hermes Agent supporting Server-Sent Events (SSE) streaming and tool call simulation.",
    status_code=status.HTTP_200_OK,
)
async def execute_hermes_agent(request: HermesAgentRequest):
    service = HermesAgentService()

    if not request.stream:
        return await service.process_sync(request)

    return StreamingResponse(
        service.generate_stream(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Content-Type": "text/event-stream",
        },
    )
