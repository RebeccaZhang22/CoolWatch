from __future__ import annotations

import logging
import re
import unicodedata
import warnings
from dataclasses import dataclass
from typing import Any, Literal, Sequence

with warnings.catch_warnings():
    warnings.filterwarnings(
        "ignore",
        message="pkg_resources is deprecated as an API.*",
        category=UserWarning,
    )
    import jieba
from rank_bm25 import BM25Okapi


DocumentVisibility = Literal["public", "private", "untrusted"]

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:[-_.][a-z0-9]+)*|[\u4e00-\u9fff]+")
_MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_CHINESE_STOP_WORDS = frozenset(
    {
        "的",
        "了",
        "和",
        "与",
        "或",
        "是",
        "在",
        "把",
        "被",
        "请",
        "我",
        "你",
        "他",
        "她",
        "它",
        "这",
        "那",
        "一个",
        "一下",
        "什么",
        "怎么",
    }
)

# Keep index construction quiet when the API process starts. Retrieval errors
# still propagate normally and fail startup instead of silently degrading.
jieba.setLogLevel(logging.WARNING)


@dataclass(frozen=True)
class Bm25RagConfig:
    top_k: int
    min_score: float
    k1: float
    b: float
    max_chunk_chars: int
    chunk_overlap_chars: int
    algorithm: Literal["bm25_okapi"] = "bm25_okapi"
    tokenizer: Literal["jieba_search"] = "jieba_search"
    chunking_strategy: Literal["markdown_sections"] = "markdown_sections"


@dataclass(frozen=True)
class KnowledgeDocument:
    id: str
    title: str
    visibility: DocumentVisibility
    content: str
    risk_flags: tuple[str, ...] = ()
    origin: Literal["builtin", "upload"] = "builtin"
    original_filename: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class KnowledgeChunk:
    id: str
    document: KnowledgeDocument
    index: int
    heading: str | None
    content: str


@dataclass(frozen=True)
class RetrievedDocument:
    document: KnowledgeDocument
    chunk_id: str
    chunk_index: int
    heading: str | None
    content: str
    score: float
    rank: int
    included: bool
    decision: str
    matched_terms: tuple[str, ...] = ()
    token_count: int = 0
    retriever: Literal["bm25_okapi"] = "bm25_okapi"


class Bm25KnowledgeRetriever:
    """In-memory, sparse RAG index for the small customer-service corpus."""

    def __init__(
        self,
        documents: Sequence[KnowledgeDocument],
        config: Bm25RagConfig,
    ) -> None:
        self.config = config
        self.chunks = tuple(
            chunk
            for document in documents
            for chunk in _chunk_markdown_document(document, config)
        )
        if not self.chunks:
            raise ValueError("BM25 RAG index requires at least one knowledge chunk")
        tokenized_corpus = [
            tokenize_for_bm25(
                "\n".join(
                    part
                    for part in (
                        chunk.document.title,
                        chunk.heading,
                        chunk.content,
                    )
                    if part
                )
            )
            for chunk in self.chunks
        ]
        if any(not tokens for tokens in tokenized_corpus):
            raise ValueError("BM25 RAG chunks must contain indexable text")
        self._tokenized_corpus = tuple(tuple(tokens) for tokens in tokenized_corpus)
        self._index = BM25Okapi(
            tokenized_corpus,
            k1=config.k1,
            b=config.b,
        )

    def search(self, query: str) -> list[RetrievedDocument]:
        query_tokens = tokenize_for_bm25(query)
        if not query_tokens:
            return []
        scores = self._index.get_scores(query_tokens)
        ranked = sorted(
            enumerate(scores),
            key=lambda item: (-float(item[1]), item[0]),
        )
        results: list[RetrievedDocument] = []
        for chunk_index, raw_score in ranked:
            score = float(raw_score)
            if score < self.config.min_score:
                continue
            chunk = self.chunks[chunk_index]
            chunk_tokens = self._tokenized_corpus[chunk_index]
            chunk_vocabulary = set(chunk_tokens)
            matched_terms = tuple(
                dict.fromkeys(token for token in query_tokens if token in chunk_vocabulary)
            )
            rank = len(results) + 1
            decision = (
                f"BM25 Top-{rank} 召回；作为不可信检索数据发送给 Agent"
                if chunk.document.visibility == "untrusted"
                else f"BM25 Top-{rank} 召回并发送给 Agent"
            )
            results.append(
                RetrievedDocument(
                    document=chunk.document,
                    chunk_id=chunk.id,
                    chunk_index=chunk.index,
                    heading=chunk.heading,
                    content=chunk.content,
                    score=score,
                    rank=rank,
                    included=True,
                    decision=decision,
                    matched_terms=matched_terms,
                    token_count=len(chunk_tokens),
                )
            )
            if len(results) >= self.config.top_k:
                break
        return results


def tokenize_for_bm25(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text).lower()
    tokens: list[str] = []
    for candidate in jieba.lcut_for_search(normalized):
        token = candidate.strip()
        if not token or token in _CHINESE_STOP_WORDS:
            continue
        if _TOKEN_PATTERN.fullmatch(token):
            tokens.append(token)
    return tokens


def _chunk_markdown_document(
    document: KnowledgeDocument,
    config: Bm25RagConfig,
) -> list[KnowledgeChunk]:
    sections = _split_markdown_sections(document.content)
    raw_chunks: list[tuple[str | None, str]] = []
    for heading, section in sections:
        for piece in _split_long_text(
            section,
            max_chars=config.max_chunk_chars,
            overlap_chars=config.chunk_overlap_chars,
        ):
            raw_chunks.append((heading, piece))
    return [
        KnowledgeChunk(
            id=f"{document.id}::chunk-{index + 1:03d}",
            document=document,
            index=index,
            heading=heading,
            content=content,
        )
        for index, (heading, content) in enumerate(raw_chunks)
    ]


def _split_markdown_sections(text: str) -> list[tuple[str | None, str]]:
    sections: list[tuple[str | None, str]] = []
    current_heading: str | None = None
    current_lines: list[str] = []
    for line in text.splitlines():
        heading_match = _MARKDOWN_HEADING.match(line)
        if heading_match and current_lines:
            section = "\n".join(current_lines).strip()
            if section:
                sections.append((current_heading, section))
            current_lines = []
        if heading_match:
            current_heading = heading_match.group(2).strip()
        current_lines.append(line)
    section = "\n".join(current_lines).strip()
    if section:
        sections.append((current_heading, section))
    return sections


def _split_long_text(
    text: str,
    *,
    max_chars: int,
    overlap_chars: int,
) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        hard_end = min(len(text), start + max_chars)
        end = hard_end
        if hard_end < len(text):
            search_start = start + max(max_chars // 2, 1)
            candidates = [
                text.rfind(boundary, search_start, hard_end)
                for boundary in ("\n\n", "\n", "。", "；")
            ]
            natural_end = max(candidates)
            if natural_end > start:
                end = natural_end + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - overlap_chars, start + 1)
    return chunks
