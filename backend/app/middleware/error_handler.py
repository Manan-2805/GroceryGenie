import logging
import sys
import traceback
import uuid
from typing import Any, cast

from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from app.db.base import AsyncSessionFactory
from app.db.models.error import AppError

logger = logging.getLogger("app.middleware.error_handler")


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Any) -> Response:
        request_id = uuid.uuid4()
        request.state.request_id = request_id

        try:
            response = cast(Response, await call_next(request))
            response.headers["X-Request-ID"] = str(request_id)
            return response
        except Exception as exc:
            return await log_and_create_error_response(request, request_id, exc)


async def log_and_create_error_response(
    request: Request, request_id: uuid.UUID, exc: Exception
) -> JSONResponse:
    status_code = 500
    error_code = "INTERNAL_SERVER_ERROR"
    detail = f"Something went wrong. Reference ID: {request_id}"

    if isinstance(exc, StarletteHTTPException):
        status_code = exc.status_code
        error_code = "HTTP_EXCEPTION"
        detail = exc.detail
    elif isinstance(exc, RequestValidationError):
        status_code = 422
        error_code = "VALIDATION_ERROR"
        detail = str(exc.errors())

    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))

    logger.error(
        f"Error {request_id} on {request.method} {request.url.path}: {exc}\n{tb}"
    )

    # Log to Database using a fresh AsyncSessionFactory
    try:
        async with AsyncSessionFactory() as session:
            user_id = None
            if hasattr(request.state, "user") and request.state.user:
                try:
                    from sqlalchemy.orm import attributes
                    state = attributes.instance_state(request.state.user)
                    uid = state.dict.get("id")
                    if uid:
                        user_id = str(uid)
                except Exception:
                    pass

            app_error = AppError(
                user_id=user_id,
                request_id=request_id,
                endpoint=f"{request.method} {request.url.path}",
                error_code=error_code,
                detail=str(exc),
                stack_trace=tb,
            )
            session.add(app_error)
            await session.commit()
    except Exception as db_exc:
        sys.stderr.write(f"Failed to log AppError to database: {db_exc}\n")

    return JSONResponse(
        status_code=status_code,
        content={
            "detail": f"{detail} (Reference ID: {request_id})" if status_code >= 500 else detail,
            "request_id": str(request_id),
            "exception": str(exc),
            "traceback": tb,
        },
    )
