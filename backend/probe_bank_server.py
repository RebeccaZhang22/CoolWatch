"""Private shared-prefill adapter for harmful, prompt leakage, and broad IPI.

Run with the source project's sglang environment. No training assets are copied.
"""
import argparse
import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import os
from pathlib import Path
import sys
import time


EXPECTED_IPI_CHECKPOINT_SHA256 = "46a68d047148be0b6ccf485be3a55966937533adfb5b9c7c01e0984982a057b4"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-root', required=True)
    parser.add_argument('--model', default='qwen35-2b')
    parser.add_argument('--port', type=int, default=8302)
    parser.add_argument('--spool', required=True)
    parser.add_argument('--mem-fraction', type=float, default=0.2)
    parser.add_argument('--content-safety-checkpoint', required=True)
    parser.add_argument('--ipi-checkpoint', required=True)
    parser.add_argument('--leakage-checkpoint', required=True)
    parser.add_argument('--max-batch', type=int, default=64)
    parser.add_argument('--batch-tokens', type=int, default=65536)
    parser.add_argument('--max-inflight', type=int, default=128)
    parser.add_argument('--batch-wait-ms', type=float, default=10)
    parser.add_argument('--request-timeout', type=float, default=60)
    args = parser.parse_args()
    root = Path(args.source_root).resolve()
    sys.path[:0] = [str(root / 'src'), str(root / 'framework/safety_probe')]
    from common import MODELS
    from sglang_det.core import DetectorCore
    from sglang_fe.extractor import build_prompt
    from fastapi import FastAPI, HTTPException, Request
    import uvicorn
    import torch
    import numpy as np
    from scipy.stats import norm
    import sglang
    from backend.content_safety_checkpoint import ContentSafetyCheckpoint
    from backend.leakage_checkpoint import LeakageCheckpoint
    from backend.probe_batcher import ProbeBatcher, Overloaded, Unavailable
    torch.set_num_threads(4)
    if args.batch_tokens < 16384 or not 1 <= args.max_batch <= 64:
        raise ValueError('Batch token budget must cover 16K requests; max batch must be 1..64')

    model_path = Path(MODELS[args.model]['path'])
    config = json.loads((model_path / 'config.json').read_text())['text_config']
    content_safety_path = Path(args.content_safety_checkpoint).resolve()
    bank_bytes = content_safety_path.read_bytes()
    content_safety = ContentSafetyCheckpoint(
        content_safety_path,
        model=args.model,
        hidden_size=config['hidden_size'],
        num_layers=config['num_hidden_layers'],
    )
    bank = content_safety.to_detector_bank()
    ipi_checkpoint_path = Path(args.ipi_checkpoint).resolve()
    checkpoint_bytes = ipi_checkpoint_path.read_bytes()
    checkpoint_hash = hashlib.sha256(checkpoint_bytes).hexdigest()
    if checkpoint_hash != EXPECTED_IPI_CHECKPOINT_SHA256:
        raise ValueError('IPI checkpoint checksum mismatch')
    checkpoint = torch.load(ipi_checkpoint_path, map_location='cpu', weights_only=True)
    if (checkpoint['schema'] != 'fyh.probe_checkpoint.v2'
            or checkpoint['selected_layer_index'] != 7
            or checkpoint['selected_layer_indices'] != [7]
            or checkpoint['selected_positions'] != [-1]
            or checkpoint['input_dim'] != bank['hidden']
            or checkpoint['training_config']['feature_normalization'] != 'standard'):
        raise ValueError('Unsupported IPI checkpoint contract')
    state = {k: v.float().reshape(-1) for k, v in checkpoint['model_state_dict'].items()}
    if any(state[k].numel() != bank['hidden'] for k in ('input_mean', 'input_std', 'probe.weight')) or state['probe.bias'].numel() != 1:
        raise ValueError('IPI parameter dimension mismatch')
    if any(not torch.isfinite(v).all() for v in state.values()) or not (state['input_std'] > 0).all():
        raise ValueError('Invalid IPI checkpoint parameters')
    leakage = LeakageCheckpoint(args.leakage_checkpoint, model_path)
    bank['entries'].append(dict(id='ipi/broad-l7', risk='ipi', method='linear_probe',
        layer_hf=8, rel_depth=8/24, val_auroc=None,
        w=state['probe.weight'].tolist(), b=state['probe.bias'].item(),
        scaler_mu=state['input_mean'].tolist(), scaler_sd=state['input_std'].tolist(),
        cal_mu=0., cal_sd=1., position='T-3', calibration='sigmoid',
        checkpoint_id='sha256:' + checkpoint_hash))
    # DetectorCore needs a linear-shaped entry to register the tap layer.
    # These placeholders are NEVER scored; the MLP above handles this entry.
    bank['entries'].append(dict(id='prompt_leakage/unified-v3', risk='prompt_leakage',
        method='multilayer_mlp', layer_hf=15, val_auroc=None,
        w=[0.] * bank['hidden'], b=0., scaler_mu=[0.] * bank['hidden'],
        scaler_sd=[1.] * bank['hidden'], cal_mu=0., cal_sd=1.,
        position='T-1', calibration='sigmoid', checkpoint_id='sha256:' + leakage.sha256))
    bank['layer_union'] = sorted({e['layer_hf'] for e in bank['entries']})
    ipi_threshold = float(checkpoint['threshold'])
    bank['thresholds']['ipi'] = {'balanced': ipi_threshold}
    bank['thresholds']['prompt_leakage'] = {'balanced': leakage.threshold}
    for retired in ('rag_leak', 'sys_leak'):
        bank['thresholds'].pop(retired, None)
    bank['calibration'] = {'harmful': bank['calibration'], 'ipi': 'checkpoint_standardization_then_sigmoid',
                           'prompt_leakage': 'checkpoint_standardization_layernorm_mlp_sigmoid'}
    bank['protocol'] = 'Harmful HF24 T-1; IPI HF8 residual-sum T-3; prompt leakage HF15 residual-sum T-1'
    bank['fusion'] = {'harmful': 'max', 'ipi': 'single_broad_l7', 'prompt_leakage': 'single_unified_v3'}
    version = 'sha256:' + hashlib.sha256(bank_bytes + checkpoint_bytes + leakage.sha256.encode() + bank['protocol'].encode()).hexdigest()
    # DetectorCore clears its spool at initialization: only give it a fresh,
    # deployment-specific directory, never the source project's shared spool.
    spool = Path(args.spool).resolve()
    if spool.exists():
        raise ValueError('Spool must be a new directory for each server process')
    spool.parent.mkdir(parents=True, exist_ok=True)
    runtime_bank_path = spool.parent / (spool.name + '-mixed-bank.json')
    runtime_bank_path.write_text(json.dumps(bank))
    original_engine = sglang.Engine
    def mixed_position_engine(**kwargs):
        for hook in kwargs['forward_hooks']:
            hook['hook_factory'] = hook['hook_factory'].replace('sglang_fe.hooks:', 'backend.probe_bank_hooks:')
        kwargs.update(max_running_requests=args.max_batch, max_prefill_tokens=args.batch_tokens,
                      max_queued_requests=args.max_inflight, watchdog_timeout=60)
        return original_engine(**kwargs)
    sglang.Engine = mixed_position_engine
    core = DetectorCore(str(model_path), str(runtime_bank_path), tp_size=1,
                        max_len=16384, spool_root=str(spool),
                        mem_fraction_static=args.mem_fraction)
    def score_hidden(hidden, tokens):
        per_entry, scores = {}, {}
        for entry_id, entry in core.entries.items():
            h = hidden[entry['layer_hf']]
            if entry['risk'] == 'ipi':
                x = torch.from_numpy(h).float()
                logit = ((x-state['input_mean'])/state['input_std']) @ state['probe.weight'] + state['probe.bias'][0]
                score = float(torch.sigmoid(logit))
            elif entry['risk'] == 'prompt_leakage':
                score, leakage_flagged = leakage.score(h)
            else:
                raw = core._score_entry(entry, h)
                score = float(norm.cdf((raw-entry['cal_mu'])/entry['cal_sd']))
            per_entry[entry_id] = score
            scores[entry['risk']] = max(scores.get(entry['risk'], 0.), score)
        per_risk = {risk: dict(score=score, threshold=bank['thresholds'][risk]['balanced'],
                              flagged=score >= bank['thresholds'][risk]['balanced'])
                    for risk, score in scores.items()}
        per_risk['prompt_leakage']['flagged'] = leakage_flagged
        triggered = [eid for eid, score in per_entry.items()
                     if score >= bank['thresholds'][core.entries[eid]['risk']]['balanced']]
        if set(per_risk) != set(core.risks) or len(per_entry) != 4:
            raise RuntimeError('Incomplete probe bank result')
        return dict(overall=any(r['flagged'] for r in per_risk.values()),
                    profile='balanced', per_risk=per_risk, per_entry=per_entry,
                    triggered_entries=triggered, detector_model=args.model,
                    bank_version=version, input_tokens=tokens)

    def run_batch(ids_list):
        # Only this worker owns the engine and spool. All members are submitted
        # together, not one Engine.generate call per HTTP request.
        rids = core._generate(ids_list)
        core._generate([[core.tok.eos_token_id]])
        features, forward_sizes = {}, []
        required = set(rids)
        # Engine.generate is synchronous. The trailing flush request has
        # completed all file writes; missing features are a failed batch.
        for path in sorted(spool.glob('fwd_*.npz')):
            with np.load(path, allow_pickle=False) as data:
                captured = json.loads(str(data['meta']))
                relevant = [(i, rid) for i, rid in enumerate(captured) if rid in required]
                if relevant:
                    forward_sizes.append(len(relevant))
                for i, rid in relevant:
                    if rid in features:
                        raise RuntimeError('Duplicate activation request ID')
                    features[rid] = {layer: data[f'hf_{layer}'][i].copy() for layer in bank['layer_union']}
            path.unlink()  # private per-process spool; dummy records are discarded
        if set(features) != required:
            raise RuntimeError('Missing activation request IDs')
        results = [score_hidden(features[rid], len(ids)) for rid, ids in zip(rids, ids_list)]
        for result in results:
            result['prefill_batch_sizes'] = forward_sizes
        return results

    batcher = ProbeBatcher(run_batch, max_batch=args.max_batch,
        token_budget=args.batch_tokens, max_inflight=args.max_inflight,
        wait_ms=args.batch_wait_ms, timeout=args.request_timeout)

    @asynccontextmanager
    async def lifespan(app):
        batcher.start()
        yield
        await batcher.close()

    app = FastAPI(title='Qwen3.5-2B shadow probe bank', lifespan=lifespan)

    @app.get('/health/ready')
    async def ready():
        if not batcher.info()['ready']:
            raise HTTPException(503, 'Probe worker unavailable')
        return batcher.info()

    @app.get('/batch-stats')
    async def stats():
        return batcher.info()

    @app.get('/bank')
    def info():
        return {**{k: bank[k] for k in ('model', 'hidden', 'n_layers', 'layer_union', 'thresholds', 'fusion', 'calibration', 'protocol')},
                'bank_version': version, 'max_len': 16384, 'batching': batcher.info(),
                'entries': [{k: e[k] for k in ('id', 'risk', 'method', 'layer_hf', 'val_auroc', 'position', 'checkpoint_id') if k in e} for e in bank['entries']]}

    @app.get('/v1/models')
    def models():
        return {'object': 'list', 'data': [{'id': args.model, 'object': 'model'}]}

    @app.post('/detect')
    async def detect(request: Request):
        start = time.perf_counter()
        try:
            batcher.reserve()
        except Overloaded as exc:
            raise HTTPException(429, str(exc), headers={'Retry-After': '1'}) from exc
        except Unavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        try:
            async with asyncio.timeout(args.request_timeout):
                body = bytearray()
                async for chunk in request.stream():
                    if len(body) + len(chunk) > 2 * 1024 * 1024:
                        raise HTTPException(413, 'Request body exceeds 2 MiB')
                    body.extend(chunk)
                try:
                    payload = json.loads(body)
                except (ValueError, UnicodeError) as exc:
                    raise HTTPException(400, 'Invalid JSON') from exc
                if not isinstance(payload, dict):
                    raise HTTPException(400, 'Expected a JSON object')
                messages, tools = payload.get('messages'), payload.get('tools')
                if (not isinstance(messages, list) or not messages or len(messages) > 128
                        or any(not isinstance(m, dict) for m in messages)):
                    raise HTTPException(400, 'messages must contain 1..128 objects')
                if tools is not None and (not isinstance(tools, list) or any(not isinstance(t, dict) for t in tools)):
                    raise HTTPException(400, 'tools must be a list of objects')
                try:
                    prompt = build_prompt(core.tok, messages, tools)
                    ids = core.tok(prompt, truncation=False)['input_ids']
                except Exception as exc:
                    raise HTTPException(400, 'Invalid conversation/template input') from exc
                if len(ids) > 16384:
                    raise HTTPException(413, 'Input exceeds the trained 16384-token context limit')
                return await batcher.submit(ids, start)
        except TimeoutError as exc:
            raise HTTPException(504, 'Probe request deadline exceeded') from exc
        except Unavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        finally:
            batcher.release()

    try:
        uvicorn.run(app, host='127.0.0.1', port=args.port, timeout_graceful_shutdown=args.request_timeout + 5)
    finally:
        core.close()


if __name__ == '__main__':
    main()
