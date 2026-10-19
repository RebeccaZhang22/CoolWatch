"""主进程驱动：sglang Engine（标准 offline API）+ sglang_fe hooks 的多层决策点特征提取。

- text-modality-only：经 SGLANG_EXTERNAL_MODEL_PACKAGE 注册 src/sglang_fe/text_model.py 的
  Qwen3_5TextOnlyForCausalLM，json_model_override_args 指定该架构，零 VL 包装器/视觉塔；
- 与 HF featurize.py 一致的渲染/分词（chat template + add_generation_prompt、截断 3072），
  token ids + 自定义 rid 直传 Engine.generate；
- hooks 在 scheduler 子进程内落盘 spool 分片（rank0），本进程按 rid 消费拼装；
- 每个 chunk 后发一个尾随 dummy 请求触发“下一 forward 冲刷上一 forward”，保证最后一批落盘。
"""
import glob
import json
import os
import shutil
import time

import numpy as np

_SRC_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_HOOKS_MOD = "sglang_fe.hooks"
_TEXT_ARCH = "Qwen3_5TextOnlyForCausalLM"
_STATE_DEBUG = False


def _norm_tool_calls(messages):
    """OpenAI 形式 tool_calls（function.name + JSON 字符串参数）→ 模板原生形式
    （扁平 name + dict 参数）。回放消息保持采集原样，归一化仅在渲染时进行。"""
    import json as _json
    out = []
    for m in messages:
        if m.get("tool_calls"):
            tcs = []
            for tc in m["tool_calls"]:
                fn = tc.get("function") or {}
                args = fn.get("arguments", tc.get("arguments"))
                if isinstance(args, str):
                    try:
                        args = _json.loads(args)
                    except Exception:
                        args = {"raw": args}
                tcs.append({"name": fn.get("name") or tc.get("name") or "", "arguments": args})
            m = {**m, "tool_calls": tcs}
        out.append(m)
    return out


def build_prompt(tok, messages, tools=None):
    """与 featurize.py 同义：先试原生 tool 角色，不支持则 user 包裹（正负一致）。
    统一 enable_thinking=False：9B/27B 模板默认渲染到 '<think>\\n'（开启），决策点会落进思考块；
    闭合后四尺寸末尾一致为 '<think>\\n\\n</think>\\n\\n'（对抗审查实测的协议统一性修复）。
    tools：ipi 官方轨迹的回放需要把采集时的工具规格渲染进系统区（与被服务请求一致）。"""
    def render(msgs, tools):
        try:
            return tok.apply_chat_template(msgs, tools=tools, tokenize=False,
                                           add_generation_prompt=True, enable_thinking=False)
        except TypeError:
            try:
                return tok.apply_chat_template(msgs, tokenize=False,
                                               add_generation_prompt=True, enable_thinking=False)
            except TypeError:  # 模板无 enable_thinking 变量
                return tok.apply_chat_template(msgs, tools=tools, tokenize=False,
                                               add_generation_prompt=True)
    try:
        p = render(_norm_tool_calls(messages), tools)
    except Exception:
        msgs = []
        for m in messages:
            if m["role"] == "tool":
                msgs.append({"role": "user", "content": "Tool output:\n" + m["content"]})
            else:
                msgs.append(m)
        p = render(_norm_tool_calls(msgs), None)
    assert p.endswith("</think>\n\n"), f"渲染尾部非闭合思考块：{p[-40:]!r}"
    return p


class SglangFeatureExtractor:
    def __init__(self, model_path, hf_indices, n_layers, spool_root, tp_size=2,
                 max_len=3072, mem_fraction_static=0.85, chunk=192, debug=False):
        self.model_path = model_path
        self.hf_indices = [int(i) for i in hf_indices]
        self.n_layers = n_layers
        self.spool_dir = os.path.abspath(spool_root)
        shutil.rmtree(self.spool_dir, ignore_errors=True)
        os.makedirs(self.spool_dir, exist_ok=True)
        self.max_len = max_len
        self.chunk = chunk
        global _STATE_DEBUG
        _STATE_DEBUG = debug

        pp = os.environ.get("PYTHONPATH", "")
        if _SRC_ROOT not in pp.split(os.pathsep):
            os.environ["PYTHONPATH"] = _SRC_ROOT + (os.pathsep + pp if pp else "")
        os.environ.setdefault("SGLANG_EXTERNAL_MODEL_PACKAGE", "sglang_fe.text_model")

        from sglang import Engine
        cfg = dict(n_layers=n_layers, hf_indices=self.hf_indices,
                   spool_dir=self.spool_dir, debug=debug)
        self.engine = Engine(
            model_path=model_path,
            tp_size=tp_size,
            dtype="bfloat16",
            log_level="info" if debug else "error",
            mem_fraction_static=mem_fraction_static,
            chunked_prefill_size=-1,
            disable_radix_cache=True,
            disable_cuda_graph=True,
            disable_prefill_cuda_graph=True,
            context_length=max_len + 16,
            forward_hooks=[
                dict(name="fe_layers",
                     target_modules=["model.layers.*", "model.model.layers.*",
                                     "language_model.model.layers.*"],
                     hook_factory=f"{_HOOKS_MOD}:make_layer_hook", config=cfg),
                dict(name="fe_norm",
                     target_modules=["model.norm", "model.model.norm",
                                     "language_model.model.norm"],
                     hook_factory=f"{_HOOKS_MOD}:make_norm_hook", config=cfg),
            ],
        )
        self._spool = {}          # rid -> {hf_idx: row}
        self._read_ptr = 0


    def _drain_spool(self):
        for f in sorted(glob.glob(os.path.join(self.spool_dir, "fwd_*.npz"))):
            idx = int(os.path.basename(f)[4:10])
            if idx < self._read_ptr:
                continue
            self._read_ptr = idx + 1
            z = np.load(f, allow_pickle=False)
            rids = json.loads(str(z["meta"]))
            keys = []
            for k in z.files:
                if not k.startswith("hf_"):
                    continue
                try:
                    keys.append((int(k[3:]), k))
                except ValueError:
                    continue
            for i, rid in enumerate(rids):
                if rid in self._spool:
                    continue
                self._spool[rid] = {idx: z[sk][i] for idx, sk in keys}
                self._spool.setdefault("_extra", {})
                for sk in z.files:
                    if sk.startswith("hf_") and not sk[3:].isdigit() and i == 0:
                        self._spool["_extra"][sk] = z[sk]
            os.remove(f)

    def extract(self, tok, list_of_messages, tools_list=None):
        """返回 (n, L_sel, d) fp16，行序与输入一致；决策点=各请求模板化后末词元。
        tools_list：与 messages 等长的工具规格列表（ipi 官方轨迹回放；无则 None）。"""
        tools_list = list(tools_list) if tools_list is not None else [None] * len(list_of_messages)
        prompts = [build_prompt(tok, m, t) for m, t in zip(list_of_messages, tools_list)]
        input_ids = [tok(p, truncation=True, max_length=self.max_len)["input_ids"]
                     for p in prompts]
        n = len(prompts)
        # 预热：第一个 forward 中途才装 meta hook，真实 chunk 必须排在它后面
        self.engine.generate(
            input_ids=[[tok.eos_token_id, tok.eos_token_id]],
            rid=["WARMUP"],
            sampling_params=dict(max_new_tokens=1, temperature=0.0),
        )
        self._drain_spool()
        for lo in range(0, n, self.chunk):
            hi = min(lo + self.chunk, n)
            rids = [f"{i:07d}" for i in range(lo, hi)]
            outs = self.engine.generate(
                input_ids=input_ids[lo:hi],
                rid=rids,
                sampling_params=dict(max_new_tokens=1, temperature=0.0),
            )
            if _STATE_DEBUG:
                infos = [str((o.get("meta_info") or {}).get("finish_reason", "?")) for o in outs]
                from collections import Counter
                print(f"[sglang_fe] generate finish_reasons: {dict(Counter(infos))}",
                      flush=True)
            # 尾随 dummy：其 forward 开始时冲刷上一（真实）forward 的特征
            self.engine.generate(
                input_ids=[[tok.eos_token_id]],
                rid=[f"FLUSH_{lo:07d}"],
                sampling_params=dict(max_new_tokens=1, temperature=0.0),
            )
            t0 = time.time()
            while time.time() - t0 < 300:
                self._drain_spool()
                if all(r in self._spool for r in rids):
                    break
                time.sleep(2)
            missing = [r for r in rids if r not in self._spool]
            if missing:
                raise RuntimeError(f"sglang_fe: {len(missing)} 个请求缺特征（首缺 {missing[0]}）；"
                                   f"spool 可能不完整")
        d = None
        for i in range(n):
            rec = self._spool[f"{i:07d}"]
            d = rec[self.hf_indices[0]].shape[0]
            break
        feats = np.zeros((n, len(self.hf_indices), d), dtype=np.float16)
        for i in range(n):
            rec = self._spool.pop(f"{i:07d}")
            feats[i] = np.stack([rec[k] for k in self.hf_indices], axis=0)
        return feats

    def close(self):
        try:
            self.engine.shutdown()
        except Exception as e:  # noqa: BLE001
            print(f"[sglang_fe] engine shutdown: {e}", flush=True)
