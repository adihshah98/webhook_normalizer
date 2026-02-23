from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.api.routes import router
from app.core.config import Settings
from app.core.logging import configure_logging
from app.core.rate_limit import InMemoryRateLimiter
from app.core.retry import with_retry
from app.db.session import init_db
from app.middleware.request_log import RequestLogMiddleware

settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    await with_retry(lambda: init_db())
    if settings.rate_limit_requests > 0:
        app.state.rate_limiter = InMemoryRateLimiter(
            requests_per_window=settings.rate_limit_requests,
            window_seconds=settings.rate_limit_window_seconds,
        )
    else:
        app.state.rate_limiter = None
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(RequestLogMiddleware)
app.include_router(router)
