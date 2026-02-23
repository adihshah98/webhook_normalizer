from sqlalchemy.exc import IntegrityError, OperationalError, InterfaceError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Event

RETRYABLE = (OperationalError, InterfaceError)


async def insert_event(
    session: AsyncSession,
    event_id: str,
    payload: str,
) -> str:
    """Insert event. Returns 'created' or 'duplicate'. Raises on other errors for retry."""
    event = Event(event_id=event_id, payload=payload)
    session.add(event)
    try:
        await session.commit()
        return "created"
    except IntegrityError:
        await session.rollback()
        return "duplicate"
    except RETRYABLE:
        await session.rollback()
        raise
