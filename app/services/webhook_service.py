import json
import structlog
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.dlq import write_to_dlq
from app.core.retry import with_retry
from app.db.events import insert_event
from app.models.schemas import WebhookOut
from app.utils.event_id import derive_event_id
from app.utils.normalize import normalize_webhook
from app.utils.validation import validate_webhook_body

logger = structlog.get_logger()
_HTTP_STATUS = {"invalid": 202, "created": 201, "duplicate": 200}
_settings = Settings()


async def _notify_webhook(event_id: str) -> None:
    """Notify external webhook (e.g. Slack) that event was processed. Logs errors, never raises."""
    url = _settings.notification_webhook_url
    if not url:
        return
    message = f"Success: event_id `{event_id}` was processed"
    payload = {"text": message}  # Slack incoming webhook format; works for most webhooks
    try:
        async with httpx.AsyncClient() as client:
            await client.post(url, json=payload, timeout=5.0)
    except Exception as e:
        logger.warning("notification_webhook_failed", event_id=event_id, error=str(e))


async def ingest(
    session: AsyncSession,
    raw: bytes,
    idempotency_key: str | None,
    request_id: str,
) -> tuple[WebhookOut, int]:
    """Ingest webhook. Returns (WebhookOut, http_status_code)."""
    try:
        body = json.loads(raw) if raw else {}
    except json.JSONDecodeError as e:
        await write_to_dlq(
            session,
            {"raw": raw.decode(errors="replace")},
            f"invalid json: {e}",
            request_id,
        )
        logger.warning("webhook_invalid", reason="invalid json", request_id=request_id)
        return WebhookOut(status="invalid", dlq=True, reason="invalid event"), 202

    if reason := validate_webhook_body(body):
        await write_to_dlq(session, body, reason, request_id)
        logger.warning("webhook_invalid", reason=reason, request_id=request_id)
        return WebhookOut(status="invalid", dlq=True, reason="invalid event"), 202

    event_id = derive_event_id(body, idempotency_key)
    standardized = normalize_webhook(body, event_id)

    async def persist():
        return await insert_event(session, event_id, json.dumps(standardized))

    result = await with_retry(persist, request_id=request_id)
    status = "created" if result == "created" else "duplicate"
    logger.info(
        "webhook_ingested" if result == "created" else "webhook_duplicate",
        event_id=event_id,
        request_id=request_id,
    )
    await _notify_webhook(event_id)

    out = WebhookOut(status=status, event_id=event_id, standardized=standardized)
    return out, _HTTP_STATUS[status]
