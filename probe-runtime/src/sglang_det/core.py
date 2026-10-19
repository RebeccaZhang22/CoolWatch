"""DetectorCore：unified bypass-detector 检测核心（sglang backend，内部通道 v1）。

流程（对应专利独1 方法A）：
1. 接收 messages + 检测配置（判决档位/条目子集）；
2. 渲染分词后经 sglang Engine（TP=2）单次预填充，hooks 按 bank 层位并集抽取决策点隐状态；
3. 各条目统一消费同一抽取结果批量打分（w·z+b）；
4. 条目级校准 Φ((s−μ)/σ) -> 跨风险可比；风险级 max 融合 -> 档位阈值判决。

v1 通道说明：仅内部通道（独2 行为规通道留待 v1.1——需 prompt logprob 语义的后缀读取）。
spool 文件通道沿用 sglang_fe（PoC 延迟可接受；生产化换共享内存）。
"""
import json
import os
import time

import numpy as np
import torch
from scipy.stats import norm

from sglang_fe.extractor import build_prompt


class DetectorCore:
    def __init__(self, model_path, bank_path, tp_size=2, spool_root="logs/spool_det",
                 max_len=3072, mem_fraction_static=0.85, debug=False):
        bank = json.load(open(bank_path))
        self.bank = bank
        self.model_path = model_path
        self.max_len = max_len
        self.risks = sorted({e["risk"] for e in bank["entries"]})
        self.entries = {e["id"]: dict(
            risk=e["risk"], method=e["method"], layer_hf=e["layer_hf"],
            w=np.asarray(e["w"], dtype=np.float64), b=float(e["b"]),
            mu=np.asarray(e["scaler_mu"], dtype=np.float64),
            sd=np.asarray(e["scaler_sd"], dtype=np.float64),
            cal_mu=e["cal_mu"], cal_sd=e["cal_sd"]) for e in bank["entries"]}
        self.thresholds = bank["thresholds"]
        hf_indices = sorted({e["layer_hf"] for e in self.entries.values()})

        _SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        pp = os.environ.get("PYTHONPATH", "")
        if _SRC not in pp.split(os.pathsep):
            os.environ["PYTHONPATH"] = _SRC + (os.pathsep + pp if pp else "")
        os.environ.setdefault("SGLANG_EXTERNAL_MODEL_PACKAGE", "sglang_fe.text_model")

        from sglang import Engine
        import shutil
        self.spool_dir = os.path.abspath(spool_root)
        shutil.rmtree(self.spool_dir, ignore_errors=True)
        os.makedirs(self.spool_dir, exist_ok=True)
        cfg = dict(n_layers=bank["n_layers"], hf_indices=hf_indices,
                   spool_dir=self.spool_dir, debug=debug)
        self.engine = Engine(
            model_path=model_path, tp_size=tp_size, dtype="bfloat16",
            mem_fraction_static=mem_fraction_static,
            chunked_prefill_size=-1, disable_radix_cache=True,
            disable_cuda_graph=True, disable_prefill_cuda_graph=True,
            context_length=max_len + 16,
            forward_hooks=[
                dict(name="tap_layers",
                     target_modules=["model.layers.*", "model.model.layers.*",
                                     "language_model.model.layers.*"],
                     hook_factory="sglang_fe.hooks:make_layer_hook", config=cfg),
                dict(name="tap_norm",
                     target_modules=["model.norm", "model.model.norm",
                                     "language_model.model.norm"],
                     hook_factory="sglang_fe.hooks:make_norm_hook", config=cfg),
            ],
        )
        self.tok = None
        self._read_ptr = 0
        self._spool = {}
        self._rid = 0
        # 预热：首个 forward 中途才装 meta hook
        from transformers import AutoTokenizer
        self.tok = AutoTokenizer.from_pretrained(model_path)
        self.tok.truncation_side = "left"  # 超长轨迹保尾部（决策点锚定区）
        self._generate([[self.tok.eos_token_id, self.tok.eos_token_id]])

    # ---------- 引擎与 tap ----------
    def _generate(self, list_ids, rid=None):
        self._rid += 1
        rid = rid or [f"det{self._rid:07d}_{i}" for i in range(len(list_ids))]
        self.engine.generate(input_ids=list_ids, rid=rid,
                             sampling_params=dict(max_new_tokens=1, temperature=0.0))
        return rid

    def _drain(self):
        import glob
        for f in sorted(glob.glob(os.path.join(self.spool_dir, "fwd_*.npz"))):
            idx = int(os.path.basename(f)[4:10])
            if idx < self._read_ptr:
                continue
            self._read_ptr = idx + 1
            z = np.load(f, allow_pickle=False)
            rids = json.loads(str(z["meta"]))
            keys = [k for k in z.files if k.startswith("hf_") and k[3:].isdigit()]
            for i, r in enumerate(rids):
                self._spool[r] = {int(k[3:]): z[k][i] for k in keys}
            os.remove(f)

    def _tap(self, list_ids, chunk=48):
        """返回 rid 列表与 {rid: {layer_hf: vec}}——决策点单次抽取。
        分块提交 + 尾随冲刷：大批量单 forward 会触发 chunk kernel 的巨量状态张量分配
        （ipi 长轨迹实测 OOM 的根因），块大小对齐 extract 的吞吐安全区。"""
        rids, out = [], {}
        for lo in range(0, len(list_ids), chunk):
            hi = min(lo + chunk, len(list_ids))
            part = self._generate(list_ids[lo:hi])
            # 尾随 dummy：其 forward 开始时冲刷上一（真实）forward 的特征
            self._generate([[self.tok.eos_token_id]])
            rids += part
            t0 = time.time()
            while time.time() - t0 < 300:
                self._drain()
                if all(r in self._spool for r in part):
                    break
                time.sleep(0.05)
            missing = [r for r in part if r not in self._spool]
            if missing:
                raise RuntimeError(f"tap 不完整：{len(missing)}/{len(part)} 缺特征（块 {lo}-{hi}）")
            out.update({r: self._spool.pop(r) for r in part})
        return rids, out

    # ---------- 打分/校准/融合/判决 ----------
    def _score_entry(self, ent, h):
        z = (h.astype(np.float64) - ent["mu"]) / ent["sd"]
        return float(ent["w"] @ z + ent["b"])

    def detect(self, messages_list, profile="balanced", entry_ids=None, tools_list=None):
        """批量检测：每元素 {messages:[...]}；返回逐元素判决与证据。
        tools_list：ipi 官方轨迹回放所需的逐请求工具规格（与 messages 等长，可为 None）。"""
        tools_list = list(tools_list) if tools_list is not None else [None] * len(messages_list)
        prompts = [build_prompt(self.tok, m, t) for m, t in zip(messages_list, tools_list)]
        ids = [self.tok(p, truncation=True, max_length=self.max_len)["input_ids"] for p in prompts]
        ents = self.entries if not entry_ids else {k: self.entries[k] for k in entry_ids}
        rids, feats = self._tap(ids)
        results = []
        for i, rid in enumerate(rids):
            hmap = feats[rid]
            per_entry, per_risk = {}, {}
            for eid, ent in ents.items():
                h = hmap.get(ent["layer_hf"])
                if h is None:
                    continue
                s_raw = self._score_entry(ent, h)
                s_cal = float(norm.cdf((s_raw - ent["cal_mu"]) / ent["cal_sd"]))
                per_entry[eid] = round(s_cal, 4)
                per_risk[ent["risk"]] = max(per_risk.get(ent["risk"], -1), s_cal)
            verdicts = {}
            triggered = []
            for risk, s in per_risk.items():
                thr = self.thresholds.get(risk, {}).get(profile)
                if thr is None:
                    continue
                flag = bool(s >= thr)
                verdicts[risk] = dict(score=round(float(s), 4), threshold=round(thr, 4),
                                      flagged=flag)
                if flag:
                    triggered += [eid for eid, e in ents.items()
                                  if e["risk"] == risk and per_entry.get(eid, 0) >= thr]
            results.append(dict(
                overall=bool(triggered), profile=profile,
                per_risk=verdicts, per_entry=per_entry, triggered_entries=triggered))
        return results

    def close(self):
        try:
            self.engine.shutdown()
        except Exception as e:  # noqa: BLE001
            print(f"[sglang_det] shutdown: {e}", flush=True)
