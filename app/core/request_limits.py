"""ASGI request-size guard for JSON and streamed bodies."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


class RequestBodyLimitMiddleware:
    """Reject bodies over ``max_bytes``, including chunked requests."""

    def __init__(self, app: Callable[..., Awaitable[None]], max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max(0, int(max_bytes))

    async def __call__(self, scope: dict[str, Any], receive: Callable, send: Callable) -> None:
        if scope["type"] != "http" or self.max_bytes == 0:
            await self.app(scope, receive, send)
            return

        for name, value in scope.get("headers", []):
            if name.lower() != b"content-length":
                continue
            try:
                if int(value) > self.max_bytes:
                    await self._reject(send)
                    return
            except ValueError:
                # The HTTP server normally rejects malformed framing. If one
                # reaches ASGI, the streaming counter below remains authoritative.
                pass

        received = 0
        response_started = False

        async def limited_receive() -> dict[str, Any]:
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _RequestBodyTooLarge
            return message

        async def tracked_send(message: dict[str, Any]) -> None:
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except _RequestBodyTooLarge:
            if response_started:
                raise
            await self._reject(send)

    @staticmethod
    async def _reject(send: Callable) -> None:
        body = b'{"detail":"Request body too large."}'
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


class _RequestBodyTooLarge(Exception):
    pass
