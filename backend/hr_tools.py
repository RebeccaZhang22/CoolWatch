"""Server-side HR tools. PDF files never enter model requests."""
from pathlib import Path

from pypdf import PdfReader


def parse_resume_pdf(path: Path) -> str:
    """Extract the complete text layer, including visually hidden white text."""
    try:
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise ValueError('简历 PDF 已加密，请提供可读取的文件')
        text = '\n\n'.join(page.extract_text() or '' for page in reader.pages).strip()
    except ValueError:
        raise
    except Exception as error:
        raise ValueError('简历 PDF 解析失败，请检查文件内容') from error
    if not text:
        raise ValueError('简历 PDF 没有可提取的文字层，请提供文字版 PDF；不会将 PDF 交给模型解析')
    return text


def rank_resumes(query, documents, config, *, limit=5):
    """BM25 ranking with positive IDF, including one-file workspace corpora.

    Score = sum(qtf * log(1 + (N-df+0.5)/(df+0.5)) *
                tf*(k1+1)/(tf+k1*(1-b+b*dl/avgdl))).
    Each document uses its best matching chunk; ties sort by source ID.
    """
    from collections import Counter
    from math import log1p
    from backend.customer_agent_rag import Bm25KnowledgeRetriever, RetrievedDocument, tokenize_for_bm25

    query_terms = Counter(tokenize_for_bm25(query))
    if not documents or not query_terms:
        return [], []
    chunks = Bm25KnowledgeRetriever(documents, config).chunks
    counts = [Counter(tokenize_for_bm25('\n'.join(
        p for p in (c.document.title, c.heading, c.content) if p))) for c in chunks]
    frequencies = Counter(term for count in counts for term in count)
    lengths = [sum(count.values()) for count in counts]
    average = sum(lengths) / len(lengths)
    best = {}
    for chunk, count, length in zip(chunks, counts, lengths):
        matched = tuple(term for term in query_terms if term in count)
        if not matched:
            continue
        score = sum(query_terms[term] * log1p((len(chunks)-frequencies[term]+0.5)/(frequencies[term]+0.5))
                    * count[term]*(config.k1+1)
                    / (count[term]+config.k1*(1-config.b+config.b*length/average)) for term in matched)
        hit = RetrievedDocument(document=chunk.document, chunk_id=chunk.id, chunk_index=chunk.index,
            heading=chunk.heading, content=chunk.content, score=score, rank=0, included=True,
            decision='BM25 正 IDF 相关度排序；每份文档取最佳命中片段', matched_terms=matched, token_count=length,
            retriever='bm25_positive_idf')
        previous = best.get(chunk.document.id)
        if previous is None or score > previous.score:
            best[chunk.document.id] = hit
    from dataclasses import replace
    hits = sorted(best.values(), key=lambda h: (-h.score, h.document.id))[:limit]
    hits = [replace(hit, rank=index) for index, hit in enumerate(hits, 1)]
    rows = [dict(rank=hit.rank, document_id=hit.document.id, title=hit.document.title,
        relevance_score=round(hit.score, 6), matched_terms=list(hit.matched_terms),
        source_chunk_id=hit.chunk_id, text=hit.content) for hit in hits]
    return rows, hits
