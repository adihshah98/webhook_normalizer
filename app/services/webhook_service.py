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
from app.utils.adyen_signature import verify_adyen_signature
from app.utils.paypal_signature import verify_paypal_signature
from app.utils.stripe_signature import verify_stripe_signature
from app.utils.validation import validate_webhook_body

logger = structlog.get_logger()
_HTTP_STATUS = {"invalid": 202, "created": 201, "duplicate": 200}
_settings = Settings()


async def _notify_webhook(event_id: str, provider: str) -> None:
    """Notify external webhook (e.g. Slack) that event was processed. Logs errors, never raises."""
    url = _settings.notification_webhook_url
    if not url:
        return
    message = f"Success: event_id `{event_id}` from {provider} was processed"
    payload = {"text": message}
    try:
        async with httpx.AsyncClient() as client:
            await client.post(url, json=payload, timeout=5.0)
    except Exception as e:
        logger.warning("notification_webhook_failed", event_id=event_id, error=str(e))


def _is_stripe_event(body: dict) -> bool:
    """Check if payload looks like a Stripe Event."""
    if not isinstance(body, dict):
        return False
    if body.get("object") != "event":
        return False
    data = body.get("data")
    return isinstance(data, dict) and "object" in data


def _is_adyen_event(body: dict) -> bool:
    """Check if payload looks like an Adyen Standard webhook."""
    if not isinstance(body, dict):
        return False
    items = body.get("notificationItems")
    if not isinstance(items, list) or len(items) == 0:
        return False
    first = items[0]
    return isinstance(first, dict) and "NotificationRequestItem" in first


def _is_paypal_event(body: dict) -> bool:
    """Check if payload looks like a PayPal webhook."""
    if not isinstance(body, dict):
        return False
    return bool(body.get("event_type") and body.get("id") and "create_time" in body)


def _get_header(headers: dict | None, key: str) -> str | None:
    """Case-insensitive header lookup (HTTP headers are case-insensitive)."""
    if not headers:
        return None
    for k, v in headers.items():
        if k.lower() == key.lower():
            return v
    return None


async def ingest(
    session: AsyncSession,
    raw: bytes,
    idempotency_key: str | None,
    request_id: str,
    *,
    headers: dict | None = None,
) -> tuple[WebhookOut, int]:
    """Ingest webhook. Returns (WebhookOut, http_status_code)."""
    try:
        body = json.loads(raw) if raw else {}
        logger.info(
            "webhook_received",
            request_id=request_id,
            body_keys=list(body.keys()) if isinstance(body, dict) else None,
            body_sample=body if isinstance(body, dict) and len(str(body)) < 2000 else "(truncated)",
        )
    except json.JSONDecodeError as e:
        await write_to_dlq(
            session,
            {"raw": raw.decode(errors="replace")},
            f"invalid json: {e}",
            request_id,
        )
        logger.warning("webhook_invalid", reason="invalid json", request_id=request_id)
        return WebhookOut(status="invalid", dlq=True, reason="invalid event"), 202

    reason = validate_webhook_body(body)
    if reason:
        await write_to_dlq(session, body, reason, request_id)
        logger.warning("webhook_invalid", reason=reason, request_id=request_id)
        return WebhookOut(status="invalid", dlq=True, reason="invalid event"), 202

    # Stripe signature verification (when secret is configured; detect by header)
    if _get_header(headers, "Stripe-Signature") and _settings.stripe_webhook_secret:
        if not verify_stripe_signature(
            raw, _get_header(headers, "Stripe-Signature"), _settings.stripe_webhook_secret
        ):
            await write_to_dlq(
                session, body, "stripe signature verification failed", request_id
            )
            logger.warning(
                "webhook_invalid",
                reason="stripe signature verification failed",
                request_id=request_id,
            )
            return WebhookOut(status="invalid", dlq=True, reason="invalid signature"), 401

    # Adyen HMAC verification (when key is configured)
    if _is_adyen_event(body) and _settings.adyen_hmac_key:
        first_item = body["notificationItems"][0]
        if not verify_adyen_signature(first_item, _settings.adyen_hmac_key):
            await write_to_dlq(
                session, body, "adyen HMAC verification failed", request_id
            )
            logger.warning(
                "webhook_invalid",
                reason="adyen HMAC verification failed",
                request_id=request_id,
            )
            return WebhookOut(status="invalid", dlq=True, reason="invalid signature"), 401

    # PayPal signature verification (when webhook_id is configured; detect by header)
    if _get_header(headers, "paypal-transmission-id") and _settings.paypal_webhook_id:
        if not verify_paypal_signature(
            raw,
            _get_header(headers, "paypal-transmission-id"),
            _get_header(headers, "paypal-transmission-time"),
            _get_header(headers, "paypal-transmission-sig"),
            _get_header(headers, "paypal-cert-url"),
            _settings.paypal_webhook_id,
        ):
            await write_to_dlq(
                session, body, "paypal signature verification failed", request_id
            )
            logger.warning(
                "webhook_invalid",
                reason="paypal signature verification failed",
                request_id=request_id,
            )
            return WebhookOut(status="invalid", dlq=True, reason="invalid signature"), 401

    event_id = derive_event_id(body, idempotency_key)
    standardized = normalize_webhook(body, event_id, headers=headers)

    logger.info(
        "webhook_classified",
        request_id=request_id,
        source=standardized["source"],
        event_id=event_id,
    )

    async def persist():
        return await insert_event(session, event_id, json.dumps(standardized))

    result = await with_retry(persist, request_id=request_id)
    status = "created" if result == "created" else "duplicate"
    logger.info(
        "webhook_ingested" if result == "created" else "webhook_duplicate",
        event_id=event_id,
        request_id=request_id,
    )
    await _notify_webhook(event_id, standardized["source"])

    out = WebhookOut(status=status, event_id=event_id, standardized=standardized)
    return out, _HTTP_STATUS[status]
