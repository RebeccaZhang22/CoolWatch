from __future__ import annotations

import hashlib
import json
import random
import time
from dataclasses import dataclass
from uuid import uuid4

import httpx

from backend.config import Settings


SUGGESTION_TEXT = {
    0: "通过",
    1: "嫌疑",
    2: "不通过",
}

YIDUN_LABEL_NAMES = {
    100: "色情",
    200: "广告",
    260: "广告法",
    300: "暴恐",
    400: "违禁",
    500: "涉政",
    600: "谩骂",
    700: "灌水",
    900: "其他",
    1100: "价值观",
}


@dataclass
class NeteaseYidunAssessment:
    suggestion: int | None
    suggestion_level: int | None
    task_id: str
    labels: list[str]
    raw_output: str
    latency_ms: int
    error: str | None = None
    chunk_count: int = 1
    input_chars: int = 0

    @property
    def risky(self) -> bool | None:
        if self.suggestion is None:
            return None
        return self.suggestion in {1, 2}

    @property
    def blocked(self) -> bool:
        return self.suggestion == 2


class NeteaseYidunClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(timeout=settings.netease_yidun_timeout_seconds)

    async def close(self) -> None:
        await self._client.aclose()

    async def moderate_prompt(self, content: str) -> NeteaseYidunAssessment:
        started = time.perf_counter()
        chunks = _content_chunks(content)
        missing = self._missing_credentials()
        if missing:
            return self._error_assessment(
                f"未配置 {', '.join(missing)}",
                started,
                chunk_count=len(chunks),
                input_chars=len(content),
            )

        payloads: list[dict] = []
        try:
            for chunk in chunks:
                response = await self._client.post(
                    self.settings.netease_yidun_api_url,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    data=self._build_params(chunk),
                )
                response.raise_for_status()
                payloads.append(response.json())
        except Exception as error:
            return self._error_assessment(
                str(error),
                started,
                chunk_count=len(chunks),
                input_chars=len(content),
            )

        assessments = [self._parse_response(payload, started) for payload in payloads]
        errors = [assessment.error for assessment in assessments if assessment.error]
        suggestions = [
            assessment.suggestion
            for assessment in assessments
            if assessment.suggestion is not None
        ]
        suggestion_levels = [
            assessment.suggestion_level
            for assessment in assessments
            if assessment.suggestion_level is not None
        ]
        return NeteaseYidunAssessment(
            suggestion=max(suggestions) if suggestions else None,
            suggestion_level=max(suggestion_levels) if suggestion_levels else None,
            task_id=",".join(
                assessment.task_id for assessment in assessments if assessment.task_id
            ),
            labels=list(
                dict.fromkeys(
                    label for assessment in assessments for label in assessment.labels
                )
            ),
            raw_output=json.dumps(
                {
                    "schema": "perspective_watch.netease_yidun.chunked_response.v1",
                    "input_chars": len(content),
                    "chunk_count": len(chunks),
                    "responses": payloads,
                },
                ensure_ascii=False,
            ),
            latency_ms=round((time.perf_counter() - started) * 1000),
            error="; ".join(errors) if errors else None,
            chunk_count=len(chunks),
            input_chars=len(content),
        )

    def _missing_credentials(self) -> list[str]:
        missing = []
        if not self.settings.netease_yidun_secret_id:
            missing.append("NETEASE_YIDUN_SECRET_ID")
        if not self.settings.netease_yidun_secret_key:
            missing.append("NETEASE_YIDUN_SECRET_KEY")
        if not self.settings.netease_yidun_business_id:
            missing.append("NETEASE_YIDUN_BUSINESS_ID")
        return missing

    def _build_params(self, content: str) -> dict[str, str]:
        params = {
            "secretId": self.settings.netease_yidun_secret_id,
            "businessId": self.settings.netease_yidun_business_id,
            "version": self.settings.netease_yidun_version,
            "timestamp": str(int(time.time() * 1000)),
            "nonce": str(random.randint(0, 10_000_000_000)),
            "dataId": uuid4().hex,
            "content": content,
        }
        signature_method = self.settings.netease_yidun_signature_method.strip().upper()
        if signature_method:
            params["signatureMethod"] = signature_method
        if self.settings.netease_yidun_check_labels.strip():
            params["checkLabels"] = self.settings.netease_yidun_check_labels.strip()
        params["signature"] = sign_yidun_params(params, self.settings.netease_yidun_secret_key)
        return params

    def _parse_response(self, payload: dict, started: float) -> NeteaseYidunAssessment:
        antispam = payload.get("result", {}).get("antispam", {}) if isinstance(payload, dict) else {}
        labels = extract_yidun_labels(antispam.get("labels", []))
        code = payload.get("code") if isinstance(payload, dict) else None
        error = None if code == 200 else f"{code}: {payload.get('msg', 'unknown error')}"
        return NeteaseYidunAssessment(
            suggestion=antispam.get("suggestion"),
            suggestion_level=antispam.get("suggestionLevel"),
            task_id=str(antispam.get("taskId") or ""),
            labels=labels,
            raw_output=json.dumps(payload, ensure_ascii=False),
            latency_ms=round((time.perf_counter() - started) * 1000),
            error=error,
        )

    def _error_assessment(
        self,
        error: str,
        started: float,
        *,
        chunk_count: int = 1,
        input_chars: int = 0,
    ) -> NeteaseYidunAssessment:
        return NeteaseYidunAssessment(
            suggestion=None,
            suggestion_level=None,
            task_id="",
            labels=[],
            raw_output="",
            latency_ms=round((time.perf_counter() - started) * 1000),
            error=error,
            chunk_count=chunk_count,
            input_chars=input_chars,
        )


def _content_chunks(content: str, limit: int = 10_000) -> list[str]:
    if limit <= 0:
        raise ValueError("content chunk limit must be positive")
    if not content:
        return [""]
    return [content[start : start + limit] for start in range(0, len(content), limit)]


def sign_yidun_params(params: dict[str, str], secret_key: str) -> str:
    signature_method = params.get("signatureMethod", "").upper()
    signing_text = "".join(f"{key}{params[key]}" for key in sorted(params) if key != "signature") + secret_key
    encoded = signing_text.encode("utf-8")
    if signature_method == "SHA1":
        return hashlib.sha1(encoded).hexdigest()
    if signature_method == "SHA256":
        return hashlib.sha256(encoded).hexdigest()
    if signature_method == "SM3":
        raise ValueError("当前后端未安装 SM3 签名依赖，请使用 MD5/SHA1/SHA256")
    return hashlib.md5(encoded).hexdigest()


def extract_yidun_labels(labels: list) -> list[str]:
    result = []
    for item in labels if isinstance(labels, list) else []:
        label = item.get("label") if isinstance(item, dict) else None
        if label is not None:
            label_id = int(label) if str(label).isdigit() else label
            result.append(YIDUN_LABEL_NAMES.get(label_id, f"标签 {label}"))
    return result
