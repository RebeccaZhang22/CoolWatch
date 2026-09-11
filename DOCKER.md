# Docker 试用

## 两个 vLLM 脚本怎么区分

| 脚本 | 默认端口 | 作用 | 常用命令 |
| --- | ---: | --- | --- |
| `vllm_setups/run_chat_vllm_qwen3_8b.sh` | `8104` | 普通聊天/业务模型，真正生成客服 Agent 的回答并执行工具调用 | `bash .../run_chat_vllm_qwen3_8b.sh` |
| `vllm_setups/run_probe_vllm_qwen3_8b.sh` | `8013` | 带 Activation/Inline Probe 的探针影子模型，只做隐藏层安全检测 | `bash .../run_probe_vllm_qwen3_8b.sh start/status/stop` |

简单记：`chat` 负责“回答”，`probe` 负责“检测”。两个服务可以同时运行，后端会分别连接它们。

## 无模型快速体验

镜像不捆绑 Qwen3 权重（单个模型约 16 GB，且需要 GPU）。拉取后可以直接运行 CPU Web 容器：

```bash
docker pull rebeccazhang22/agent-guard-open:latest
docker run --rm --name prospectmonitor \
  -p 18088:18088 \
  rebeccazhang22/agent-guard-open:latest
```

打开 [http://localhost:18088/?demo=1](http://localhost:18088/?demo=1)。`demo=1` 使用内置 Mock Agent，可以体验首页、护栏开关、对话、RAG 轨迹和风险展示，不需要 GPU、模型权重或第三方密钥。

## 接入真实 vLLM

先在宿主机或 GPU 节点启动普通业务模型和带 Probe 的影子模型：

```bash
./vllm_setups/run_chat_vllm_qwen3_8b.sh              # 普通模型 :8104
./vllm_setups/run_probe_vllm_qwen3_8b.sh start   # Probe 模型 :8013
```

然后启动容器：

```bash
docker compose up -d
```

Compose 默认通过 `host.docker.internal` 访问宿主机的 `8104` 和 `8013`。如果模型在其他机器，设置 `CUSTOMER_AGENT_BUSINESS_VLLM_BASE_URL`、`CUSTOMER_AGENT_SHADOW_VLLM_BASE_URL` 和对应的护栏环境变量后再启动。

真实模式访问 [http://localhost:18088/](http://localhost:18088/)，首次使用需要注册账号。`/?demo=1` 始终是本地 Mock 试用，不会调用模型。

## 从源码构建

```bash
docker compose build
docker compose up -d
```

容器健康检查：

```bash
curl http://localhost:18088/api/health
```
