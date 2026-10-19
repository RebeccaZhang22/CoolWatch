# GPU7：chat + 影子模型 + probe API

本目录部署独立的 SGLang 0.5.19 activation runtime。两个 Qwen3-8B 实例均为 BF16、TP=1，使用物理 GPU7；不修改旧的 `probe-runtime`、`sglang_fe`、`sglang_det` 或已安装的 SGLang。

| 服务 | 端口 | 职责 |
| --- | --- | --- |
| `coolwatch-activation-chat` | 8104 | 正常 OpenAI chat/tool calling；关闭 activation capture |
| `coolwatch-activation-shadow` | 8303 | 新版按请求选层的 `/generate`、OpenAI 接口 |
| `coolwatch-activation-probe` | 8302 | CPU 上的 prompt 渲染和已启用分类器（当前仅 IPI）；异步请求 8303 |
| 已有 `coolwatch-web` | 18088 | 现有客服和 HR 前端；业务请求走 8104，检测走 8302 |

完成真实请求测试后，chat 约 34.3 GiB，shadow 约 34.7 GiB，总共约 69 GiB，剩余约 70.8 GiB。各自限制 `max_total_tokens=131072`，16K 上下文、4096-token chunked prefill；不要仅靠相加 `mem_fraction_static` 估算同卡占用，它还受启动时可用显存及显式 KV 上限影响。Chat 最大 32 个运行请求，shadow 最大 64 个运行请求，probe API 最多 128 个在途请求，超额返回 429。

## Probe 实际采集定义

直接读取已有 checkpoint 元数据，不按文件名推断层数：

| 风险 | 0-based block index | 按第 1 层起算 | 旧 bank `layer_hf` |
| --- | --- | --- | --- |
| 内容安全 | 21 | 第 22 层 | 22 |
| 提示词泄露 | 14 | 第 15 层 | 15 |
| 间接提示注入 | 22 | 第 23 层 | 23 |

三者均取 `block_output`：FFN 输出加回 residual、最终 RMSNorm 之前的原始 4096 维向量。位置是 `apply_chat_template(add_generation_prompt=True, enable_thinking=True)` 渲染出的完整 prompt 的最后一个 token，包含工具上下文。不是纯 `ffn_output`，也不是最后一条用户消息的最后一个字。

`backend/activation_probe_server.py` 按 checkpoint 生成请求参数，通过 base64 接收 BF16 数据，严格检查层、site、token 位置、token ID、形状、dtype、字节数和有限值。服务初始化校验模型路径、模型类型、权重合同和 IPI checkpoint SHA256。保留原来的 probe 参数、标准化和阈值。

Shadow 使用官方 `--enable-deterministic-inference`：普通 BF16 的批次大小变化曾导致分数波动，甚至改变近阈值判定。确定性模式下本次 1/8/16/32 并发测试与单请求的分数差为 0。它仍保留连续批处理、chunked prefill、prefix cache 和 decode CUDA Graph。采集 prefill 使用 eager；chat 使用正常高速推理配置。

## 启动与检查

这些 unit 文件按当前机器的用户和绝对目录部署。首次安装：

```bash
sudo cp sglang-activation-runtime/deploy/coolwatch-activation-*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start coolwatch-activation-shadow coolwatch-activation-chat coolwatch-activation-probe
```

服务由 systemd 管理，失败时重启；本次未设置开机自动启动。不要同时启动旧的 `coolwatch-chat` / `coolwatch-probe`，它们占用相同端口。上述命令不会自动清理 GPU 上其他服务；启动前确认显存。2026-10-12 已按用户要求停止 GPU7 原来的 Qwen3.8-27B（8029），命令记录在 `.runtime/activation-gpu7/previous-gpu7.json`。

```bash
systemctl status coolwatch-activation-shadow coolwatch-activation-chat coolwatch-activation-probe
journalctl -u coolwatch-activation-shadow -f
curl http://127.0.0.1:8302/health/ready
curl http://127.0.0.1:8302/bank
curl http://127.0.0.1:8302/batch-stats
```

前端已有运行环境指向 `8104/v1` 和 `8302`，因此用兼容的 `/detect`、`/bank`、`/v1/models` 接口完成接入，无需替换前端；模型卡片改用“业务 API”标注端口。结果的 `metadata.runtime` 为 `sglang-request-activation-v1`，`metadata.extraction` 给出实际采集定义。CPU 服务没有旧的全局 hooks、npz spool、flush 请求和串行 Engine 队列，GPU 批处理由 SGLang 统一负责。

## 验证和边界

```bash
CUDA_VISIBLE_DEVICES='' sglang-activation-runtime/python sglang-activation-runtime/tests/probe_adapter.py
CUDA_VISIBLE_DEVICES='' sglang-activation-runtime/python sglang-activation-runtime/tests/gpu7_live.py
# 数值参考会临时在 GPU7 再加载一份约 16 GiB 的 HF 模型，结束后释放。
CUDA_VISIBLE_DEVICES=7 sglang-activation-runtime/python sglang-activation-runtime/tests/probe_reference.py
.venv/bin/python sglang-activation-runtime/tests/frontend_live.py
```

浏览器测试需要 Playwright 的 Chromium 系统依赖。本机已有隔离依赖目录，可加 `LD_LIBRARY_PATH=/tmp/hr-browser-libs/extracted/usr/lib/x86_64-linux-gnu` 运行最后一条命令。测试通过真实注册 API 创建临时测试账号，完成后删除；不会重置已有账号或改写业务配置。

本次报告保存在 `.runtime/activation-gpu7/`，摘要见本目录 `validation-gpu7.json`。覆盖并发时两模型共用 GPU7、不同请求动态选择第 9/19 层和不同 site、decode CUDA Graph、4958-token 分块预填充及缓存复用、真实 8B 模型对照 HF 的三层向量、HTTP 校验及 HR 浏览器真实 SSE 请求。

真实 8B 的九组向量与 HF BF16 的余弦相似度最低约 0.9995，相对 L2 误差最高约 3.15%；三个参考输入的 probe 判定一致、概率差最大约 0.020。不同引擎不保证逐位一致，以上是工程数值检查，不是分类精度评估。

现有 probe 在 HR 域存在误报：明确要求正常 `record_screening` 保存操作的请求，在读取岗位工具后可能被提示词泄露 probe 拦截；简单介绍职责的请求也观察到误报。另有正常任务给出文字结论但没有调用保存工具。这些行为有真实轨迹记录，不能当作注入防护成功。此实现保留已有权重和阈值；要改善这些行为，需要另行做 HR 域评估/校准或模型提示词调整。

当前默认 `PROBE_BANK_ENABLED_RISKS=ipi`。有害行为与提示信息泄露探针暂时禁用：不加载其权重，不捕获其独有层，也不计分或参与拦截。`/bank` 和 `/detect` 返回 `enabled_risks` / `disabled_risks`，`per_risk` 只含实际启用项。API 适配器校验实际返回集合必须与配置一致，缺失 IPI 仍视为服务异常。配置改动须同步用于检测服务与 Web 服务，并重启生效。
