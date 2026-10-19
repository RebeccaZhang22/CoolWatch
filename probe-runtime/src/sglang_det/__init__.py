"""sglang_det：ad-hoc unified bypass-detector sglang server（Phase D v1）。

复用 sglang 标准组件（Engine/TP/flashinfer/forward_hooks 协议）与 sglang_fe 的 tap 机制，
零 sglang 源码修改。组件：
- core.DetectorCore：加载 results/bank/bank_*.json，经 sglang Engine+hooks 做
  决策点多层抽取（层位并集由 bank 反向驱动），条目批量打分 -> 统一校准 -> max 融合 -> 档位判决；
- server：FastAPI HTTP 包装（POST /detect）。
"""
