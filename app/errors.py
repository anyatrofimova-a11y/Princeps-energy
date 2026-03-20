"""Consistent API error handling for Princeps."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


class APIError(Exception):
    """Structured API error with code, message, status, and optional details."""

    def __init__(
        self,
        code: str,
        message: str,
        status: int = 400,
        details: dict | None = None,
    ):
        self.code = code
        self.message = message
        self.status = status
        self.details = details
        super().__init__(message)


async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    """FastAPI exception handler for APIError."""
    return JSONResponse(
        status_code=exc.status,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            }
        },
    )
