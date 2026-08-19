from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from fastapi import UploadFile

from backend.customer_agent_catalog import (
    CUSTOMER_AGENT_DATA_ROOT,
    LoadedCustomerAgentScenario,
    load_customer_agent_scenario,
)
from backend.customer_agent_rag import Bm25KnowledgeRetriever
from backend.customer_agent_schemas import (
    CustomerAgentRagConfigResponse,
    CustomerAgentRagDocumentContentResponse,
    CustomerAgentRagDocumentResponse,
    CustomerAgentRagMutationResponse,
    CustomerAgentSystemPromptResponse,
)


MAX_SYSTEM_PROMPT_BYTES = 100_000
MAX_RAG_UPLOAD_BYTES = 2 * 1024 * 1024
ALLOWED_RAG_SUFFIXES = frozenset({".md", ".txt"})
RAG_UPLOADS_RELATIVE_DIR = Path("rag/uploads")
RAG_DOCUMENTS_RELATIVE_PATH = Path("rag/documents.json")
SYSTEM_PROMPT_OVERRIDE_RELATIVE_PATH = Path("agent/system_prompt.override.md")
_SAFE_STEM_PATTERN = re.compile(r"[^a-z0-9]+")


class CustomerAgentRuntimeConfig:
    """Own the mutable customer-Agent data and its current BM25 snapshot."""

    def __init__(self, data_root: Path = CUSTOMER_AGENT_DATA_ROOT) -> None:
        self.data_root = data_root.resolve()
        self._lock = RLock()
        self._scenario = load_customer_agent_scenario(self.data_root)
        self._retriever = self._build_retriever(self._scenario)

    def snapshot(self) -> tuple[LoadedCustomerAgentScenario, Bm25KnowledgeRetriever]:
        with self._lock:
            return self._scenario, self._retriever

    def system_prompt(self) -> CustomerAgentSystemPromptResponse:
        scenario, _ = self.snapshot()
        return CustomerAgentSystemPromptResponse(
            content=scenario.editable_system_prompt,
            source=scenario.system_prompt_source,
        )

    def update_system_prompt(self, content: str) -> CustomerAgentSystemPromptResponse:
        normalized = content.strip()
        if not normalized:
            raise ValueError("System Prompt 不能为空")
        if len(normalized.encode("utf-8")) > MAX_SYSTEM_PROMPT_BYTES:
            raise ValueError("System Prompt 不能超过 100 KB")
        path = self.data_root / SYSTEM_PROMPT_OVERRIDE_RELATIVE_PATH
        with self._lock:
            previous_content = (
                path.read_text(encoding="utf-8") if path.is_file() else None
            )
            _atomic_write_text(path, normalized + "\n")
            try:
                self._reload_locked()
            except Exception:
                if previous_content is None:
                    path.unlink(missing_ok=True)
                else:
                    _atomic_write_text(path, previous_content)
                # Restore the last known-good in-memory snapshot as well. If
                # restoration itself fails, keep the original save error as
                # the useful failure reported to the caller.
                try:
                    self._reload_locked()
                except Exception:
                    pass
                raise
            scenario = self._scenario
        return CustomerAgentSystemPromptResponse(
            content=scenario.editable_system_prompt,
            source=scenario.system_prompt_source,
            updated=True,
        )

    def rag_config(self) -> CustomerAgentRagConfigResponse:
        scenario, retriever = self.snapshot()
        return _rag_config_response(scenario, retriever)

    def rag_document_content(
        self,
        document_id: str,
    ) -> CustomerAgentRagDocumentContentResponse:
        """Return the original managed file, without runtime evaluation markers."""
        with self._lock:
            document = next(
                (
                    item
                    for item in self._scenario.knowledge_documents
                    if item.id == document_id and item.visibility != "untrusted"
                ),
                None,
            )
            if document is None:
                raise KeyError(document_id)
            config = next(
                (
                    item
                    for item in self._read_document_configs()
                    if item.get("id") == document_id
                ),
                None,
            )
            if config is None:
                raise KeyError(document_id)
            relative_path = Path(str(config.get("content_path", "")))
            content_path = (self.data_root / relative_path).resolve()
            if not content_path.is_relative_to(self.data_root):
                raise ValueError("RAG 文档路径不在受管数据目录中")
            if not content_path.is_file():
                raise KeyError(document_id)
            try:
                content = content_path.read_text(encoding="utf-8")
            except UnicodeDecodeError as error:
                raise ValueError("RAG 文档不是有效的 UTF-8 文本") from error
        return CustomerAgentRagDocumentContentResponse(
            id=document.id,
            title=document.title,
            visibility=document.visibility,  # type: ignore[arg-type]
            origin=document.origin,
            filename=document.original_filename,
            content=content,
        )

    async def upload_rag_document(
        self,
        upload: UploadFile,
        *,
        title: str | None,
        visibility: str,
    ) -> CustomerAgentRagMutationResponse:
        original_filename = Path(upload.filename or "").name
        suffix = Path(original_filename).suffix.lower()
        if not original_filename or suffix not in ALLOWED_RAG_SUFFIXES:
            raise ValueError("只支持上传 UTF-8 编码的 .md 或 .txt 文件")
        normalized_visibility = visibility.strip().lower()
        if normalized_visibility not in {"public", "private"}:
            raise ValueError("RAG 文档可见级别必须是 public 或 private")
        content_bytes = await _read_upload_limited(upload, MAX_RAG_UPLOAD_BYTES)
        try:
            content = content_bytes.decode("utf-8").strip()
        except UnicodeDecodeError as error:
            raise ValueError("RAG 文件必须使用 UTF-8 编码") from error
        if not content:
            raise ValueError("RAG 文件内容不能为空")
        normalized_title = (title or Path(original_filename).stem).strip()
        if not normalized_title:
            raise ValueError("RAG 文档标题不能为空")
        if len(normalized_title) > 200:
            raise ValueError("RAG 文档标题不能超过 200 个字符")

        document_id = _new_document_id(Path(original_filename).stem)
        stored_filename = f"{document_id}{suffix}"
        relative_content_path = RAG_UPLOADS_RELATIVE_DIR / stored_filename
        content_path = self.data_root / relative_content_path
        config_entry = {
            "id": document_id,
            "title": normalized_title,
            "visibility": normalized_visibility,
            "content_path": relative_content_path.as_posix(),
            "risk_flags": [],
            "origin": "upload",
            "original_filename": original_filename,
            "created_at": datetime.now(UTC).isoformat(),
        }

        with self._lock:
            documents = self._read_document_configs()
            _atomic_write_text(content_path, content + "\n")
            try:
                self._write_document_configs([*documents, config_entry])
                self._reload_locked()
            except Exception:
                content_path.unlink(missing_ok=True)
                self._write_document_configs(documents)
                self._reload_locked()
                raise
            rag = _rag_config_response(self._scenario, self._retriever)
            uploaded = next(
                document for document in rag.documents if document.id == document_id
            )
        return CustomerAgentRagMutationResponse(document=uploaded, rag=rag)

    def delete_rag_document(self, document_id: str) -> CustomerAgentRagMutationResponse:
        with self._lock:
            documents = self._read_document_configs()
            target = next(
                (item for item in documents if item.get("id") == document_id),
                None,
            )
            if target is None:
                raise KeyError(document_id)
            if target.get("origin", "builtin") != "upload":
                raise PermissionError("内置 RAG 文档不能从配置台删除")
            relative_path = Path(str(target.get("content_path", "")))
            expected_parent = (self.data_root / RAG_UPLOADS_RELATIVE_DIR).resolve()
            content_path = (self.data_root / relative_path).resolve()
            if not content_path.is_relative_to(expected_parent):
                raise ValueError("上传文档路径不在受管目录中")
            remaining = [item for item in documents if item is not target]
            trash_path = content_path.with_name(
                f".{content_path.name}.deleting-{uuid4().hex}"
            )
            if content_path.is_file():
                content_path.replace(trash_path)
            try:
                self._write_document_configs(remaining)
                self._reload_locked()
            except Exception:
                if trash_path.is_file():
                    trash_path.replace(content_path)
                self._write_document_configs(documents)
                self._reload_locked()
                raise
            trash_path.unlink(missing_ok=True)
            rag = _rag_config_response(self._scenario, self._retriever)
        return CustomerAgentRagMutationResponse(rag=rag)

    def clear_uploaded_rag_documents(self) -> int:
        """Remove session-uploaded documents while keeping built-in knowledge."""
        with self._lock:
            documents = self._read_document_configs()
            uploaded = [
                item for item in documents if item.get("origin", "builtin") == "upload"
            ]
            if not uploaded:
                return 0
            remaining = [item for item in documents if item not in uploaded]
            trash_paths: list[tuple[Path, Path]] = []
            try:
                for item in uploaded:
                    relative_path = Path(str(item.get("content_path", "")))
                    expected_parent = (self.data_root / RAG_UPLOADS_RELATIVE_DIR).resolve()
                    content_path = (self.data_root / relative_path).resolve()
                    if not content_path.is_relative_to(expected_parent):
                        raise ValueError("上传文档路径不在受管目录中")
                    if content_path.is_file():
                        trash_path = content_path.with_name(
                            f".{content_path.name}.clearing-{uuid4().hex}"
                        )
                        content_path.replace(trash_path)
                        trash_paths.append((content_path, trash_path))
                self._write_document_configs(remaining)
                self._reload_locked()
            except Exception:
                for content_path, trash_path in reversed(trash_paths):
                    if trash_path.is_file():
                        trash_path.replace(content_path)
                self._write_document_configs(documents)
                self._reload_locked()
                raise
            for _, trash_path in trash_paths:
                trash_path.unlink(missing_ok=True)
            return len(uploaded)

    def _read_document_configs(self) -> list[dict[str, Any]]:
        path = self.data_root / RAG_DOCUMENTS_RELATIVE_PATH
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("RAG documents.json 必须是数组")
        return [dict(item) for item in payload]

    def _write_document_configs(self, documents: list[dict[str, Any]]) -> None:
        path = self.data_root / RAG_DOCUMENTS_RELATIVE_PATH
        serialized = json.dumps(documents, ensure_ascii=False, indent=2) + "\n"
        _atomic_write_text(path, serialized)

    def _reload_locked(self) -> None:
        load_customer_agent_scenario.cache_clear()
        scenario = load_customer_agent_scenario(self.data_root)
        retriever = self._build_retriever(scenario)
        self._scenario = scenario
        self._retriever = retriever

    @staticmethod
    def _build_retriever(
        scenario: LoadedCustomerAgentScenario,
    ) -> Bm25KnowledgeRetriever:
        return Bm25KnowledgeRetriever(
            scenario.knowledge_documents,
            scenario.rag_config,
        )


async def _read_upload_limited(upload: UploadFile, maximum: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(min(64 * 1024, maximum + 1 - total))
        if not chunk:
            break
        total += len(chunk)
        if total > maximum:
            raise ValueError("RAG 文件不能超过 2 MB")
        chunks.append(chunk)
    return b"".join(chunks)


def _rag_config_response(
    scenario: LoadedCustomerAgentScenario,
    retriever: Bm25KnowledgeRetriever,
) -> CustomerAgentRagConfigResponse:
    chunk_counts: dict[str, int] = {}
    for chunk in retriever.chunks:
        chunk_counts[chunk.document.id] = chunk_counts.get(chunk.document.id, 0) + 1
    return CustomerAgentRagConfigResponse(
        retriever=scenario.rag_config.algorithm,
        tokenizer=scenario.rag_config.tokenizer,
        top_k=scenario.rag_config.top_k,
        chunk_count=len(retriever.chunks),
        documents=[
            CustomerAgentRagDocumentResponse(
                id=document.id,
                title=document.title,
                visibility=document.visibility,  # type: ignore[arg-type]
                origin=document.origin,
                filename=document.original_filename,
                character_count=len(document.content),
                chunk_count=chunk_counts.get(document.id, 0),
                deletable=document.origin == "upload",
            )
            for document in scenario.knowledge_documents
            if document.visibility != "untrusted"
        ],
    )


def _new_document_id(stem: str) -> str:
    normalized = _SAFE_STEM_PATTERN.sub("-", stem.lower()).strip("-")
    if not normalized:
        normalized = "document"
    return f"upload-{normalized[:48]}-{uuid4().hex[:10]}"


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
