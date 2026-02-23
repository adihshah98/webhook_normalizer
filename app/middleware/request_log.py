import time
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.logging import bind_request_id, log


class RequestLogMiddleware(BaseHTTPMiddleware):
    """Adds request_id to state and context, logs each request with method, path, status, duration."""

    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        bind_request_id(request_id)

        start = time.time()
        resp = await call_next(request)
        ms = int((time.time() - start) * 1000)
        log.info(
            "request",
            method=request.method,
            path=request.url.path,
            status=resp.status_code,
            ms=ms,
        )
        return resp
