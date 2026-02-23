import pytest
from unittest.mock import AsyncMock

from app.core.retry import with_retry


@pytest.mark.asyncio
async def test_with_retry_succeeds_first_try():
    coro = AsyncMock(return_value=42)
    result = await with_retry(coro, max_attempts=3)
    assert result == 42
    coro.assert_called_once()


@pytest.mark.asyncio
async def test_with_retry_succeeds_after_failures():
    from sqlalchemy.exc import OperationalError
    coro = AsyncMock(side_effect=[OperationalError("fail", None, None), 42])
    result = await with_retry(coro, max_attempts=3, base_delay=0.01, max_delay=0.05)
    assert result == 42
    assert coro.call_count == 2


@pytest.mark.asyncio
async def test_with_retry_raises_after_max_attempts():
    from sqlalchemy.exc import OperationalError
    coro = AsyncMock(side_effect=OperationalError("fail", None, None))
    with pytest.raises(OperationalError):
        await with_retry(coro, max_attempts=3, base_delay=0.01, max_delay=0.05)
    assert coro.call_count == 3


@pytest.mark.asyncio
async def test_with_retry_non_retryable_propagates():
    coro = AsyncMock(side_effect=ValueError("not retryable"))
    with pytest.raises(ValueError):
        await with_retry(coro, max_attempts=3)
    coro.assert_called_once()
