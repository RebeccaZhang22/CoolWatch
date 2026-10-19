# 兼容 Probe Bank 部署示例

`systemd/` 保存原有 Probe Bank、业务聊天、Qwen3Guard 和 Web 服务的 unit 示例。
如果使用新版按请求采集隐藏状态的运行时，请阅读
[`sglang-activation-runtime/deploy/README.md`](../sglang-activation-runtime/deploy/README.md)。
两套方案共用部分端口，不能同时启动对应的 chat/probe 服务。

## 环境与启动

原有特征提取代码位于 `probe-runtime/src/`，使用独立的
`probe-runtime/.venv-sglang` 环境，固定 SGLang 0.5.19。
本机依赖清单见 [`probe-runtime/requirements-local.txt`](../probe-runtime/requirements-local.txt)，
其中的版本针对 Python 3.11、PyTorch 2.13.0 / CUDA 13.0 环境。
准备兼容的基础环境后运行：

```bash
bash vllm_setups/setup_probe_runtime.sh
```

Web/API 使用项目根目录 `.venv`。模型目录由 `PROBE_MODEL_PATH` 指定，默认是
`.runtime/models/Qwen3-8B`；可以链接到已有模型目录，无需重复复制权重。
以下命令分别在不同终端启动服务：

```bash
CUDA_VISIBLE_DEVICES=0 PROBE_MODEL_PATH=/path/to/Qwen3-8B \
  bash vllm_setups/run_probe_bank_qwen3_8b.sh
CUDA_VISIBLE_DEVICES=0 MODEL_PATH=/path/to/Qwen3-8B \
  bash vllm_setups/run_chat_qwen3_8b.sh
bash vllm_setups/run_agent_backend.sh
```

探针服务默认监听 `127.0.0.1:8302`，就绪检查为 `/health/ready`，检测接口为
`/detect`。业务模型为独立的 `8104` 服务，提供 OpenAI-compatible 聊天和工具调用。
业务聊天默认关闭思考模式（`CUSTOMER_AGENT_ENABLE_REASONING=false`），
影子模型保持探针训练时使用的 thinking 模板。

Probe Bank 默认并发为 4、批次 token 预算为 16384、KV 缓存上限为 32768 tokens；
通过 `PROBE_MAX_BATCH`、`PROBE_BATCH_TOKENS`、`PROBE_MAX_TOTAL_TOKENS` 和
`PROBE_MEM_FRACTION` 调整。聊天脚本默认上下文长度 16384、最大并发 8、KV 缓存上限
131072 tokens，并开启最多 batch size 8 的 decode CUDA Graph。共享 GPU 时按剩余显存配置。

## systemd 示例

| 服务 | 示例 GPU / 端口 | 用途 |
| --- | --- | --- |
| `coolwatch-probe` | GPU0 / 8302 | 原有影子模型和已启用探针 |
| `coolwatch-chat` | GPU0 / 8104 | SGLang 业务聊天模型 |
| `coolwatch-guard` | GPU1 / 8001 | Qwen3Guard-Gen-8B |
| `coolwatch-web` | 18088 | 演示台与后端 API |

这些文件使用本机用户 `yutongz` 和绝对目录。部署到其他服务器前，修改 `User`、
工作目录、启动命令、磁盘挂载依赖及 GPU 编号。模型端口仅监听本机；Web 入口按部署环境配置。
unit 设置了异常重启、磁盘挂载等待及模型 HTTP 就绪检查。

```bash
# 调整配置后安装
sudo install -m 0644 deploy/systemd/coolwatch-*.service /etc/systemd/system/
sudo systemctl daemon-reload
# 选用这套方案时，启动并启用开机自启
sudo systemctl enable --now coolwatch-{probe,chat,guard,web}.service
sudo systemctl status coolwatch-{probe,chat,guard,web}.service
sudo journalctl -u coolwatch-chat.service -f
# 应用后端代码修改
sudo systemctl restart coolwatch-web.service
```

服务已由 systemd 管理时，不要重复启动同一端口的脚本。管理者控制台另用
[`manager/start.sh`](../manager/start.sh) 启动，默认端口 18089；其独立账号和共享活动数据配置见
[`manager/README.md`](../manager/README.md)。
