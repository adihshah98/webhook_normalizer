from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_session
from app.core.rate_limit import rate_limit_dep
from app.db.session import check_ready
from app.services.webhook_service import ingest

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz() -> JSONResponse:
    ok = await check_ready()
    if ok:
        return JSONResponse(content={"status": "ready"}, status_code=200)
    return JSONResponse(content={"status": "not ready"}, status_code=503)


@router.post("/webhook")
async def webhook(
    request: Request,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(rate_limit_dep),
) -> JSONResponse:
    body, status_code = await ingest(
        session,
        await request.body(),
        request.headers.get("X-Idempotency-Key"),
        getattr(request.state, "request_id", "unknown"),
    )
    return JSONResponse(
        content=body.model_dump(mode="json", exclude_none=True),
        status_code=status_code,
    )
