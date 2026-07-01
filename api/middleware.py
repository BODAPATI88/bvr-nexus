"""
BVR API request validation middleware.

Extracted from api/main.py so middleware can be imported and tested
without pulling in the full application graph.
"""

import os

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

MAX_PAYLOAD_BYTES = int(os.getenv("BVR_MAX_PAYLOAD_BYTES", str(1 * 1024 * 1024)))  # 1 MB


class PayloadSizeMiddleware(BaseHTTPMiddleware):
    """Reject requests whose declared Content-Length exceeds MAX_PAYLOAD_BYTES."""

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > MAX_PAYLOAD_BYTES:
            return Response(
                content='{"detail":"Request body too large"}',
                status_code=413,
                media_type="application/json",
            )
        return await call_next(request)


class ContentTypeMiddleware(BaseHTTPMiddleware):
    """Require application/json Content-Type on mutating requests."""

    async def dispatch(self, request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH"):
            ct = request.headers.get("content-type", "")
            if not ct.startswith("application/json"):
                return Response(
                    content='{"detail":"Content-Type must be application/json"}',
                    status_code=415,
                    media_type="application/json",
                )
        return await call_next(request)
