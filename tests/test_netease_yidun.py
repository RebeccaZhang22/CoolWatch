from __future__ import annotations

import asyncio

import httpx

from backend.config import Settings
from backend.watchers.netease_yidun import NeteaseYidunClient


def test_long_content_is_fully_chunked_and_riskiest_result_wins() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        suggestion = 0 if len(requests) == 1 else 2
        return httpx.Response(
            200,
            json={
                "code": 200,
                "result": {
                    "antispam": {
                        "suggestion": suggestion,
                        "suggestionLevel": suggestion,
                        "taskId": f"task-{len(requests)}",
                        "labels": [{"label": 900}] if suggestion else [],
                    }
                },
            },
        )

    settings = Settings(
        NETEASE_YIDUN_SECRET_ID="secret-id",
        NETEASE_YIDUN_SECRET_KEY="secret-key",
        NETEASE_YIDUN_BUSINESS_ID="business-id",
    )
    client = NeteaseYidunClient(settings)
    asyncio.run(client._client.aclose())
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    content = "甲" * 10_000 + "恶"

    assessment = asyncio.run(client.moderate_prompt(content))
    asyncio.run(client.close())

    assert len(requests) == 2
    assert len(requests[0].content.decode()) > 10_000
    assert b"%E6%81%B6" in requests[1].content
    assert assessment.input_chars == 10_001
    assert assessment.chunk_count == 2
    assert assessment.suggestion == 2
    assert assessment.risky is True
    assert assessment.task_id == "task-1,task-2"
    assert assessment.labels == ["其他"]
