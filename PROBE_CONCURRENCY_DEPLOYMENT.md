# 2B 影子服务：64 并发部署

## 已实现

- GPU 0、单份 Qwen3.5-2B、一个 GPU worker；HTTP 异步并发进入有界 microbatcher。
- 每批最多 64 请求，累计最多 65,536 输入 tokens；收集窗口 10 ms；HTTP 在途上限 128。超过容量返回 429 + Retry-After，不无限排队。
- 每批一起调用 Engine.generate(list_of_input_ids)，不是对每条 HTTP 请求分别调用。按 request ID 提取 activation、恢复响应对应关系。
- 每条请求仍共用一次真实输入 prefill 供 harmful / prompt_leakage / ipi 打分。当前每批另有一次 dummy flush。保留 no-thinking 模板、层位、T-1/T-3 和原 checkpoint 阈值。
- 真实 forward 批大小由 activation 文件里的 request IDs 统计，响应字段 `prefill_batch_sizes`，不把 HTTP 并发数冒充 GPU batch size。
- 总请求 deadline 60 秒，过期排队项不再执行；2 MiB 请求体、128 条消息、16,384 tokens 单请求上限。非法模板返回 400，不污染其他批次。
- 批次执行失败会标记 worker 不可用、返回 503；`/health/ready` 返回非健康。运行中的 GPU 计算不能被客户端超时立即抢占，配置了引擎 60 秒 watchdog；需要进程监管/容器探针重启故障实例。
- 清理每批 spool 文件，包括 dummy，避免 upstream 未消费 dummy 特征长期累积。没有移除状态保护，而是只允许批处理 worker 持有引擎。
- 公共 API 保留 429/504，并返回 detector_overloaded / detector_timeout。银行模式业务输入/工具返回后的检测失败会中止后续业务，而不是当作安全继续回答。

## 实测范围（A800 80GB，2026-09-10）

每波 64 个并发 HTTP 请求，四种良性/窃取样例轮换；与旧串行服务逐项比较 tokens、bank SHA、四个 entry 分数和三领域判定。不是持续满负载容量承诺。

| 每请求输入 tokens | 波数 | 每波总耗时 | 吞吐 | 实际 GPU prefill 批大小 |
|---|---:|---:|---:|---|
| 20–26 | 3 | 0.39–0.76 s | 84–165 req/s | 首波 64，后续自动合批 2–21 |
| 1,820–1,826 | 3 | 2.24–2.31 s | 27.8–28.5 req/s | 3–35 |
| 7,220–7,226 | 3 | 8.23–8.59 s | 7.45–7.78 req/s | 1–9 |
| 16,220–16,226 | 2 | 19.78–20.44 s | 3.13–3.24 req/s | 4 |

共 704 条压力请求通过，零 HTTP 失败，样例风险判定与串行一致；最大分数漂移约 0.0089（BF16 批形状变化），不声称位级一致或阈值附近永不翻转。冷态首次遇到新批形状曾有约 8.6 秒 JIT 开销，上线前需代表性预热。

候选服务在另一份旧影子服务仍存在时，长批测试后显存占用约 26.9 GiB；正式单实例静态池可能更大。必须按当前 GPU 和输入长度重新测峰值，不能把此前串行 17–18 GiB 或 24GB 卡建议用于此配置。

正式切换后 GPU 0 仅一份 2B：64 并发 1.8K 波次 2.20/2.31 秒、16.2K 波次 19.59 秒，均通过；长批运行后进程占用 29,978 MiB（约 29.3 GiB，非高频采样峰值）。API 路由 → 真实候选 GPU → Python SDK schema 的 64 并发也已通过（测试鉴权、不写真实用量账本）。

“64 并发”表示能同时接受并完成这类 64 请求波次，不意味着 64 条 16K 输入会放进同一个 forward，更不意味着 64 QPS、零等待。长请求分批由 token 预算决定。若需要 64 条 16K 请求低延迟完成，应增加独立 2B 副本/更多 GPU，并做负载均衡。

## 启动及检查

```bash
CUDA_VISIBLE_DEVICES=0 bash vllm_setups/run_probe_bank_qwen35_2b.sh
curl -fsS http://127.0.0.1:8302/health/ready
curl -fsS http://127.0.0.1:8302/batch-stats
```

可覆盖参数：PROBE_MAX_BATCH=64、PROBE_BATCH_TOKENS=65536、PROBE_MAX_INFLIGHT=128、PROBE_BATCH_WAIT_MS=10、PROBE_REQUEST_TIMEOUT=60、PROBE_MEM_FRACTION=0.2。切勿直接增加 Uvicorn workers；每个模型副本需独立 GPU/显存预算和 spool。仅监听 loopback，外部通过鉴权业务 API 访问。

压测（使用原项目的 `.venv-sglang/bin/python`，在本项目目录运行）：

```bash
/ssd/workspace/djs/zhuanli/.venv-sglang/bin/python -m unittest regression.test_probe_batcher
/ssd/workspace/djs/zhuanli/.venv-sglang/bin/python regression/probe_batch_load.py --url http://127.0.0.1:8302 --baseline '' --concurrency 64 --rounds 3 --repeats 200
```

`--repeats 0/200/800/1800` 对应上表四档输入；`--baseline` 指向独立旧服务可以对照，否则用当前服务单请求结果作参考。生产压测客户端建议 70 秒超时，不做立即无限重试。

## 尚需生产验收

真实业务长度/工具轨迹分布，持续 30–60 分钟 64 客户端闭环负载，突发超载及故障恢复、敏感数据日志策略、token 级租户限流、P95/P99 SLO。不要把并发验收等同于模型误报率/整套业务的最终验收。

按用户最新要求，`ProbeBankGuard.moderate` 在发送检测请求时创建过滤后的消息列表：保留索引 0 的 system，去掉后续 system；其余 user/assistant/tool、工具定义均保留。业务消息及工具执行逻辑不修改，也不把中途 system 合并到首条。公共 API 用量 token 数对应过滤后实际检测输入，原始消息日志仍保留调用方提交内容。已用含多条中途 system 和工具返回的输入实测，与手动过滤后结果一致，且原始列表未变。此处理仅在本项目检测适配层，直接访问私有 `/detect` 的调用方仍须遵循模型模板。
