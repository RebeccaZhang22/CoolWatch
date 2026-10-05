"""Qwen3-8B shared-prefill adapter for the three production risk detectors.

Run with the source project's sglang environment. No training assets are copied.
"""
import argparse
import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
from pathlib import Path
import sys
import time


EXPECTED_IPI_CHECKPOINT_SHA256 = "a1e6ca136a49b769409d4b9679ae704f1f30b7d8550c4988a7a83aa8431f5278"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-root', required=True)
    parser.add_argument('--model', default='qwen3-8b', choices=['qwen3-8b'])
    parser.add_argument('--model-path', required=True)
    parser.add_argument('--ipi-threshold', type=float, default=0.91)
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
    from sglang_det.core import DetectorCore
    from backend.qwen3_rendering import normalize_tool_calls as _norm_tool_calls
    from fastapi import FastAPI, HTTPException, Request
    import uvicorn
    import torch
    import numpy as np
    import sglang
    from backend.qwen3_checkpoint import Qwen3Checkpoint
    from backend.probe_batcher import ProbeBatcher, Overloaded, Unavailable
    torch.set_num_threads(4)
    if args.batch_tokens < 16384 or not 1 <= args.max_batch <= 64:
        raise ValueError('Batch token budget must cover 16K requests; max batch must be 1..64')

    model_path = Path(args.model_path).resolve()
    config = json.loads((model_path / 'config.json').read_text())
    if config['model_type'] != 'qwen3' or config['hidden_size'] != 4096 or config['num_hidden_layers'] != 36:
        raise ValueError('Expected Qwen3-8B architecture')
    probes = {risk: Qwen3Checkpoint(path, model_path, risk) for risk, path in
              [('harmful', args.content_safety_checkpoint), ('prompt_leakage', args.leakage_checkpoint)]}
    bank = dict(model=args.model, hidden=4096, n_layers=36, entries=[], thresholds={})
    for risk, probe in probes.items():
        bank['entries'].append(dict(id=f'{risk}/qwen3-8b', risk=risk, method=probe.classifier_type,
            layer_hf=probe.layer+1, w=[0.]*4096, b=0., scaler_mu=[0.]*4096, scaler_sd=[1.]*4096,
            cal_mu=0., cal_sd=1., position='T-1', checkpoint_id='sha256:'+probe.sha256))
        bank['thresholds'][risk] = {'balanced': probe.threshold}
    bank_bytes = json.dumps(bank, sort_keys=True).encode()
    ipi_checkpoint_path = Path(args.ipi_checkpoint).resolve()
    checkpoint_bytes = ipi_checkpoint_path.read_bytes()
    checkpoint_hash = hashlib.sha256(checkpoint_bytes).hexdigest()
    if checkpoint_hash != EXPECTED_IPI_CHECKPOINT_SHA256:
        raise ValueError('IPI checkpoint checksum mismatch')
    checkpoint = torch.load(ipi_checkpoint_path, map_location='cpu', weights_only=True)
    if (checkpoint['schema'] != 'fyh.probe_checkpoint.v2'
            or checkpoint['selected_layer_index'] != 22
            or checkpoint['selected_layer_indices'] != [22]
            or checkpoint['selected_positions'] != [-1]
            or checkpoint['input_dim'] != bank['hidden']
            or checkpoint['training_config']['feature_normalization'] != 'standard'):
        raise ValueError('Unsupported IPI checkpoint contract')
    state = {k: v.float().reshape(-1) for k, v in checkpoint['model_state_dict'].items()}
    if any(state[k].numel() != bank['hidden'] for k in ('input_mean', 'input_std', 'probe.weight')) or state['probe.bias'].numel() != 1:
        raise ValueError('IPI parameter dimension mismatch')
    if any(not torch.isfinite(v).all() for v in state.values()) or not (state['input_std'] > 0).all():
        raise ValueError('Invalid IPI checkpoint parameters')
    bank['entries'].append(dict(id='ipi/broad-l22', risk='ipi', method='linear_probe',
        layer_hf=23, rel_depth=23/36, val_auroc=None,
        w=state['probe.weight'].tolist(), b=state['probe.bias'].item(),
        scaler_mu=state['input_mean'].tolist(), scaler_sd=state['input_std'].tolist(),
        cal_mu=0., cal_sd=1., position='T-1', calibration='sigmoid',
        checkpoint_id='sha256:' + checkpoint_hash))
    bank['layer_union'] = sorted({e['layer_hf'] for e in bank['entries']})
    if not 0 < args.ipi_threshold < 1:
        raise ValueError('Invalid IPI threshold')
    bank['thresholds']['ipi'] = {'balanced': args.ipi_threshold}
    bank['calibration'] = {risk: 'checkpoint_standardization_then_sigmoid' for risk in ['harmful','prompt_leakage','ipi']}
    bank['protocol'] = 'Qwen3-8B enable_thinking=True; full raw block residual T-1 before final RMSNorm'
    bank['fusion'] = {risk: 'single_probe' for risk in bank['thresholds']}
    version = 'sha256:' + hashlib.sha256(bank_bytes + checkpoint_bytes + json.dumps(bank,sort_keys=True).encode()).hexdigest()
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
            hook['hook_factory'] = hook['hook_factory'].replace('sglang_fe.hooks:', 'backend.qwen3_probe_hooks:')
        kwargs.update(max_running_requests=args.max_batch, max_prefill_tokens=args.batch_tokens,
                      max_queued_requests=args.max_inflight, watchdog_timeout=60)
        return original_engine(**kwargs)
    sglang.Engine = mixed_position_engine
    core = DetectorCore(str(model_path), str(runtime_bank_path), tp_size=1,
                        max_len=16384, spool_root=str(spool),
                        mem_fraction_static=args.mem_fraction)
    def score_hidden(hidden, tokens):
        per_entry, per_risk = {}, {}
        triggered = []
        for entry_id, entry in core.entries.items():
            h = hidden[entry['layer_hf']]
            risk = entry['risk']
            if risk == 'ipi':
                x = torch.from_numpy(h).float()
                logit = ((x-state['input_mean'])/state['input_std']) @ state['probe.weight'] + state['probe.bias'][0]
                score = float(torch.sigmoid(logit))
                flagged = score >= args.ipi_threshold
            else:
                score, flagged = probes[risk].score(h)
            per_entry[entry_id] = score
            per_risk[risk] = dict(score=score, threshold=bank['thresholds'][risk]['balanced'], flagged=flagged)
            if flagged:
                triggered.append(entry_id)
        if set(per_risk) != {'harmful','ipi','prompt_leakage'} or len(per_entry) != 3:
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

    app = FastAPI(title='Qwen3-8B shadow probe bank', lifespan=lifespan)

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
                    prompt = core.tok.apply_chat_template(_norm_tool_calls(messages), tools=tools, tokenize=False, add_generation_prompt=True, enable_thinking=True)
                    ids = core.tok(prompt, truncation=False, add_special_tokens=False)['input_ids']
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
