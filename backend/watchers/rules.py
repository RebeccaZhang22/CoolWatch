from dataclasses import dataclass


GUARD_NAMES = {
    "baseline": "无防护",
    "qwen_guard": "Qwen3 安全护栏",
    "llama_prompt_guard": "Llama 安全护栏",
    "netease_yidun": "易盾文本安全",
    "safegauge": "后缀概率探针",
    "inline_probing": "生成内探针",
    "rule_guard": "规则防护",
    "custom_guard": "自定义防护",
}

ATTACK_KEYWORDS = [
    "system prompt",
    "系统提示词",
    "隐藏指令",
    "完整上下文",
    "检索到的全部",
    "内部",
    "敏感",
    "忽略之前",
    "ignore",
]


@dataclass
class GuardDecision:
    blocked: bool
    status: str
    connected: bool
    query_risk: bool | None
    matched_labels: list[str]
    note: str


def detect_attack_intent(message: str, is_attack: bool) -> list[str]:
    text = message.lower()
    labels = [keyword for keyword in ATTACK_KEYWORDS if keyword.lower() in text]
    if is_attack and not labels:
        labels.append("manual_attack")
    return labels


def evaluate_input_guard(guard_id: str, query_risky: bool, matched_labels: list[str]) -> GuardDecision:
    if guard_id == "baseline":
        return GuardDecision(
            blocked=False,
            status="未启用护栏",
            connected=True,
            query_risk=None,
            matched_labels=[],
            note="固定对照，不对输入做拦截或改写。",
        )

    if guard_id in {"qwen_guard", "llama_prompt_guard", "netease_yidun", "safegauge", "inline_probing"}:
        return GuardDecision(
            blocked=False,
            status="待接入",
            connected=False,
            query_risk=None,
            matched_labels=[],
            note="外部护栏模型尚未接入，本轮只保留检测位，不拦截输入，也不影响模型输出。",
        )

    if guard_id in {"rule_guard", "custom_guard"}:
        return GuardDecision(
            blocked=query_risky,
            status="命中风险" if query_risky else "未命中",
            connected=True,
            query_risk=query_risky,
            matched_labels=matched_labels,
            note="本地规则检测只用于调试演示，不改写 agent 输出。",
        )

    return GuardDecision(
        blocked=False,
        status="未知方法",
        connected=False,
        query_risk=None,
        matched_labels=[],
        note="未识别的输入护栏方法。",
    )
