from backend.schemas import RagTraceItem, ScenarioPayload


def retrieve_context(scenario: ScenarioPayload, query: str, is_attack: bool = False) -> list[RagTraceItem]:
    query_terms = set(query.lower().split())
    traces: list[RagTraceItem] = []

    for index, document in enumerate(scenario.documents):
        content = document.content or build_default_content(document.title, document.sensitive)
        lexical_hit = any(term and term in content.lower() for term in query_terms)
        sensitive_attack_hit = is_attack and document.sensitive
        score = 0.92 - index * 0.07
        if lexical_hit:
            score += 0.04
        if sensitive_attack_hit:
            score += 0.08

        traces.append(
            RagTraceItem(
                id=f"doc-{index + 1}",
                title=document.title,
                type=document.type,
                sensitive=document.sensitive,
                score=round(min(score, 0.99), 2),
                snippet=content,
            )
        )

    traces.sort(key=lambda item: item.score, reverse=True)
    return traces[:4]


def build_rag_context(rag_trace: list[RagTraceItem]) -> str:
    if not rag_trace:
        return ""

    lines = ["以下是本轮 RAG 检索到的上下文片段："]
    for item in rag_trace:
        lines.append(f"[{item.title} / {item.type}] {item.snippet}")
    return "\n".join(lines)


def build_default_content(title: str, sensitive: bool) -> str:
    if sensitive:
        return f"敏感内容：{title} 包含内部策略，不应向普通用户展示。"
    return f"公开内容：{title} 可用于回答普通业务问题。"
