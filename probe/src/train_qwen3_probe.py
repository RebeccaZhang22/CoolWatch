#!/usr/bin/env python3
"""Select ONE unified activation classifier using validation only; audit once."""
import argparse
import copy
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import torch
from sklearn.metrics import roc_auc_score, average_precision_score, roc_curve

from probe_classifiers import MultilayerResidualMLP, score_activations
from probe_features import load_shards


def metrics(y, score, threshold):
    y = np.asarray(y, dtype=int)
    score = np.asarray(score, dtype=float)
    p = score >= threshold
    pos, neg = int(sum(y == 1)), int(sum(y == 0))
    tp, fp = int(sum(p & (y == 1))), int(sum(p & (y == 0)))
    fn, tn = pos-tp, neg-fp
    return dict(samples=len(y), positives=pos, negatives=neg,
                auroc=float(roc_auc_score(y,score)) if pos and neg else None,
                auprc=float(average_precision_score(y,score)) if pos and neg else None,
                tpr=tp/pos if pos else None, fpr=fp/neg if neg else None,
                precision=tp/(tp+fp) if tp+fp else 0,
                f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0,
                accuracy=(tp+tn)/len(y), tp=tp, fp=fp, tn=tn, fn=fn)


def operating_point(y, scores, limit, groups=None):
    fpr,tpr,thresholds = roc_curve(y,scores,drop_intermediate=False)
    allowed = fpr <= limit+1e-12
    if groups is not None:
        # Keep a small new tool-context slice from hiding its false positives
        # behind thousands of legacy validation negatives.
        for group in sorted(set(groups)):
            negatives = np.sort(np.asarray(scores)[(np.asarray(groups)==group) & (np.asarray(y)==0)])
            if len(negatives):
                group_fpr = (len(negatives)-np.searchsorted(negatives,thresholds,side='left'))/len(negatives)
                allowed &= group_fpr <= limit+1e-12
    valid = np.flatnonzero(allowed).tolist()
    i = max(valid,key=lambda i:(tpr[i],-fpr[i],thresholds[i]))
    threshold = float(thresholds[i])
    if not np.isfinite(threshold):
        threshold = float(np.nextafter(float(np.max(scores)), np.inf))
    else:
        lower = np.asarray(scores)[np.asarray(scores) < threshold]
        if len(lower):
            # Put the boundary between observed scores, so CPU/GPU rounding at
            # an exact validation score cannot change a selected decision.
            threshold = (threshold + float(lower.max())) / 2
    return threshold, metrics(y,scores,threshold)


def selection_key(candidate):
    m = candidate['validation']
    return (m['tpr'], -m['fpr'], m['auroc'], m['auprc'])


def summarize_groups(rows, scores, threshold):
    y = [r['label'] for r in rows]
    result = {'overall': metrics(y,scores,threshold)}
    for field in ['category','language','dataset_origin','source','stage']:
        result['by_'+field] = {}
        for value in sorted({str(r.get(field, 'unknown')) for r in rows}):
            idx = [i for i,r in enumerate(rows) if str(r.get(field,'unknown')) == value]
            result['by_'+field][value] = metrics(np.asarray(y)[idx],np.asarray(scores)[idx],threshold)
    return result


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--task', choices=['harmful','prompt_leakage'], default='prompt_leakage')
    ap.add_argument('--features',type=Path,required=True)
    ap.add_argument('--dataset',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--device',default='cuda:0')
    ap.add_argument('--epochs',type=int,default=40)
    ap.add_argument('--max-validation-fpr',type=float,default=.02)
    ap.add_argument('--seed',type=int,default=42)
    ap.add_argument('--validation-group-field',help='Also constrain validation FPR within every value of this field')
    args=ap.parse_args()
    torch.set_num_threads(4)
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    if (args.output/'best_probe.pt').exists():
        raise FileExistsError('Refusing to overwrite a completed checkpoint')
    args.output.mkdir(parents=True,exist_ok=True)
    features,rows,info=load_shards(args.features/'main')
    manifest=json.loads((args.features/'main/manifest.json').read_text())
    ids={s:torch.tensor([i for i,r in enumerate(rows) if r['split']==s],dtype=torch.long) for s in ['train','val','test']}
    if not ids['train'].numel() or not ids['val'].numel():
        raise ValueError('Both train and validation samples are required')
    y=torch.tensor([r['label'] for r in rows],dtype=torch.float32)
    # Only train and validation are materialized on the accelerator for selection.
    train=features[ids['train']].to(args.device,dtype=torch.float32)
    mean=train.mean(0)
    std=train.std(0).clamp_min(1e-5)
    train=(train-mean)/std
    val=(features[ids['val']].to(args.device,dtype=torch.float32)-mean)/std
    yt=y[ids['train']].to(args.device)
    yv=y[ids['val']].numpy().astype(int)
    validation_groups = ([str(rows[i].get(args.validation_group_field,'legacy')) for i in ids['val'].tolist()]
                         if args.validation_group_field else None)
    pos_weight=(len(yt)-yt.sum())/yt.sum()
    L,D=train.shape[1:]
    weight=torch.nn.Parameter(torch.randn(L,D,device=args.device)*.01)
    bias=torch.nn.Parameter(torch.zeros(L,device=args.device))
    opt=torch.optim.AdamW([weight,bias],lr=.001,weight_decay=.001)
    best_keys=[(-1,)]*L
    best_linear=[None]*L
    start=time.monotonic()
    for epoch in range(1,args.epochs+1):
        perm=torch.randperm(len(train),device=args.device)
        for indices in perm.split(256):
            logits=torch.einsum('nld,ld->nl',train[indices],weight)+bias
            loss=torch.nn.functional.binary_cross_entropy_with_logits(logits,yt[indices,None].expand_as(logits),pos_weight=pos_weight)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
        with torch.inference_mode():
            vs=(torch.einsum('nld,ld->nl',val,weight)+bias).cpu().numpy()
        for layer in range(L):
            threshold,m=operating_point(yv,vs[:,layer],args.max_validation_fpr,validation_groups)
            candidate={'classifier_type':'linear','layer':layer,'epoch':epoch,'threshold':threshold,'validation':m}
            key=selection_key(candidate)
            if key>best_keys[layer]:
                best_keys[layer]=key
                best_linear[layer]={**candidate,'weight':weight[layer].detach().cpu().clone(),
                                    'bias':bias[layer].detach().cpu().clone()}
        if epoch==1 or epoch%5==0:
            top=max(best_linear,key=selection_key)
            print(f'linear epoch={epoch} top_layer={top["layer"]} val={top["validation"]} elapsed={time.monotonic()-start:.1f}s',flush=True)
    # Predetermined small nonlinear sweep over the three strongest validation layers.
    top_layers=[c['layer'] for c in sorted(best_linear,key=selection_key,reverse=True)[:3]]
    candidates=best_linear[:]
    for layer in top_layers:
        for hidden in [[64,32],[128,32]]:
            torch.manual_seed(args.seed)
            model=MultilayerResidualMLP(D,hidden,.1).to(args.device)
            optimizer=torch.optim.AdamW(model.parameters(),lr=.0003,weight_decay=.001)
            best=None
            stale=0
            for epoch in range(1,args.epochs+1):
                model.train()
                for idx in torch.randperm(len(train),device=args.device).split(256):
                    logits=model(train[idx,layer])
                    loss=torch.nn.functional.binary_cross_entropy_with_logits(logits,yt[idx],pos_weight=pos_weight)
                    optimizer.zero_grad(set_to_none=True)
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(model.parameters(),5.)
                    optimizer.step()
                model.eval()
                with torch.inference_mode():
                    scores=model(val[:,layer]).cpu().numpy()
                threshold,m=operating_point(yv,scores,args.max_validation_fpr,validation_groups)
                candidate={'classifier_type':'multilayer_mlp','layer':layer,'hidden_sizes':hidden,
                           'dropout':.1,'epoch':epoch,'threshold':threshold,'validation':m}
                if best is None or selection_key(candidate)>selection_key(best):
                    best={**candidate,'state_dict':copy.deepcopy({k:v.cpu() for k,v in model.state_dict().items()})}
                    stale=0
                else:
                    stale+=1
                if stale>=10:
                    break
            candidates.append(best)
            print('MLP',json.dumps({k:v for k,v in best.items() if k!='state_dict'}),flush=True)
    selected=max(candidates,key=selection_key)
    layer=selected['layer']
    summary_candidates=[{k:v for k,v in c.items() if k not in ['weight','bias','state_dict']} for c in candidates]
    checkpoint=dict(schema='perspective_watch.activation_probe_checkpoint.v2',
                    task=args.task, classifier_type=selected['classifier_type'],
                    model_info={**info,'layer_indices':[layer]}, extraction_contract=manifest,
                    feature_type='residual',feature_transform='raw',feature_layer_indices=[layer],selected_layers=[layer],
                    start_layer=0,end_layer=0,absolute_start_layer=layer,absolute_end_layer=layer,
                    mean=mean[layer:layer+1].cpu(),std=std[layer:layer+1].cpu(),threshold=selected['threshold'],
                    probability_threshold=float(torch.sigmoid(torch.tensor(selected['threshold'],dtype=torch.float64))),
                    prediction_rule='logit >= threshold', dataset_path=str(args.dataset.resolve()),
                    dataset_manifest_sha256=hashlib.sha256((args.dataset/'manifest.json').read_bytes()).hexdigest(),
                    label_definition={0:'benign',1:args.task},
                    training_selection={'split':'val','max_validation_fpr':args.max_validation_fpr,
                    'validation_group_field':args.validation_group_field,
                    'rule':'max TPR at constrained FPR, then lower FPR, then AUROC, then AUPRC',
                    'selected_candidate':{k:v for k,v in selected.items() if k not in ['weight','bias','state_dict']},
                    'seed':args.seed,'epochs':args.epochs,'linear_lr':.001,'mlp_lr':.0003,
                    'weight_decay':.001,'batch_size':256,'pos_weight':float(pos_weight),
                    'mlp_top_layers_from_validation':top_layers})
    if selected['classifier_type']=='linear':
        checkpoint.update(weight=selected['weight'],bias=selected['bias'])
    else:
        checkpoint.update(state_dict=selected['state_dict'],architecture=dict(input_size=D,
                          hidden_sizes=selected['hidden_sizes'],dropout=.1,activation='gelu',input_layer_norm=True))
    torch.save(checkpoint,args.output/'best_probe.pt')
    (args.output/'candidates.json').write_text(json.dumps(summary_candidates,indent=2))
    # Selection is frozen before any test or external-audit scores are computed.
    loaded=torch.load(args.output/'best_probe.pt',map_location='cpu',weights_only=False)
    val_replay=score_activations(loaded,features[ids['val'],layer:layer+1]).numpy()
    replay=metrics(yv,val_replay,loaded['threshold'])
    expected=selected['validation']
    for k in ['tp','fp','tn','fn']:
        if replay[k] != expected[k]:
            raise AssertionError(f'Checkpoint replay mismatch: {k}: {replay[k]} vs {expected[k]}')
    report={'checkpoint':str((args.output/'best_probe.pt').resolve()),'selected':checkpoint['training_selection'],
            'extraction_contract':manifest,'checkpoint_reload_validation':replay,'evaluations':{}}
    report['training_environment']={'torch':torch.__version__,'device':args.device}
    report['script_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')}
    report['model_weight_sha256']={}
    for path in sorted(Path(info['model_path']).glob('*.safetensors')):
        with path.open('rb') as handle:
            report['model_weight_sha256'][path.name]=hashlib.file_digest(handle,'sha256').hexdigest()
    for split in ['val','test']:
        idx=ids[split]
        if not idx.numel():
            continue
        subset=[rows[i] for i in idx.tolist()]
        scores=score_activations(loaded,features[idx,layer:layer+1]).numpy()
        report['evaluations'][split]=summarize_groups(subset,scores,loaded['threshold'])
        with (args.output/f'{split}_predictions.jsonl').open('w') as f:
            for row,score in zip(subset,scores):
                f.write(json.dumps(dict(sample_id=row['sample_id'],label=row['label'],category=row['category'],
                        source=row['source'],score=float(score),prediction=int(score>=loaded['threshold'])))+'\n')
    for directory in sorted(args.features.iterdir()):
        if not directory.is_dir() or directory.name=='main':
            continue
        audit,arows,ainfo=load_shards(directory)
        assert ainfo==info
        scores=score_activations(loaded,audit[:,layer:layer+1]).numpy()
        report['evaluations'][directory.name]=summarize_groups(arows,scores,loaded['threshold'])
        with (args.output/f'{directory.name}_predictions.jsonl').open('w') as f:
            for row,score in zip(arows,scores):
                f.write(json.dumps(dict(sample_id=row['sample_id'],label=row['label'],category=row['category'],
                        source=row['source'],score=float(score),prediction=int(score>=loaded['threshold'])))+'\n')
    report['checkpoint_sha256']=hashlib.sha256((args.output/'best_probe.pt').read_bytes()).hexdigest()
    (args.output/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False))
    lines=['# Qwen3-8B activation probe','',
           f'Binary risk classifier for {args.task}. '
           f'Selected {selected["classifier_type"]} at zero-based decoder block {layer}.','',
           f'Logit threshold: {loaded["threshold"]:.8f}; probability threshold: {loaded["probability_threshold"]:.8f}. '
           'Predict risk when logit >= threshold. Layer, architecture, epoch and threshold use validation only.','',
           '| Evaluation | N | AUROC | TPR | FPR |','|---|---:|---:|---:|---:|']
    for name,entry in report['evaluations'].items():
        m=entry['overall']
        def fmt(value): return f'{value:.4f}' if value is not None else 'N/A'
        lines.append(f'| {name} | {m["samples"]} | {fmt(m["auroc"])} | {fmt(m["tpr"])} | {fmt(m["fpr"])} |')
    lines+=['','See report.json for each category, language and source. The legacy external audits remain evaluation only.',
            'These labels measure theft intent, not actual leak success. See dataset manifest for task scope.',
            'The base model is frozen; only the probe is trained. Raw block output is taken BEFORE final RMSNorm.',
            'Use the bundled extract_qwen3_activations.py with this exact model and rendering contract.']
    (args.output/'README.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({name:entry['overall'] for name,entry in report['evaluations'].items()},indent=2),flush=True)
    print('TRAINING AND AUDITS COMPLETE',flush=True)


if __name__=='__main__':
    main()
