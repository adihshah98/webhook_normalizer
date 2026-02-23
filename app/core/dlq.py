from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DLQEntry


async def write_to_dlq(
    session: AsyncSession,
    raw_payload: dict,
    reason: str,
    request_id: str,
) -> None:
    """Write invalid webhook to DLQ table. Commits immediately."""
    entry = DLQEntry(
        request_id=request_id,
        reason=reason,
        payload=raw_payload,
    )
    session.add(entry)
    await session.commit()
