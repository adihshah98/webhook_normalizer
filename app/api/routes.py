from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
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
    # Reject oversized payloads before reading into memory
    settings = get_settings()
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > settings.max_body_size:
        raise HTTPException(status_code=413, detail="Request body too large")

    raw_body = await request.body()
    if len(raw_body) > settings.max_body_size:
        raise HTTPException(status_code=413, detail="Request body too large")

    # Pass headers as dict so ingest can read Stripe/PayPal verification headers
    header_dict = dict(request.headers) if request.headers else None
    body, status_code = await ingest(
        session,
        raw_body,
        getattr(request.state, "request_id", "unknown"),
        headers=header_dict,
    )
    return JSONResponse(
        content=body.model_dump(mode="json", exclude_none=True),
        status_code=status_code,
    )
