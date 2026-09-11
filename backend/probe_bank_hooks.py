"""Reuse upstream tap lifecycle with per-layer token positions for the mixed bank."""
import json
from pathlib import Path

import numpy as np
import torch
from sglang_fe import hooks as upstream


def _flush_positions():
    state = upstream._STATE
    pending, state['pending'] = state['pending'], None
    if not pending or not pending.get('meta') or not pending['buf']:
        return
    rids, lengths = pending['meta']
    if not rids or not lengths:
        return
    ends = np.cumsum(lengths)
    record = {}
    for layer, hidden in pending['buf'].items():
        # FYH layer 7 = HF 8 at T-3; original probes remain at T-1.
        offset = 3 if layer == 8 else 1
        if min(lengths) < offset or hidden.shape[0] != int(ends[-1]):
            continue  # short warm-up / flush requests carry no real decision
        positions = torch.as_tensor(ends - offset, device=hidden.device)
        record[f'hf_{layer}'] = hidden[positions].to(torch.float16).cpu().numpy()
    if record:
        path = Path(state['spool_dir']) / f"fwd_{state['fwd_counter']:06d}.npz"
        state['fwd_counter'] += 1
        np.savez(path, meta=json.dumps(rids), **record)


def make_layer_hook(config):
    upstream._flush_locked = _flush_positions
    original_hook = upstream.make_layer_hook(config)

    def layer_hook(module, args, output):
        original_hook(module, args, output)
        if not upstream._is_real_decoder_layer(module) or module.layer_id not in (7, 14):
            return
        with upstream._LOCK:
            layer_hf = module.layer_id + 1
            pending = upstream._STATE['pending']
            if pending is None or layer_hf not in upstream._STATE['hf_indices']:
                return
            # SGLang defers the residual addition until the next layer's
            # fused norm. HF's layer output includes that residual already.
            # Preserve the original bank's tap convention for all other layers.
            hidden, residual = output
            pending['buf'][layer_hf] = (hidden + residual).detach() if residual is not None else hidden.detach().clone()

    return layer_hook


def make_norm_hook(config):
    upstream._flush_locked = _flush_positions
    return upstream.make_norm_hook(config)
