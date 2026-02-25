import structlog

from app.db.models import DLQEntry
from app.db.session import async_session

logger = structlog.get_logger()


async def write_to_dlq(
    raw_payload: dict,
    reason: str,
    request_id: str,
) -> None:
    """Write invalid webhook to DLQ table using an independent session."""
    try:
        async with async_session() as session:
            entry = DLQEntry(
                request_id=request_id,
                reason=reason,
                payload=raw_payload,
            )
            session.add(entry)
            await session.commit()
    except Exception as e:
        logger.error("dlq_write_failed", request_id=request_id, error=str(e))
