"""ASGI tee: records authenticated requests without buffering or delaying SSE delivery."""
from __future__ import annotations

import asyncio
import json

import anyio
import logging
from time import perf_counter
from urllib.parse import parse_qsl

from starlette.requests import Request
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)
MAX_REQUEST = 256 * 1024
MAX_RESPONSE = 2 * 1024 * 1024
RUN_PATHS = {"/api/customer-agent/run", "/api/customer-agent/run/stream", "/api/customer-agent/compare",
             "/api/customer-agent/hr/chat/stream", "/v1/moderations", "/v1/guardrails", "/api/moderate"}


class ResponseCapture:
    def __init__(self):
        self.buffer = bytearray()
        self.payload = {}
        self.stream = False
        self.final = False
        self.error = False
        self.truncated = False
        self.discarding = False
        self.observations = []

    def feed(self, chunk):
        if not self.stream:
            room = max(0, MAX_RESPONSE - len(self.buffer))
            self.buffer.extend(chunk[:room])
            self.truncated |= len(chunk) > room
            return
        # Parse byte lines so UTF-8 codepoints split across ASGI chunks remain intact.
        self.buffer.extend(chunk)
        while b"\n\n" in self.buffer:
            block, _, rest = self.buffer.partition(b"\n\n")
            self.buffer = bytearray(rest)
            if self.discarding or len(block) > MAX_RESPONSE:
                self.discarding = False
                self.truncated = True
                continue
            name, data = "message", []
            for line in block.splitlines():
                if line.startswith(b"event:"):
                    name = line[6:].strip().decode("utf-8", "replace")
                if line.startswith(b"data:"):
                    data.append(line[5:].strip())
            try:
                payload = json.loads(b"\n".join(data))
            except (ValueError, UnicodeError):
                continue
            if name == "final":
                self.payload, self.final = payload, True
            elif name == "error":
                self.payload, self.error = {"error": payload}, True
            elif name == "status" and isinstance(payload, dict) and payload.get("defense_signals"):
                self.observations = payload["defense_signals"]
        if len(self.buffer) > MAX_RESPONSE:
            self.buffer.clear()
            self.discarding = True
            self.truncated = True

    def result(self):
        if self.stream:
            if not self.final and self.observations:
                self.payload["defense_signals"] = self.observations
            return self.payload
        if self.truncated:
            return {"capture_truncated": True, "preview": self.buffer[:4096].decode("utf-8", "replace")}
        try:
            return json.loads(self.buffer) if self.buffer else {}
        except (ValueError, UnicodeError):
            return {"content_type": "non_json", "size_bytes": len(self.buffer)}


class ActivityMiddleware:
    def __init__(self, app, auth_store, activity_store):
        self.app, self.auth, self.store = app, auth_store, activity_store

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        tracked = path.startswith("/api/customer-agent") or path.startswith("/api/case-studies") or path.startswith("/api/audit/") or path in RUN_PATHS
        if scope["type"] != "http" or not tracked or scope.get("method") == "OPTIONS":
            return await self.app(scope, receive, send)
        req = Request(scope)
        scheme, _, token = req.headers.get("authorization", "").partition(" ")
        user = await run_in_threadpool(self.auth.current_user,
                                      session=req.cookies.get("pm_session") if path != "/v1/moderations" else None,
                                      token=token.strip() if scheme.lower() == "bearer" else None)
        if not user:
            return await self.app(scope, receive, send)
        session = req.headers.get("x-demo-session", "")[:128]
        event_id = None
        try:
            event_id = await run_in_threadpool(self.store.append, user["id"], kind="request", name=req.method + " " + path,
                                              path=path, method=req.method, session_id=session, status="running", is_run=path in RUN_PATHS)
        except Exception:
            logger.exception("Cannot start demo activity record")
        capture = ResponseCapture()
        body = bytearray()
        received_bytes, http_status, completed = 0, 500, False
        started = perf_counter()

        async def tee_receive():
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                chunk = message.get("body", b"")
                received_bytes += len(chunk)
                # Never store multipart file bytes.
                if "application/json" in req.headers.get("content-type", ""):
                    body.extend(chunk[:max(0, MAX_REQUEST - len(body))])
            return message

        async def tee_send(message):
            nonlocal http_status, completed
            if message["type"] == "http.response.start":
                http_status = message["status"]
                headers = dict(message.get("headers", []))
                capture.stream = b"text/event-stream" in headers.get(b"content-type", b"")
                if event_id:
                    message = {**message, "headers": [*message.get("headers", []), (b"x-activity-id", event_id.encode())]}
            if message["type"] == "http.response.body":
                try:
                    capture.feed(message.get("body", b""))
                except Exception:
                    capture.truncated = True
                    logger.exception("Cannot parse activity response")
                completed = not message.get("more_body", False)
            await send(message)

        failed = False
        cancelled = False
        try:
            await self.app(scope, tee_receive, tee_send)
        except BaseException as error:
            cancelled = isinstance(error, asyncio.CancelledError)
            failed = not cancelled
            raise
        finally:
            if event_id:
                try:
                    if body and received_bytes <= MAX_REQUEST:
                        try:
                            request_payload = json.loads(body)
                        except (ValueError, UnicodeError):
                            request_payload = {"invalid_json": True}
                    else:
                        request_payload = {"content_type": req.headers.get("content-type", ""), "size_bytes": received_bytes}
                    result = capture.result()
                    if isinstance(result, dict):
                        session = str(result.get("session_id") or (request_payload.get("session_id") if isinstance(request_payload, dict) else "") or session)[:128]
                    status = "error" if failed or http_status >= 400 or capture.error else (
                        "interrupted" if cancelled or not completed or capture.stream and not capture.final else "completed")
                    with anyio.CancelScope(shield=True):
                        await run_in_threadpool(self.store.finish, event_id, request=request_payload, response=result,
                                                status=status, http_status=http_status, duration_ms=round((perf_counter() - started) * 1000, 1),
                                                session_id=session, properties={"query": dict(parse_qsl(scope.get("query_string", b"").decode("utf-8", "replace"))),
                                                "request_truncated": received_bytes > MAX_REQUEST,
                                                "response_truncated": capture.truncated})
                except Exception:
                    logger.exception("Cannot finish demo activity record %s", event_id)
