import logging
from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = str(uuid4())
        try:
            response = await call_next(request)
        except Exception as exc:
            logger.error("request_failed id=%s kind=%s", request_id, type(exc).__name__)
            response = JSONResponse(
                status_code=500,
                content={"detail": "Something went wrong.", "request_id": request_id},
            )
        response.headers["X-Request-ID"] = request_id
        return response
