import asyncio
import random
from collections.abc import Callable, Awaitable
from typing import TypeVar

import structlog
from sqlalchemy.exc import OperationalError, InterfaceError

logger = structlog.get_logger()

T = TypeVar("T")
RETRYABLE = (OperationalError, InterfaceError)


async def with_retry(
    coro: Callable[[], Awaitable[T]],
    max_attempts: int = 3,
    base_delay: float = 0.1,
    max_delay: float = 5.0,
    request_id: str | None = None,
    retryable: tuple[type[Exception], ...] = RETRYABLE,
) -> T:
    last_exc = None
    for attempt in range(max_attempts):
        try:
            return await coro()
        except retryable as e:
            last_exc = e
            if attempt < max_attempts - 1:
                delay = min(base_delay * (2**attempt), max_delay)
                jitter = delay * 0.1 * random.random()
                sleep_time = delay + jitter
                logger.warning(
                    "retry_attempt",
                    attempt=attempt + 1,
                    max_attempts=max_attempts,
                    error=str(e),
                    sleep_seconds=round(sleep_time, 3),
                    request_id=request_id,
                )
                await asyncio.sleep(sleep_time)
            else:
                raise last_exc
    raise last_exc
