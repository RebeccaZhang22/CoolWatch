"""sglang scheduler 子进程内的特征捕获 hooks v3（ServerArgs.forward_hooks 标准协议注入）。

实测（0.5.19）事实驱动的三个设计决定：
1. spec hook 的 args 不可依赖（backbone 以 kwargs 被调用，nn.Module post-hook 丢弃 kwargs）——
   元数据（rids/extend_seq_lens）经 layer_id==0 上的 PyTorch 标准 with_kwargs=True hook 读取；
2. flush 不依赖任何根模块触发——下一个 forward 开始时（layer0 post）冲刷上一 forward 的缓冲，
   末尾 forward 由驱动端的尾随 dummy 请求触发冲刷；
3. 模块路径做多 pattern 兜底（不同包装层级下 layers 的绝对路径不同），真实 decoder layer 用
   类名 + layer_id 识别；HF hidden_states[n_layers]（末层，最终归一化之后）经 model.norm 捕获。

捕获语义对齐 HF featurize.py：决策点=各请求最后一个 extend 词元；层 j 输出 ↔ HF index j+1；
embed 输出 ↔ HF index 0；norm 输出 ↔ HF index n_layers。仅 tp rank0 落盘。
"""
import json
import os
import threading

import numpy as np
import torch

_LOCK = threading.Lock()
_STATE = {
    "inited": False,
    "n_layers": None,
    "hf_indices": None,
    "spool_dir": None,
    "fwd_counter": 0,
    "meta_hook_on": False,
    "pending": None,           # dict(fwd_id, buf={hf_idx: tensor}, meta=(rids, ext) | None)
    "rank": None,
    "debug": False,
}
_LAYER_CLASS_NAMES = ("Qwen3_5LinearDecoderLayer", "Qwen3_5AttentionDecoderLayer")


def _maybe_init(config):
    if not _STATE["inited"]:
        _STATE["inited"] = True
        _STATE["n_layers"] = config["n_layers"]
        _STATE["hf_indices"] = set(config["hf_indices"])
        _STATE["spool_dir"] = config["spool_dir"]
        _STATE["debug"] = bool(config.get("debug", False))
        os.makedirs(_STATE["spool_dir"], exist_ok=True)
        try:
            from sglang.srt.distributed import get_parallel
            _STATE["rank"] = get_parallel().tp_rank
        except Exception:
            _STATE["rank"] = int(os.environ.get("SGLANG_TP_RANK", "0"))
        print(f"[sglang_fe] hooks init: n_layers={_STATE['n_layers']} "
              f"hf_indices={sorted(_STATE['hf_indices'])} rank={_STATE['rank']}", flush=True)
    return _STATE["rank"] == 0


def _flush_locked():
    """把 pending 写入 spool。调用方需持有 _LOCK。行数不一致的层跳过（防越界 assert 毒化上下文）。"""
    p, _STATE["pending"] = _STATE["pending"], None
    if not p or not p["meta"] or not p["buf"]:
        return
    rids, ext = p["meta"]
    if not rids or not ext:
        if _STATE["debug"]:
            print(f"[sglang_fe] flush skip: rids={rids!r} ext={ext!r}", flush=True)
        return
    ends = np.cumsum([0] + list(ext))
    dec_rows = ends[:-1] + np.asarray(ext) - 1
    ntok = int(ends[-1])
    # hf_0（embedding 输出）由驱动端按 HF 语义直接查表计算（W[last_token_id]）——
    # sglang 内部路径对 embedding 有非恒等变换（实测与查表真值正交），不经 hook 捕获。
    p["buf"].pop(0, None)
    if _STATE["debug"]:
        print(f"[sglang_fe] flush rows={len(rids)} ntok={ntok}", flush=True)
    rec = {}
    shapes = {}
    for hf_idx, h in p["buf"].items():
        if h.shape[0] <= int(dec_rows.max()) or h.shape[0] != int(ends[-1]):
            shapes[int(hf_idx)] = tuple(h.shape)
            continue
        rec[f"hf_{int(hf_idx)}"] = h[torch.as_tensor(dec_rows, device=h.device)] \
            .to(torch.float16).cpu().numpy()
    outp = os.path.join(_STATE["spool_dir"], f"fwd_{_STATE['fwd_counter']:06d}.npz")
    _STATE["fwd_counter"] += 1
    if _STATE["debug"]:
        print(f"[sglang_fe] flush fwd rows={len(rids)} ntok={int(ends[-1])} "
              f"keys={sorted(rec)} mismatch={shapes}", flush=True)
    if not rec:
        return
    np.savez(outp, meta=json.dumps(rids), **rec)


def _meta_hook(module, args, kwargs, output):
    """layer0 的 with_kwargs hook：新 forward 开始 -> 冲刷上一 forward -> 记录本 forward 元数据。"""
    fb = kwargs.get("forward_batch")
    with _LOCK:
        if _STATE["debug"]:
            try:
                mode = str(getattr(fb, "forward_mode", "?"))
                nrid = len(fb.rids or [])
            except Exception:
                mode, nrid = "?", -1
            print(f"[sglang_fe] meta fire: mode={mode} nrids={nrid} has_fb={fb is not None}",
                  flush=True)
        _flush_locked()
        try:
            is_extend = fb.forward_mode.is_extend()
        except Exception:
            is_extend = getattr(fb, "extend_seq_lens", None) is not None
        if fb is None or not is_extend:
            _STATE["pending"] = dict(buf={}, cands=[], meta=None)
            return
        ext = fb.extend_seq_lens_cpu
        if ext is None and fb.extend_seq_lens is not None:
            ext = fb.extend_seq_lens.tolist()
        pend = dict(buf={}, meta=(list(fb.rids or []),
                                  list(ext) if ext is not None else None))
        _STATE["pending"] = pend


def _is_real_decoder_layer(module):
    return type(module).__name__ in _LAYER_CLASS_NAMES and hasattr(module, "layer_id")


def make_layer_hook(config):
    def layer_hook(module, args, output):
        if not _maybe_init(config) or not _is_real_decoder_layer(module):
            return
        with _LOCK:
            j = module.layer_id
            if j == 0 and not _STATE["meta_hook_on"]:
                module.register_forward_hook(_meta_hook, with_kwargs=True)
                _STATE["meta_hook_on"] = True
                print("[sglang_fe] meta hook installed on layer 0", flush=True)
            hf_idx = j + 1
            p = _STATE["pending"]
            if p is None or hf_idx not in _STATE["hf_indices"]:
                return
            if isinstance(output, tuple) and len(output) >= 1 and \
               isinstance(output[0], torch.Tensor) and output[0].dim() == 2:
                p["buf"][hf_idx] = output[0].detach()

    return layer_hook




def make_norm_hook(config):
    """最终归一化输出（HF hidden_states[n_layers]）。"""

    def norm_hook(module, args, output):
        if not _maybe_init(config):
            return
        with _LOCK:
            nl = _STATE["n_layers"]
            if nl not in _STATE["hf_indices"] or not isinstance(output, torch.Tensor) \
               or output.dim() != 2 or _STATE["pending"] is None:
                return
            _STATE["pending"]["buf"][nl] = output.detach()

    return norm_hook
