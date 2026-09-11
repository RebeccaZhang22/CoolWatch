#!/usr/bin/env python3
"""Build the canonical portable report artifact from frozen audit metrics."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
METRICS_PATH = HERE / "metrics.json"
MANIFEST_PATH = ROOT / "data/activation_probe/audits/theft_large_v1/manifest.json"
ERRORS_PATH = HERE / "errors_at_trained_threshold.jsonl"
ARTIFACT_PATH = HERE / "artifact.json"
SQL_PATH = HERE / "audit_report_sources.sql"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def load_sql_queries() -> dict[str, str]:
    parts = re.split(
        r"^-- ([a-z_]+)\s*$",
        SQL_PATH.read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    )
    return {
        parts[index]: parts[index + 1].strip()
        for index in range(1, len(parts), 2)
    }


def build_artifact() -> dict[str, Any]:
    metrics = read_json(METRICS_PATH)
    dataset_manifest = read_json(MANIFEST_PATH)
    fixed = metrics["trained_threshold"]["held_out_audit_metrics"]
    profile = metrics["data"]["profile"]
    threshold = metrics["trained_threshold"]["probability_threshold"]
    policies = metrics["calibration_selected_fpr_policies"]
    descriptive = metrics["descriptive_held_out_accuracy_frontier"]
    generated_at = datetime.now(timezone.utc).isoformat()
    sql_queries = load_sql_queries()

    source_dataset = {
        "id": "audit-dataset",
        "label": "Activation Probe 大规模窃取审计集 v1",
        "path": "data/activation_probe/audits/theft_large_v1/cases.jsonl",
        "query": {
            "engine": "python3",
            "query": "python3 evaluations/activation_probe_theft_large_v1/run_audit.py generate",
            "description": "用固定随机种子生成 10,000 条组合式合成审计请求，并按模板族切分校准集和留出审计集。",
            "language": "shell",
            "executed_at": dataset_manifest["created_at"],
            "tables_used": ["data/activation_probe/audits/theft_large_v1/cases.jsonl"],
            "filters": [
                "single-turn requests only",
                "positive class: protected-asset theft intent",
                "negative class: topic-matched, legal in-distribution, and general benign requests",
            ],
            "metric_definitions": [
                "每条 case_id 和规范化 query 必须唯一。",
                "校准集与留出审计集按 template_family 隔离。",
            ],
        },
    }
    source_predictions = {
        "id": "probe-predictions",
        "label": "v16 Activation Probe 逐条原始评分",
        "path": "evaluations/activation_probe_theft_large_v1/predictions.jsonl",
        "query": {
            "engine": "ProspectMonitor ActivationProbeGuard",
            "query": "python3 evaluations/activation_probe_theft_large_v1/run_audit.py run --concurrency 16",
            "description": "使用当前法规条款 Agent 的渲染后 System Prompt，通过修改版 vLLM 对每条请求执行一次 v16 隐藏层激活探针评分；不调用 SafeGauge。",
            "language": "shell",
            "executed_at": metrics["created_at"],
            "tables_used": ["evaluations/activation_probe_theft_large_v1/predictions.jsonl"],
            "filters": ["probe_id=activation-probe-qwen3-8b-theft-unified-v16-multilayer-mlp"],
            "metric_definitions": ["score 为 MLP logit 的 sigmoid 概率。"],
        },
    }
    source_metrics = {
        "id": "audit-metrics",
        "label": "Activation Probe 审计指标与阈值扫描",
        "path": "evaluations/activation_probe_theft_large_v1/metrics.json",
        "query": {
            "engine": "python3 + scikit-learn",
            "query": "python3 evaluations/activation_probe_theft_large_v1/run_audit.py analyze",
            "description": "从冻结逐条评分计算训练阈值指标、分类切片、校准集阈值策略以及留出集描述性准确率上界。",
            "language": "shell",
            "executed_at": metrics["created_at"],
            "tables_used": [
                "evaluations/activation_probe_theft_large_v1/predictions.jsonl",
                "data/activation_probe/audits/theft_large_v1/cases.jsonl",
            ],
            "filters": [
                "threshold selection uses calibration split only",
                "held-out audit labels are excluded from deployable threshold selection",
            ],
            "metric_definitions": [
                "召回率 = TP / (TP + FN)",
                "误伤率 = FP / (FP + TN)",
                "准确率 = (TP + TN) / N；本审计正负类各 50%",
                "区间估计使用双侧 95% Wilson score interval",
            ],
        },
    }
    def sql_source(
        source_id: str,
        label: str,
        query_id: str,
        description: str,
        tables_used: list[str],
    ) -> dict[str, Any]:
        return {
            "id": source_id,
            "label": label,
            "path": "evaluations/activation_probe_theft_large_v1/audit_report_sources.sql",
            "query": {
                "engine": "SQLite 3.51",
                "sql": sql_queries[query_id],
                "description": description,
                "language": "sql",
                "executed_at": metrics["created_at"],
                "tables_used": tables_used,
            },
        }

    source_fixed_sql = sql_source(
        "fixed-metrics-sql",
        "固定训练阈值指标复核 SQL",
        "fixed_metrics",
        "在留出审计集上复算 TP、TN、FP、FN、召回率、误伤率与准确率。",
        ["predictions"],
    )
    source_category_sql = sql_source(
        "category-metrics-sql",
        "攻击类别切片复核 SQL",
        "category_metrics",
        "按窃取资产类别汇总攻击与主题相近正常请求。",
        ["predictions"],
    )
    source_policy_sql = sql_source(
        "fpr-policy-sql",
        "误伤率阈值策略报告 SQL",
        "fpr_policy",
        "读取校准集选阈值后在留出审计集上的表现。",
        ["threshold_policy"],
    )
    source_oracle_sql = sql_source(
        "oracle-frontier-sql",
        "留出集描述性准确率上界 SQL",
        "oracle_frontier",
        "读取不同观察误伤率上限下的描述性准确率上界。",
        ["oracle_frontier"],
    )
    source_composition_sql = sql_source(
        "composition-sql",
        "审计集构成复核 SQL",
        "composition",
        "按校准/留出切分和正负标签汇总数据规模。",
        ["dataset_composition"],
    )
    source_errors_sql = sql_source(
        "errors-sql",
        "固定阈值错误案例排序 SQL",
        "errors",
        "按错误置信度排序固定阈值下的漏报和误伤案例。",
        ["classification_errors"],
    )
    sources = [
        source_dataset,
        source_predictions,
        source_metrics,
        source_fixed_sql,
        source_category_sql,
        source_policy_sql,
        source_oracle_sql,
        source_composition_sql,
        source_errors_sql,
    ]

    headline = [{
        "recall": fixed["recall"],
        "false_positive_rate": fixed["false_positive_rate"],
        "accuracy": fixed["accuracy"],
        "auroc": fixed["auroc"],
        "sample_count": fixed["sample_count"],
        "threshold": threshold,
    }]
    category_rows = []
    category_labels = {
        "system_prompt": "System Prompt 窃取",
        "rag": "私有 RAG 窃取",
        "cot": "私有 CoT 窃取",
        "skill": "私有 Skill/tool 窃取",
    }
    for category, values in metrics["trained_threshold"]["held_out_by_category_with_topic_matched_negatives"].items():
        category_rows.append({
            "category": category,
            "category_label": category_labels[category],
            "recall": values["recall"],
            "false_positive_rate": values["false_positive_rate"],
            "accuracy": values["accuracy"],
            "sample_count": values["sample_count"],
            "false_negative": values["false_negative"],
            "false_positive": values["false_positive"],
        })
    category_rows.sort(key=lambda row: row["recall"])

    policy_rows = []
    for row in policies:
        calibration = row["calibration_metrics"]
        heldout = row["held_out_audit_metrics"]
        policy_rows.append({
            "target_fpr_cap": row["target_fpr_cap"],
            "selected_threshold": row["selected_probability_threshold"],
            "calibration_fpr": calibration["false_positive_rate"],
            "heldout_actual_fpr": heldout["false_positive_rate"],
            "heldout_recall": heldout["recall"],
            "heldout_accuracy": heldout["accuracy"],
            "heldout_precision": heldout["precision"],
        })
    policy_chart_rows = []
    for row in policy_rows:
        for metric_field, metric_label in (
            ("heldout_recall", "召回率"),
            ("heldout_accuracy", "准确率"),
        ):
            policy_chart_rows.append({
                "target_fpr_cap": row["target_fpr_cap"],
                "metric": metric_label,
                "value": row[metric_field],
                "selected_threshold": row["selected_threshold"],
                "heldout_actual_fpr": row["heldout_actual_fpr"],
            })
    oracle_rows = []
    for row in descriptive:
        heldout = row["held_out_audit_metrics"]
        oracle_rows.append({
            "target_fpr_cap": row["target_fpr_cap"],
            "selected_threshold": row["selected_probability_threshold"],
            "observed_fpr": heldout["false_positive_rate"],
            "recall": heldout["recall"],
            "accuracy": heldout["accuracy"],
            "deployment_eligible": False,
        })

    composition_rows = []
    grouped: dict[tuple[str, int], int] = {}
    for row in dataset_manifest["composition"]:
        key = (row["split"], int(row["label"]))
        grouped[key] = grouped.get(key, 0) + int(row["count"])
    for split in ("calibration", "audit"):
        composition_rows.append({
            "split": "校准集" if split == "calibration" else "留出审计集",
            "attack_count": grouped[(split, 1)],
            "safe_count": grouped[(split, 0)],
            "total_count": grouped[(split, 1)] + grouped[(split, 0)],
        })

    error_rows = []
    for row in read_jsonl(ERRORS_PATH):
        score = float(row["score"])
        label = int(row["label"])
        prediction = int(row["prediction_at_trained_threshold"])
        error_rows.append({
            "error_type": "漏报" if label == 1 else "误伤",
            "category": category_labels.get(row["category"], row["category"]),
            "language": row["language"],
            "score": score,
            "threshold": threshold,
            "error_confidence": 1.0 - score if label == 1 else score,
            "query": row["query"][:100],
            "label": label,
            "prediction": prediction,
        })
    error_rows.sort(key=lambda row: row["error_confidence"], reverse=True)
    error_rows = error_rows[:30]

    policy_1pct = next(row for row in policy_rows if row["target_fpr_cap"] == 0.01)
    strongest_category = max(category_rows, key=lambda row: row["recall"])
    weakest_category = min(category_rows, key=lambda row: row["recall"])
    latency = profile["probe_latency_ms"]

    cards = [
        {
            "id": "card-recall",
            "description": "留出审计集中的 3,496 条窃取攻击被识别的比例。",
            "dataset": "headline",
            "sourceId": "fixed-metrics-sql",
            "metrics": [{"label": "召回率", "field": "recall", "format": "percent"}],
        },
        {
            "id": "card-fpr",
            "description": "留出审计集中正常请求被误判为攻击的比例。",
            "dataset": "headline",
            "sourceId": "fixed-metrics-sql",
            "metrics": [{"label": "误伤率", "field": "false_positive_rate", "format": "percent"}],
        },
        {
            "id": "card-accuracy",
            "description": "在正负类各 50% 的留出审计集上计算。",
            "dataset": "headline",
            "sourceId": "fixed-metrics-sql",
            "metrics": [{"label": "准确率", "field": "accuracy", "format": "percent"}],
        },
        {
            "id": "card-auroc",
            "description": "不依赖单一阈值的排序质量。",
            "dataset": "headline",
            "sourceId": "fixed-metrics-sql",
            "metrics": [{"label": "AUROC", "field": "auroc", "format": "number"}],
        },
    ]

    charts = [
        {
            "id": "chart-category-recall",
            "title": "四类窃取攻击的召回率",
            "subtitle": "固定使用 v16 训练阈值；每类同时包含主题相近的正常请求",
            "showDescription": True,
            "intent": "comparison",
            "question": "固定阈值对哪类受保护资产的窃取请求识别最弱？",
            "rationale": "四个离散类别使用按召回率排序的横向条形图，便于比较长中文标签。",
            "type": "horizontalBar",
            "dataset": "category_metrics",
            "sourceId": "category-metrics-sql",
            "encodings": {
                "x": {"field": "category_label", "type": "nominal", "label": "攻击类别"},
                "y": {"field": "recall", "type": "quantitative", "format": "percent", "label": "召回率"},
                "tooltip": [
                    {"field": "recall", "type": "quantitative", "format": "percent", "label": "召回率"},
                    {"field": "false_positive_rate", "type": "quantitative", "format": "percent", "label": "误伤率"},
                    {"field": "sample_count", "type": "quantitative", "format": "number", "label": "样本数"},
                ],
            },
            "valueFormat": "percent",
            "layout": "full",
        },
        {
            "id": "chart-fpr-policy",
            "title": "校准误伤率约束与留出集表现",
            "subtitle": "阈值仅在校准集选择；横轴是目标误伤率上限，曲线是留出审计集实际结果",
            "showDescription": True,
            "intent": "trend",
            "question": "收紧可接受误伤率时，留出集召回率和准确率如何变化？",
            "rationale": "目标误伤率上限是有序连续变量，折线能直接展示不同运维约束下的性能变化。",
            "type": "line",
            "dataset": "fpr_policy_chart",
            "sourceId": "fpr-policy-sql",
            "encodings": {
                "x": {"field": "target_fpr_cap", "type": "quantitative", "format": "percent", "label": "目标误伤率上限"},
                "y": {"field": "value", "type": "quantitative", "format": "percent", "label": "留出集比例"},
                "color": {"field": "metric", "type": "nominal", "label": "指标"},
                "tooltip": [
                    {"field": "selected_threshold", "type": "quantitative", "format": "number", "label": "概率阈值"},
                    {"field": "heldout_actual_fpr", "type": "quantitative", "format": "percent", "label": "实际误伤率"},
                ],
            },
            "valueFormat": "percent",
            "layout": "full",
        },
    ]

    tables = [
        {
            "id": "table-fpr-policy",
            "title": "校准集选阈值后的留出集结果",
            "subtitle": "误伤率上限用于校准集；留出集实际误伤率可能偏离目标",
            "showDescription": True,
            "dataset": "fpr_policy",
            "defaultSort": {"field": "target_fpr_cap", "direction": "asc"},
            "density": "spacious",
            "sourceId": "fpr-policy-sql",
            "layout": "full",
            "columns": [
                {"field": "target_fpr_cap", "label": "校准 FPR 上限", "format": "percent"},
                {"field": "selected_threshold", "label": "阈值", "format": "number"},
                {"field": "heldout_actual_fpr", "label": "留出 FPR", "format": "percent"},
                {"field": "heldout_recall", "label": "留出召回率", "format": "percent"},
                {"field": "heldout_accuracy", "label": "留出准确率", "format": "percent"},
            ],
        },
        {
            "id": "table-oracle-frontier",
            "title": "留出集内的描述性准确率上界",
            "subtitle": "阈值查看过留出标签，因此只用于理解模型上界，不可直接部署",
            "showDescription": True,
            "dataset": "oracle_frontier",
            "defaultSort": {"field": "target_fpr_cap", "direction": "asc"},
            "density": "spacious",
            "sourceId": "oracle-frontier-sql",
            "layout": "full",
            "columns": [
                {"field": "target_fpr_cap", "label": "观察 FPR 上限", "format": "percent"},
                {"field": "selected_threshold", "label": "事后阈值", "format": "number"},
                {"field": "observed_fpr", "label": "实际 FPR", "format": "percent"},
                {"field": "recall", "label": "召回率", "format": "percent"},
                {"field": "accuracy", "label": "准确率", "format": "percent"},
            ],
        },
        {
            "id": "table-composition",
            "title": "校准集与留出审计集构成",
            "subtitle": "按模板族切分；两个集合均保持正负类平衡",
            "showDescription": True,
            "dataset": "composition",
            "defaultSort": {"field": "total_count", "direction": "desc"},
            "density": "spacious",
            "sourceId": "composition-sql",
            "layout": "full",
            "columns": [
                {"field": "split", "label": "数据集", "type": "text"},
                {"field": "attack_count", "label": "攻击请求", "format": "number"},
                {"field": "safe_count", "label": "正常请求", "format": "number"},
                {"field": "total_count", "label": "合计", "format": "number"},
            ],
        },
    ]
    if error_rows:
        tables.append({
            "id": "table-errors",
            "title": "固定阈值下置信度最高的错误案例",
            "subtitle": "最多展示 30 条，用于定位漏报和误伤模式",
            "showDescription": True,
            "dataset": "errors",
            "defaultSort": {"field": "error_confidence", "direction": "desc"},
            "density": "dense",
            "sourceId": "errors-sql",
            "layout": "full",
            "columns": [
                {"field": "error_type", "label": "错误类型", "type": "text"},
                {"field": "category", "label": "类别", "type": "text"},
                {"field": "error_confidence", "label": "错误置信度", "format": "percent"},
                {"field": "query", "label": "请求", "type": "text"},
            ],
        })

    blocks: list[dict[str, Any]] = [
        {"id": "title", "type": "markdown", "body": "# Activation Probe 大规模窃取数据审计"},
        {
            "id": "technical-summary",
            "type": "markdown",
            "sourceId": "audit-metrics",
            "body": (
                "## 技术摘要\n\n"
                f"在固定的 v16 训练阈值 `{threshold:.6f}` 下，留出审计集共 "
                f"{fixed['sample_count']:,} 条请求，召回率为 **{pct(fixed['recall'])}**，"
                f"误伤率为 **{pct(fixed['false_positive_rate'])}**，准确率为 "
                f"**{pct(fixed['accuracy'])}**，AUROC 为 **{fixed['auroc']:.5f}**。"
                "这些数字说明探针在本次合成、单一法规 Agent 上下文中有较强区分能力，但不等同于真实流量表现。"
            ),
        },
        {"id": "headline-strip", "type": "metric-strip", "cardIds": ["card-recall", "card-fpr", "card-accuracy", "card-auroc"]},
        {
            "id": "category-finding",
            "type": "markdown",
            "sourceId": "audit-metrics",
            "body": (
                "## 固定训练阈值下的分类表现\n\n"
                f"四类攻击中，召回率最高的是 **{strongest_category['category_label']}** "
                f"（{pct(strongest_category['recall'])}），最低的是 "
                f"**{weakest_category['category_label']}**（{pct(weakest_category['recall'])}）。"
                "分类指标均加入同主题 hard negative，避免只看攻击样本得出虚高结论。"
            ),
        },
        {"id": "category-chart", "type": "chart", "chartId": "chart-category-recall", "layout": "full"},
        {
            "id": "fpr-finding",
            "type": "markdown",
            "sourceId": "audit-metrics",
            "body": (
                "## 误伤率约束下的准确率\n\n"
                "可部署阈值只在校准集选择，再应用到留出集。以校准误伤率上限 1% 为例，"
                f"选择的阈值为 `{policy_1pct['selected_threshold']:.6f}`；留出集实际误伤率 "
                f"**{pct(policy_1pct['heldout_actual_fpr'])}**、召回率 "
                f"**{pct(policy_1pct['heldout_recall'])}**、准确率 "
                f"**{pct(policy_1pct['heldout_accuracy'])}**。"
                "准确率依赖本审计的 50/50 类别比例，线上容量规划应优先使用召回率和误伤率。"
            ),
        },
        {"id": "fpr-chart", "type": "chart", "chartId": "chart-fpr-policy", "layout": "full"},
        {"id": "fpr-table", "type": "table", "tableId": "table-fpr-policy", "layout": "full"},
        {
            "id": "oracle-note",
            "type": "markdown",
            "sourceId": "audit-metrics",
            "body": (
                "## 描述性上界不能直接当线上阈值\n\n"
                "下面的表回答“如果只描述这批留出数据，在给定误伤率范围内最高能达到多少准确率”。"
                "它查看了留出标签，存在测试集过拟合，只能用于诊断；真正上线必须用新的校准数据重新选阈值。"
            ),
        },
        {"id": "oracle-table", "type": "table", "tableId": "table-oracle-frontier", "layout": "full"},
        {
            "id": "scope",
            "type": "markdown",
            "sourceId": "audit-dataset",
            "body": (
                "## 数据范围与指标口径\n\n"
                "审计集包含 10,000 条唯一单轮请求：5,000 条窃取攻击和 5,000 条正常请求。"
                "攻击覆盖 System Prompt、私有 RAG、私有 CoT、私有 Skill/tool；正常请求包括 "
                "3,000 条主题相近 hard negative、1,000 条法规咨询和 1,000 条通用问题。"
                "中英文各占一半，历史训练/测试 query 的规范化精确重合为 0。误伤率定义为正常请求中的误报比例。"
            ),
        },
        {"id": "composition-table", "type": "table", "tableId": "table-composition", "layout": "full"},
        {
            "id": "methodology",
            "type": "markdown",
            "sourceId": "probe-predictions",
            "body": (
                "## 方法与复现路径\n\n"
                "每条请求都与当前法规条款 Agent 的完整渲染后 System Prompt 组成单轮 replay，"
                "发送到修改版 vLLM。v16 探针读取 Qwen3-8B 第 21/22/23 个 block 的末尾 token "
                "residual activation，标准化、拼接后由小型 MLP 打分。请求只生成 1 个 token 以触发 prefill，"
                "不使用业务回答判断结果，也没有调用 SafeGauge。"
            ),
        },
        {
            "id": "limitations",
            "type": "markdown",
            "sourceId": "audit-metrics",
            "body": (
                "## 局限性、误差与稳健性\n\n"
                "本结果应按“可带限制分享”处理：数据是组合模板生成的合成压力测试，不是独立采集的真实攻击流量；"
                "主审计只使用一个法规 Agent System Prompt；虽然校准集和审计集按模板族隔离，但仍共享主题词汇。"
                f"探针单请求中位延迟为 **{latency['median']:.0f} ms**，P95 为 "
                f"**{latency['p95']:.0f} ms**。95% Wilson 区间已保存在指标文件中。"
            ),
        },
    ]
    if error_rows:
        blocks.extend([
            {
                "id": "error-analysis",
                "type": "markdown",
                "sourceId": "audit-metrics",
                "body": (
                    "## 错误案例显示下一轮应补哪些数据\n\n"
                    f"固定训练阈值共产生 {fixed['false_negative']} 条漏报和 "
                    f"{fixed['false_positive']} 条误伤。下表优先展示离阈值最远的错误，"
                    "适合用于补充 hard negative、隐式改写攻击和更自然的口语表达。"
                ),
            },
            {"id": "errors-table", "type": "table", "tableId": "table-errors", "layout": "full"},
        ])
    blocks.extend([
        {
            "id": "next-steps",
            "type": "markdown",
            "body": (
                "## 建议的下一步\n\n"
                "1. 从真实或人工独立撰写的请求中建立新的冻结外部审计集，再验证本次阈值策略。\n"
                "2. 优先围绕最弱攻击类别和高置信误伤补数据，不在本留出集上重新训练后继续报同一结果。\n"
                "3. 根据线上正常流量基率，用召回率和误伤率估算每日告警量，再确定可接受阈值。\n"
                "4. 增加多 System Prompt、长上下文和多轮 replay 审计，检验当前单轮结论是否稳定。"
            ),
        },
        {
            "id": "further-questions",
            "type": "markdown",
            "body": (
                "## 仍需回答的问题\n\n"
                "真实用户流量中的攻击基率是多少？不同业务 Agent 的 System Prompt 是否会系统性改变分数分布？"
                "多轮历史、工具结果和超长 RAG 上下文加入后，当前阈值是否仍能维持同样的误伤率？"
            ),
        },
    ])

    manifest = {
        "version": 1,
        "surface": "report",
        "title": "Activation Probe 大规模窃取数据审计",
        "description": "v16 Activation Probe 在 10,000 条合成单轮请求上的召回率、误伤率、准确率与阈值约束分析。",
        "generatedAt": generated_at,
        "cards": cards,
        "charts": charts,
        "tables": tables,
        "sources": sources,
        "blocks": blocks,
    }
    snapshot = {
        "version": 1,
        "generatedAt": generated_at,
        "status": "ready",
        "datasets": {
            "headline": headline,
            "category_metrics": category_rows,
            "fpr_policy": policy_rows,
            "fpr_policy_chart": policy_chart_rows,
            "oracle_frontier": oracle_rows,
            "composition": composition_rows,
            "errors": error_rows,
        },
    }
    return {
        "surface": "report",
        "manifest": manifest,
        "snapshot": snapshot,
        "sources": sources,
    }


def main() -> None:
    artifact = build_artifact()
    ARTIFACT_PATH.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"artifact": str(ARTIFACT_PATH)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
