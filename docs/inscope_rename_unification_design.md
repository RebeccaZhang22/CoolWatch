# InScope 统一命名与 server/client 合并设计

状态：**设计稿，未实施**。只描述命名方案、目标结构与迁移顺序，不代表代码已改动。
范围：h20-1 上的 `CoolWatch-server` 与 `CoolWatch-request` 两个项目 → 统一为 **InScope**。
依据：2026-10-22 对两个目录的只读全量扫描（排除 `.venv/`、`vendor/`、`__pycache__/`、`logs/`、`.runtime/`）。
关联：[server/client 拆分设计](server_client_split_design.md)（同目录）。

---

## 1. 结论摘要

1. **建议把「改名」和「拆分」合并成一次重构**（即把拆分设计的 S0–S5 与本方案合并执行），否则要经历两次停服、两次 GPU 验收。
2. `InScope` 这个名字**在本项目里已经被占用 5 次**（fork、conda 环境、线上协议 schema、checkpoint 字段、类名）。直接拿它当产品名会造成「同名不同物」，必须配一套消歧约定（见 §3）。
3. 有三类东西**绝对不能跟着改名**：线上协议字符串、历史证据文件、由别人拥有的资源（见 §6）。
4. 目录改名会**打断 3 个 editable 安装**（server、request、`vendor/` 里的 sglang fork），因为 editable finder 把绝对路径写死在 `.venv` 里；必须重装（见 §5.3）。
5. 已发布的调用方（Python 包名、环境变量、CLI 名）需要**过渡别名**，不能一刀切（见 §7）。

---

## 2. 现状盘点（实测）

### 2.1 出现次数

| token | CoolWatch-server | CoolWatch-request |
| --- | --- | --- |
| `CoolWatch` | 31 | 36 |
| `coolwatch` | 10 | 17 |
| `Shadow`（大写，出现在用户可见字符串里） | 3 | 0 |
| `shadow_`（包/模块前缀） | 19 | 0 |
| `SHADOW`（环境变量） | 11 | 14 |
| `COOLWATCH_`（环境变量） | 0 | 15 |
| `InScope` | 22 | 2 |
| `inscope` | 14 | 1 |

### 2.2 按文件落点

**CoolWatch-server**（共 20 个文件命中，`grep -c` 为命中行数）

| 文件 | `shadow_server` | `SHADOW_API_KEY` | `Shadow` | `CoolWatch` | `coolwatch` |
| --- | --- | --- | --- | --- | --- |
| `docs/developer_guide.md` | 6 | 1 | – | 8 | – |
| `docs/deployment.md` | – | 1 | – | 5 | 2 |
| `docs/probe_messages_api.md` | – | 2 | 1 | 2 | – |
| `README.md` | – | – | – | 5 | – |
| `.env.example` | – | 1 | – | – | – |
| `pyproject.toml` | 1 | – | – | – | 1 |
| `requirements-runtime.txt` | – | – | – | 2 | 2 |
| `shadow_server/__init__.py` | – | – | – | 1 | – |
| `shadow_server/app.py` | – | – | 2 | 1 | – |
| `shadow_server/config.py` | – | 2 | – | – | – |
| `shadow_server/rendering.py` | – | – | – | 1 | – |
| `scripts/start_api.sh` | 1 | 1 | – | – | – |
| `scripts/start_backend.sh` | 1 | – | – | – | – |
| `scripts/run_logged.py` | – | 1 | – | – | – |
| `scripts/smoke.py` | – | 1 | – | – | – |
| `scripts/download_model.py` | 1 | – | – | – | 1 |
| `scripts/download_model_ranges.py` | – | – | – | – | 3 |
| `tests/test_shadow.py` | 6 | – | – | – | – |
| `tests/test_normalization.py` | 1 | – | – | – | – |
| `tests/test_upstream.py` | 2 | – | – | – | 1 |

**CoolWatch-request**（共 11 个文件命中）

| 文件 | `CoolWatch` | `coolwatch` | `SHADOW` | `COOLWATCH_` |
| --- | --- | --- | --- | --- |
| `README.md` | 9 | 6 | 3 | 3 |
| `docs/developer_guide.md` | 3 | 2 | 1 | 1 |
| `pyproject.toml` | 1 | 3 | – | – |
| `.env.example` | – | – | 1 | 2 |
| `call_coolwatch.sh` | 1 | 2 | 5 | 3 |
| `coolwatch_request/__init__.py` | 2 | – | – | – |
| `coolwatch_request/client.py` | 2 | – | – | – |
| `coolwatch_request/__main__.py` | 4 | – | 1 | 2 |
| `examples/request.py` | 2 | 1 | 1 | 2 |
| `tests/test_client.py` | 5 | 1 | – | – |
| `tests/test_server_integration.py` | 3 | 1 | – | – |

（`coolwatch_request.egg-info/` 与 `__pycache__/` 是生成物，改源码后重新生成即可，不计入。）

### 2.3 目录/文件级别的命名

| 类型 | 旧名 | 位置 |
| --- | --- | --- |
| 包目录 | `shadow_server/` | server |
| 包目录 | `coolwatch_request/` | request |
| 生成物目录 | `coolwatch_request.egg-info/` | request |
| 脚本 | `call_coolwatch.sh` | request |
| 测试文件 | `tests/test_shadow.py` | server |
| 产物名 | `coolwatch_model_manifest.json`（下载模型时写入） | server `scripts/download_model*.py` |
| dist 名 | `coolwatch-server==0.2.0`、`coolwatch-request==0.1.0` | 两侧 `pyproject.toml` |
| 控制台入口 | `coolwatch-request` | request |

### 2.4 已确认的干扰项

- `scripts/download_model_ranges.py` 里的 `?coolwatch=size` / `?coolwatch_range=` 是**写给上游 CDN 的 query key**（防缓存用），改名无害但属于噪音，可顺手改成 `inscope`。
- `scripts/run_logged.py:11` 用 `SHADOW_API_KEY`/`SGLANG_API_KEY` 做日志脱敏白名单 —— **改名时必须同步**，否则 key 会漏进日志。
- 两个项目的 `.env` 均为 `yutongz:yutongz 0600`，当前登录的 `zmosg` **读不到也改不了**；改名涉及 key 名变更时必须由 `yutongz` 执行（见 §9 风险）。

---

## 3. `InScope` 已有 5 个含义（消歧是硬要求）

| # | 含义 | 证据 | 归属 | 能否改名 |
| --- | --- | --- | --- | --- |
| 1 | SGLang fork `yeasen-z/sglang-inscope` @ `d504843f…` | `vendor/sglang-inscope/`、`config.py:9` `INSCOPE_COMMIT`、`scripts/prepare_runtime.sh` | 上游仓库 | **不能**，是外部仓库名 |
| 2 | conda 环境 `/opt/miniconda3/envs/inscope` | `.venv/pyvenv.cfg` 的 `home` | 本机共享环境（非本项目） | **不能**，且是只读复用 |
| 3 | 线上特征协议 schema `inscope.feature_capture.v1` | `shadow_server/backend.py:19`、`tests/test_shadow.py:34`、客户端集成测试 | fork + 两侧实现 | **不能**，是线协议 |
| 4 | checkpoint manifest 字段 `inscope_layers = [9,17,25]` | `checkpoints/manifest.json` | 训练侧产物 | **不能**，改了旧文件读不出 |
| 5 | 类名 `InScopeBackend` | `shadow_server/backend.py`、`app.py`、测试（共 11 处） | 本项目代码 | 可改，但没必要 |

**消歧约定（建议写进 README 与开发者指南）：**

- 产品/服务名：**InScope**（首字母大写、无连字符写全称）。
- 指 SGLang fork 时**必须写全 `sglang-inscope`**，禁止简写成 InScope。
- 指特征协议时一律写 `inscope.feature_capture.v1`（小写带版本），不改。
- conda 环境保持 `inscope`，文档中出现时写成 `/opt/miniconda3/envs/inscope`（带路径）。
- 代码命名空间统一用 `inscope_*` 前缀（下划线），与上面四者字形可区分。

如果觉得仍然容易混，备选：把**服务层**命名为 `inscope-gateway`（CPU API）/ `inscope-engine`（GPU 侧），只在仓库与产品层面叫 InScope。本文按「统一叫 InScope + 前缀区分」写，§10 列为待确认项。

---

## 4. 目标命名映射

| 类别 | 旧 | 新 | 备注 |
| --- | --- | --- | --- |
| 仓库/目录 | `CoolWatch-server` | `InScope/`（单仓，见 §5.1） | 目录改名需停服 |
| 仓库/目录 | `CoolWatch-request` | 并入同仓 `packages/inscope-request/` | 也可保留双仓 |
| Python 包 | `shadow_server` | `inscope_server` | 不用裸 `inscope`，避免与 fork/协议同名 |
| Python 包 | `coolwatch_request` | `inscope_request` | |
| Python 包（新） | – | `inscope_contract` | 拆分设计的契约包 |
| Python 包（新） | – | `inscope_engine` | GPU 侧启动/适配 |
| dist 名 | `coolwatch-server` | `inscope-server` | 版本升 `0.3.0`（有破坏性 API 变更） |
| dist 名 | `coolwatch-request` | `inscope-request` | |
| 类 | `CoolWatchClient` | `InScopeClient` | |
| 类 | `AsyncCoolWatchClient` | `AsyncInScopeClient` | |
| 类 | `InScopeBackend` | 保留 | 已经是目标命名 |
| 类 | `Probe` | 保留（或 `A6Probe`） | 无命名冲突 |
| 控制台入口 | `coolwatch-request` | `inscope-request` | 保留旧名别名一个版本 |
| 脚本 | `call_coolwatch.sh` | `call_inscope.sh` | |
| 脚本 | `scripts/start_backend.sh` | `scripts/start_engine.sh` | “backend” 与 InScope 的 engine 对齐 |
| 测试 | `tests/test_shadow.py` | `tests/test_detector.py` | |
| 产物 | `coolwatch_model_manifest.json` | `inscope_model_manifest.json` | |
| 环境变量 | `SHADOW_API_KEY` | `INSCOPE_API_KEY` | 对外 key，需过渡期 |
| 环境变量 | `COOLWATCH_SERVER_URL` | `INSCOPE_SERVER_URL` | 客户端用 |
| 环境变量 | `COOLWATCH_REQUEST_TIMEOUT` | `INSCOPE_REQUEST_TIMEOUT` | 客户端用 |
| 环境变量 | `SGLANG_API_KEY` | **不变** | 属于 SGLang 自身 |
| 环境变量 | `BACKEND_URL`/`BACKEND_PORT` | `INSCOPE_ENGINE_URL`/`_PORT` | 全项目自有变量加前缀，避免 `.env` 被 `set -a` 载入后与同机其他项目冲突 |
| 环境变量 | `API_HOST`/`API_PORT` | `INSCOPE_API_HOST`/`_PORT` | 同上 |
| 环境变量 | `MAX_INFLIGHT`/`MAX_INPUT_TOKENS`/`REQUEST_TIMEOUT`/`MEM_FRACTION_STATIC` | 加 `INSCOPE_` 前缀 | 同上；`PROBE_THRESHOLD`→`INSCOPE_PROBE_THRESHOLD` |
| 环境变量 | `MODEL_PATH` | `INSCOPE_MODEL_PATH` | 同上 |
| 环境变量 | `CUDA_VISIBLE_DEVICES`、`PYTHON` | 不变 | 通用变量 |
| 错误字符串 | `"Shadow feature backend unavailable"` | `"InScope engine unavailable"` | 已核实：两侧测试与客户端均**不**匹配该文案，可安全改写 |
| 日志 | `"Shadow backend failed: %s"` | `"InScope engine failed: %s"` | |
| 文档 | 全部 `CoolWatch*` | `InScope*` | 历史材料例外，见 §6 |
| HTTP 路径/字段 | `/detect`、`/info`、`/health/*`、`score/logit/threshold/flagged/risk/model` | **不变** | 线协议冻结 |

---

## 5. 目标结构

### 5.1 仓库布局（单仓方案）

```text
InScope/
├── pyproject.toml                  # 工作区/或单 dist 多 entrypoint
├── packages/
│   ├── inscope_contract/           # 常量 + schema，三端共享；仅依赖 pydantic
│   ├── inscope_server/             # CPU：8302，原 shadow_server
│   │   ├── app.py  normalization.py  rendering.py  probe.py
│   │   └── engine_client.py        # 原 backend.py 的协议部分
│   ├── inscope_engine/             # GPU：30000，SGLang InScope 启动 + 身份校验 + 适配
│   └── inscope_request/            # 客户端：仅 httpx
├── scripts/                        # service.py / start_*.sh / smoke.py / download_model*.py
├── tests/
├── checkpoints/                    # 含 manifest.json（字段名不动）
├── vendor/sglang-inscope/          # 保持为独立 git 仓库，仅记录 commit
└── docs/
```

若坚持双仓：`InScope-server/` + `InScope-request/`，契约包单独发 `inscope-contract` 或作为 server 仓内的 namespace。单仓更贴合「统一」诉求，且能让 §2.2 里那 20+11 个文件的文档路径一次改完。

### 5.2 单进程入口

```bash
inscope serve --api        # 等价原 uvicorn shadow_server.app:create_app --factory
inscope serve --engine     # 等价原 scripts/start_backend.sh（SGLang InScope）
inscope status|start|stop  # 等价原 scripts/service.py
```

`scripts/service.py` 已经区分 `--component api|backend`，改成 `--component api|engine` 即可，管理语义不变。

### 5.3 目录改名的真实代价（必须做，否则起不来）

editable 安装在 `.venv` 里写死了绝对路径，实测：

| finder | 写死的路径 |
| --- | --- |
| `__editable___coolwatch_server_0_2_0_finder.py` | `/mnt/kpfs_qyang/yutongz/CoolWatch-server` |
| `__editable___sglang_0_0_0_dev1_gd504843f4_finder.py` | `/mnt/kpfs_qyang/yutongz/CoolWatch-server`（vendor 内） |
| `__editable___coolwatch_request_0_1_0_finder.py`（装在 **server 的 venv** 里） | `/mnt/kpfs_qyang/yutongz/CoolWatch-request` |

因此改名后必须：

```bash
# 1) 目录改名（需 yutongz 身份；停服后执行）
# 2) 重装三处 editable
.venv/bin/pip install -e .                      # inscope-server（或 inscope）
.venv/bin/pip install -e packages/inscope-request
SGLANG_BUILD_RUST_EXTS=none .venv/bin/pip install --no-build-isolation -e vendor/sglang-inscope/python
# 3) 重新生成 requirements-runtime.txt（当前是 pip freeze，里头含两条 -e 与 fork 的 git URL）
```

注意 `requirements-runtime.txt:20-23` 现在就记录着 `coolwatch-request`/`coolwatch-server` 两条 editable 与一条 `-e git+…sglang-inscope.git@d504843…`，路径与 egg 名都要跟着更新。

**顺带清掉一处既有的耦合**：server 的 venv 里装着客户端（`coolwatch_request-0.1.0.dist-info` + 指向 `../CoolWatch-request` 的 pth）。改名时正好把这条 editable 从 server venv 移除，只保留在 developer 环境或合并后的单仓里。

---

## 6. 冻结清单（改名不得触碰）

| 冻结项 | 值/位置 | 原因 |
| --- | --- | --- |
| 特征协议 schema | `inscope.feature_capture.v1` | fork 定义、两侧已上线，改了直接 503 |
| checkpoint 文件与 manifest 字段 | `best_layers_08_16_24.pt`、`inscope_layers`、`feature_name`、`schema`、`arm`、`setting`、`runtime_parity` | 训练侧产物格式，旧文件要能读 |
| checkpoint/commit 常量 | `10f79d9c…`、`d504843f…` | 校验用，改名不影响，但**不要顺手“整理”** |
| HTTP 路径与 JSON 字段 | `/detect`、`/info`、`/health/live`、`/health/ready`、`score/logit/threshold/flagged` | 已发布给外部调用方 |
| 历史证据文件 | `.runtime/*`（`gpu-smoke-h20.log`、`long-context-h20.json`）、`logs/*`、`docs/reference/*handoff*.md` | 是验收与交接证据，改名会破坏可追溯性；只加“更名说明”，不改写正文 |
| 旧仓库 | `/mnt/kpfs_qyang/yutongz/CoolWatch`（origin `RebeccaZhang22/CoolWatch`） | 别人的 git 仓库，与本项目无关，不参与改名 |
| 共享 conda 环境 | `/opt/miniconda3/envs/inscope` | 非本项目所有，只读复用 |
| fork 仓库名与 remote | `yeasen-z/sglang-inscope` | 上游地址 |
| 数值契约 | 层号 `8/16/24→9/17/25`、位置 `[-4..-1]`、展平 `layer→token→hidden`、`BF16→E5M2→FP32`、阈值 `0.9` | 见拆分设计 §6 |

---

## 7. 兼容期与影响面

| 变更 | 需重启 server | 需重发/重装客户端 | 破坏线协议 | 过渡策略 |
| --- | --- | --- | --- | --- |
| 目录改名 | 是 | 否 | 否 | 无 |
| edtiable 重装 | 是 | 否 | 否 | 无 |
| Python 包名/类名 | 是 | **是**（`from coolwatch_request import CoolWatchClient` 会失败） | 否（仅 Python API） | 旧名保留为 `DeprecationWarning` 别名一个版本 |
| CLI 入口名 | 否 | 是 | 否 | `entry_points` 同时提供 `inscope-request` 与 `coolwatch-request` 两个脚本指向同一 `main` |
| 环境变量名 | 是 | 是 | 否 | server 读 `INSCOPE_API_KEY` 优先、回退旧 `SHADOW_API_KEY` 并打弃用日志；client 同样双读；`.env` 两处都要更新（`yutongz` 0600） |
| 错误字符串/日志 | 是 | 否 | 否 | 直接改（已核实无消费方匹配文案） |
| HTTP 路径/字段 | 是 | 是 | **是** | **本次不做**；若要做，先加 `/v1/*` 别名再弃用 |
| 产物/清单文件名 | 否 | 否 | 否 | 新文件用新名，旧文件不动 |

---

## 8. 迁移顺序（与拆分设计合并执行）

| 步骤 | 内容 | 需重启 | 风险 |
| --- | --- | --- | --- |
| T0 | 建 git 基线：单仓 `InScope/`，把两个目录的内容并入并首次提交（先存档，后改名） | 否 | 低 |
| T1 | 目录改名 + 三处 editable 重装 + `requirements-runtime.txt` 重生成（**此时不动代码**） | 是 | 中：忘重装会 `ImportError`，表象像“服务起不来” |
| T2 | 代码改名：包名、类名、env 名、脚本名、日志/错误文案；加过渡别名 | 是 | 中：`run_logged.py` 脱敏白名单必须同步 |
| T3 | 抽 `inscope_contract`（拆分设计 §3.1），三端改为依赖它 | 是 | 低 |
| T4 | `backend.py` 三职责重划：身份校验下移到 engine 侧 | 是 | 中：身份校验放宽处需测试覆盖 |
| T5 | venv 分家 + 移除 server venv 里的客户端 editable | 是 | 低 |
| T6 | 传输可选优化：`encoding` 增加 `base64`（实测 text 575 KiB → base64 128/64 KiB） | 是（两端） | 中：需数值对照 |
| T7 | CLI 统一为 `inscope serve --api\|--engine`，`service.py` 改调它 | 是 | 低 |
| T8 | systemd（可选，替换无开机自启的后台进程） | 是 | 低 |

T1 与 T2 分开的理由：先证明「改名后原代码仍能跑起来」，再动代码，出问题时可二分定位。

---

## 9. 验收与回滚

**残留校验（期望：除白名单外为 0）**

```bash
cd InScope
grep -rn --binary-files=without-match \
  --exclude-dir=.venv --exclude-dir=vendor --exclude-dir=__pycache__ \
  --exclude-dir=logs --exclude-dir=.runtime --exclude-dir=.git \
  -iE 'coolwatch|shadow_server' . | grep -v 'docs/reference/'
```

**功能与数值验收**（改名不得改变任何数值）

```bash
.venv/bin/python -m unittest discover -s tests -v          # server
cd packages/inscope-request && python -m unittest discover -s tests -v
set -a; source .env; set +a
python scripts/smoke.py --url http://127.0.0.1:8302
# 固定 examples/probe_request.json + 9K/40K 长输入：score/logit 与改名前后逐位一致
```

**风险**

1. `.env` 属 `yutongz` 0600，`zmosg` 无读写权 → 改 env key 名必须由 `yutongz` 执行，否则服务 401。
2. 目录改名需要停服窗口；GPU 7 上 CoolWatch 占约 30.2 GiB/143.8 GiB（21%），同机 GPU 0–6 被其他用户项目占满，重启前确认显存。
3. editable 路径写死是最易踩的坑（§5.3）。
4. 外部调用方可能仍持有 `CoolWatch-request` 包与 `SHADOW_API_KEY`、`COOLWATCH_SERVER_URL`；必须给足兼容期，否则对端直接失败。
5. 历史材料（handoff、`.runtime` 报告、日志）建议保留原名原文，只在 README 加一行「原 CoolWatch-server，2026-10-22 更名 InScope」；全量改写会破坏证据链。

**回滚**：T0 的 git 基线保证任一步可 `git checkout`；目录改名可用 `mv` 反向；env 双读设计使 T2 可单侧回退。

---

## 10. 待确认

1. **命名粒度**：统一叫 InScope（本文方案，配 §3 消歧约定），还是服务层另起 `inscope-gateway`/`inscope-engine`？
2. **单仓还是双仓**：合并进 `InScope/`（推荐，一次改完 31 个文件的文档路径），还是保留两个仓库？
3. **兼容期**：`coolwatch-request` 入口与旧 env 名保留多久（一个版本 / 一个季度 / 立即切断）？
4. **env 变量前缀**：是否把所有项目自有变量改为 `INSCOPE_*`（本文建议，避免 `.env` 被 `set -a` 后污染同机其他项目），还是只改 key 类变量？
5. **改名时机与执行者**：需要停服 + 一次 GPU 验收；由 `yutongz` 执行（涉及 `.env` 与目录属主）。
6. **旧仓库**：`/mnt/kpfs_qyang/yutongz/CoolWatch`（origin `RebeccaZhang22/CoolWatch`）是否也要改 README 指向 InScope，或完全不动？