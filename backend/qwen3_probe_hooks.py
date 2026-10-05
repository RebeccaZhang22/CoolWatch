"""Qwen3 raw block residuals at the last prefill token, before final norm."""
import json
from pathlib import Path
import threading

import numpy as np
import torch

_LOCK = threading.Lock()
_PENDING = None
_COUNTER = 0


def _flush(config):
    global _PENDING, _COUNTER
    pending, _PENDING = _PENDING, None
    if pending is None:
        return
    rids, lengths, buf = pending
    ends = np.cumsum(lengths)
    if not len(ends) or not buf:
        return
    record = {}
    for layer, hidden in buf.items():
        if hidden.shape[0] != int(ends[-1]):
            raise RuntimeError('Qwen3 prefill capture length mismatch')
        pos = torch.as_tensor(ends - 1, device=hidden.device)
        record[f'hf_{layer}'] = hidden[pos].to(torch.float16).cpu().numpy()
    path = Path(config['spool_dir']) / f'fwd_{_COUNTER:06d}.npz'
    _COUNTER += 1
    np.savez(path, meta=json.dumps(rids), **record)


def make_layer_hook(config):
    def hook(module, args, output):
        global _PENDING
        if type(module).__name__ != 'Qwen3DecoderLayer':
            return
        layer = module.self_attn.attn.layer_id
        with _LOCK:
            if layer == 0:
                _flush(config)
                # Qwen3Model passes forward_batch positionally to each block.
                fb = args[2]
                if fb.forward_mode.is_extend():
                    lengths = fb.extend_seq_lens_cpu
                    if lengths is None:
                        lengths = fb.extend_seq_lens.tolist()
                    _PENDING = (list(fb.rids), list(lengths), {})
            if _PENDING is not None and layer + 1 in config['hf_indices']:
                hidden, residual = output
                _PENDING[2][layer + 1] = (hidden + residual).detach() if residual is not None else hidden.detach().clone()
    return hook


def make_norm_hook(config):
    # All retrained probes use raw block output, including block 35.
    return lambda module, args, output: None
