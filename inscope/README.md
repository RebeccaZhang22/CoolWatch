# InScope 接入点

InScope 的契约 / 服务 / 客户端**不在本仓库**。单一来源是独立仓库 `../inscope-service`
（`inscope_contract` + `inscope_server` + `inscope_client` 三个包），这里只保留接入说明，
不再保存副本——副本一旦存在就会和服务端契约各自漂移（本目录此前保存的副本停留在
`score/flagged/threshold_logit` 形状，而服务端已改为 `probability/label`）。

## 部署形状：一个风险一个实例

每个启用的风险由一个独立 InScope 实例作答。实例在 `/info` 和每次 `/detect` 里都声明
自己只答哪一个风险，接入侧据此校验，接错地址会直接报错而不是静默用错检测器。

```bash
# 每个风险一个实例（不同端口，各自一份 checkpoint 与 composer profile）
export INSCOPE_MODEL_PATH=/path/Qwen3-8B-FP8
export INSCOPE_ENGINE_URL=http://127.0.0.1:30000
export INSCOPE_API_KEY=<你的 key>
export INSCOPE_PROBE_CHECKPOINT=/path/probes/attention-h1-obv3/best.pt
export INSCOPE_COMPOSER_PROFILE=observation_blocks_v3
inscope-serve --host 127.0.0.1 --port 8302
```

## CoolWatch 侧配置

```bash
export PROBE_BANK_ENABLED_RISKS=ipi
export PROBE_BANK_RISK_ENDPOINTS=ipi=http://127.0.0.1:8302
```

只配一个风险时可以省略 `PROBE_BANK_RISK_ENDPOINTS`，用 `PROBE_BANK_BASE_URL` 兜底；
启用多个风险时每个风险都必须给端点，缺一个会在启动时报错。

`/v1/moderations` 把各实例结果汇总成 `per_risk`，并为返回块级结果的实例带上
`blocks`（块级证据）、`coordinate_system`、`importance_semantics`，同时用 `probes`
记录实际应答的探针 ID 与 checkpoint sha256。`blocks[].source_message_indices`
指回调用方自己请求里的消息序号，`start`/`end` 是该消息正文内的字符偏移。
