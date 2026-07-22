# AgentGuard

AgentGuard 是一个 LLM 安全攻防演示项目：前端用于选择场景、攻击样例和输入护栏，FastAPI 后端负责调用主模型、Qwen3Guard/网易易盾，并展示检测结果和泄露评估。

## 运行架构

```text
浏览器
  └─ FastAPI + 前端静态页面：http://127.0.0.1:8000
       ├─ 主模型 vLLM：http://127.0.0.1:8767/v1
       └─ Qwen3Guard vLLM（可选）：http://127.0.0.1:8001/v1
```

建议从项目根目录执行下面的命令。主模型、Qwen3Guard 和 Web 后端需要分别占用终端；如果 GPU 资源有限，也可以不单独启动 Qwen3Guard，改用后端本地 Transformers 模式。

## 1. 安装后端依赖

推荐使用 Python 3.10～3.12：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

`requirements.txt` 已包含 Web 后端、Transformers 本地推理和 vLLM serving 所需依赖。vLLM 需要可用的 CUDA 环境；如果主模型使用独立的推理环境，也可以在那里单独执行 `pip install vllm`。模型需要提前下载到本机，或保证当前环境可以从 Hugging Face 拉取。

## 2. 启动主模型 serving

项目默认使用 `qwen3.5-27b`，服务端口为 `8767`。可以直接启动一个 OpenAI-compatible 服务：

```bash
CUDA_VISIBLE_DEVICES=0,1 vllm serve Qwen/Qwen3.5-27B \
  --served-model-name qwen3.5-27b \
  --host 0.0.0.0 \
  --port 8767 \
  --tensor-parallel-size 2 \
  --trust-remote-code
```

确认服务正常：

```bash
curl http://127.0.0.1:8767/v1/models
```

如果使用其他模型或端口，需要同步修改后端的 `VLLM_MODEL` 和 `VLLM_BASE_URL`。前端当前的模型下拉框默认填写 `qwen3.5-27b`，它必须和 serving 的 `--served-model-name` 一致。

## 3. 配置 Qwen3Guard

### 推荐：独立 vLLM 服务

在另一张空闲 GPU 上启动 Qwen3Guard：

```bash
CUDA_VISIBLE_DEVICES=2 vllm serve \
  /share/workspace/models/hub/models--Qwen--Qwen3Guard-Gen-8B/snapshots/4505cb1a6f1864f21f8b27f7daf1b9a1aab6edbb \
  --served-model-name Qwen/Qwen3Guard-Gen-8B \
  --host 0.0.0.0 \
  --port 8001 \
  --max-model-len 32768
```

然后在 `backend/.env` 中配置：

```dotenv
QWEN3_GUARD_BACKEND=openai
QWEN3_GUARD_BASE_URL=http://127.0.0.1:8001/v1
QWEN3_GUARD_API_KEY=EMPTY
QWEN3_GUARD_MODEL=Qwen/Qwen3Guard-Gen-8B
```

### 备选：后端本地加载

不单独开启服务时，可以让后端在首次使用 Qwen3Guard 时通过 Transformers 懒加载模型：

```dotenv
QWEN3_GUARD_BACKEND=transformers
QWEN3_GUARD_MODEL=/share/workspace/models/hub/models--Qwen--Qwen3Guard-Gen-8B/snapshots/4505cb1a6f1864f21f8b27f7daf1b9a1aab6edbb
```

这种方式启动简单，但首次检测较慢，并且 Qwen3Guard 会和后端进程共享 GPU/内存。`QWEN3_GUARD_BACKEND=auto` 时，有 `QWEN3_GUARD_BASE_URL` 就调用独立服务，否则使用本地 Transformers。

## 4. 配置并启动后端

后端会自动读取 `backend/.env`。如果该文件还不存在，可以先复制示例文件，再补充主模型和 Qwen3Guard 配置：

```bash
cp -n backend/.env.example backend/.env
```

推荐的基础配置如下：

```dotenv
VLLM_BASE_URL=http://127.0.0.1:8767/v1
VLLM_API_KEY=EMPTY
VLLM_MODEL=qwen3.5-27b

QWEN3_GUARD_BACKEND=openai
QWEN3_GUARD_BASE_URL=http://127.0.0.1:8001/v1
QWEN3_GUARD_API_KEY=EMPTY
QWEN3_GUARD_MODEL=Qwen/Qwen3Guard-Gen-8B
```

如需使用网易易盾，再在同一个文件中填写：

```dotenv
NETEASE_YIDUN_SECRET_ID=your_secret_id
NETEASE_YIDUN_SECRET_KEY=your_secret_key
NETEASE_YIDUN_BUSINESS_ID=your_business_id
```

从项目根目录启动 FastAPI：

```bash
source .venv/bin/activate
uvicorn backend.app:app --host 0.0.0.0 --port 8000
```

检查后端和主模型连接状态：

```bash
curl http://127.0.0.1:8000/api/health
```

## 5. 启动前端

### 推荐：由后端直接托管

FastAPI 已经挂载了 `frontend/` 静态目录。后端启动后直接访问：

```text
http://127.0.0.1:8000
```

这种方式不需要 Node.js，也不需要再开前端进程。

### 前后端分开运行

如需单独启动前端：

```bash
python3 -m http.server 4173 --directory frontend
```

然后访问 `http://127.0.0.1:4173`。前端默认请求同源 `/api`；分开部署时，需要在 `frontend/index.html` 的 `app.js` 引入之前加入后端地址：

```html
<script>
  window.AGENT_GUARD_API_BASE = "http://127.0.0.1:8000";
</script>
```

后端默认允许跨域请求；生产环境可通过 `CORS_ALLOW_ORIGINS` 限制允许访问的前端域名。

## 最简启动顺序

```text
1. 启动主模型 vLLM（8767）
2. 启动 Qwen3Guard vLLM（8001，可选）
3. 配置 backend/.env
4. 启动 FastAPI（8000）
5. 浏览器打开 http://127.0.0.1:8000
```

进入页面后，勾选“Qwen3Guard”才会对本轮用户输入调用 Qwen3Guard；未勾选时只运行默认的无防护基线。
