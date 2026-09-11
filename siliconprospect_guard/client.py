from __future__ import annotations

import os
from typing import Any, Mapping
from uuid import uuid4

import httpx

from .errors import SiliconProspectAPIError
from .types import ModerationRequest, ModerationResponse


class _Moderations:
    def __init__(self, client: "SiliconProspectGuard") -> None:
        self._client = client

    def create(
        self,
        *,
        messages: list[Mapping[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        metadata: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
        request_id: str | None = None,
    ) -> ModerationResponse:
        request = ModerationRequest(
            messages=[dict(message) for message in messages],
            tools=tools,
            metadata=dict(metadata) if metadata else None,
            idempotency_key=idempotency_key,
            request_id=request_id,
        )
        headers = {"Authorization": f"Bearer {self._client.api_key}"}
        if request.request_id:
            headers["X-Request-Id"] = request.request_id
        if request.idempotency_key:
            headers["Idempotency-Key"] = request.idempotency_key
        response = self._client._http.post(
            f"{self._client.base_url}/v1/moderations",
            json=request.model_dump(exclude_none=True, exclude={"idempotency_key", "request_id"}),
            headers=headers,
        )
        if response.is_error:
            self._raise_api_error(response)
        return ModerationResponse.model_validate(response.json())

    @staticmethod
    def _raise_api_error(response: httpx.Response) -> None:
        payload = response.json() if response.content else {}
        error = payload.get("error", {}) if isinstance(payload, dict) else {}
        raise SiliconProspectAPIError(
            error.get("message") or f"SiliconProspect API returned HTTP {response.status_code}",
            status_code=response.status_code,
            code=error.get("code"),
            request_id=error.get("request_id") or response.headers.get("x-request-id"),
            param=error.get("param"),
            retry_after=response.headers.get("retry-after"),
        )


class SiliconProspectGuard:
    """Synchronous Python client for the standardized moderation API.

    The SDK deliberately performs no automatic retries: callers must opt into
    idempotency when retrying a timed-out request.
    """

    def __init__(self, *, api_key: str | None = None, base_url: str | None = None,
                 timeout: float = 30.0) -> None:
        self.api_key = api_key or os.getenv("SILICONPROSPECT_API_KEY", "")
        if not self.api_key:
            raise ValueError("api_key is required (or set SILICONPROSPECT_API_KEY)")
        self.base_url = (base_url or os.getenv("SILICONPROSPECT_BASE_URL", "http://127.0.0.1:18088")).rstrip("/")
        self._http = httpx.Client(timeout=timeout)
        self.moderations = _Moderations(self)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "SiliconProspectGuard":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
