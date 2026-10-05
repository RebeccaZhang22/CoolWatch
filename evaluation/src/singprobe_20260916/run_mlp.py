#!/usr/bin/env python3
"""Official SingProbe GuardMLP port to Qwen3 decision-point binary detection.
This is explicitly a last-token MLP adaptation, not token-streaming or Ling replication.
"""
import argparse,copy,hashlib,importlib.util,json,sys,time
from pathlib import Path
import numpy as np
import torch
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'probe/src'))
from train_qwen3_probe import metrics,operating_point,summarize_groups
from probe_classifiers import score_activations
LAYERS=[11,23,35] # fixed thirds of the 36-block Qwen3 backbone, chosen without evaluation labels

def load(path):
    xs=[]; rows=[]; baseline=[]
    for p in sorted(path.glob('shard_*_of_*.pt')):
        d=torch.load(p,map_location='cpu',weights_only=False)
        xs.append(d['features']['residual'][:,LAYERS].clone())
        baseline.append(d['features']['residual'][:,[12]].clone())
        rows.extend(d['metadata'])
    order=np.argsort([r['sample_index'] for r in rows])
    return torch.cat(xs)[order],torch.cat(baseline)[order],[rows[i] for i in order]

def norm(x):
    x=x.float(); return (x*torch.rsqrt(x.square().mean(-1,keepdim=True)+1e-6)).flatten(1)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--upstream',default='/tmp/agent-guard-SingProbe-20260916');ap.add_argument('--device',default='cuda:0');ap.add_argument('--epochs',type=int,default=30);args=ap.parse_args()
    torch.set_num_threads(4)
    spec=importlib.util.spec_from_file_location('official_guard',Path(args.upstream)/'models/guard.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    out=ROOT/'.runtime/singprobe-20260916';out.mkdir(exist_ok=True)
    cache=ROOT/'.runtime/qwen3-8b-retrain-20260915/leakage_features'
    X,B,rows=load(cache/'main'); y=np.array([r['label'] for r in rows]); ix={s:np.array([i for i,r in enumerate(rows) if r['split']==s]) for s in ['train','val','test']}
    # Verify the frozen input has no exact conversation crossing weight/selection/test splits.
    raw=[json.loads(l) for l in (ROOT/'.runtime/qwen3-8b-retrain-20260915/leakage_data/all_samples.jsonl').open()]
    hashes={s:set() for s in ix}
    for r in raw:
        msg=r.get('messages') or [{'role':'system','content':r['system_prompt']},{'role':'user','content':r['query']}]
        hashes[r['split']].add(hashlib.sha256(json.dumps(msg,sort_keys=True,ensure_ascii=False).encode()).hexdigest())
    overlap={a+'_'+b:len(hashes[a]&hashes[b]) for a,b in [('train','val'),('train','test'),('val','test')]}
    assert not any(overlap.values()),overlap
    train=norm(X[ix['train']]).to(args.device);val=norm(X[ix['val']]).to(args.device)
    yt=torch.tensor(y[ix['train']],dtype=torch.float32,device=args.device)
    checkpoint=torch.load(ROOT/'probe/qwen3-8b/prompt_leakage/best_probe.pt',map_location='cpu',weights_only=False)
    baseline_scores=score_activations(checkpoint,B).numpy()
    report={'scope':'Qwen3-8B official GuardMLP last-decision-token binary adaptation; not full SingProbe token supervision or Attention','layers':LAYERS,'normalization':'per-layer non-affine RMS, eps=1e-6; not trained standardization','label':'protected asset theft intent','upstream_source_sha256':hashlib.sha256((Path(args.upstream)/'models/guard.py').read_bytes()).hexdigest(),'split_counts':{s:len(v) for s,v in ix.items()},'exact_message_overlap':overlap,'seeds':{},'baseline':{},'config':{'epochs':args.epochs,'lr':.0003,'weight_decay':.001,'batch':256,'hidden':1024,'validation_fpr_cap':.02,'selection':'validation TPR at <=2% FPR, then lower FPR, then AUROC','seeds':[42,43,44]}}
    baseval=baseline_scores[ix['val']];base_thresholds={'deployed':float(checkpoint['threshold'])}
    for cap in [.01,.02,.05]:base_thresholds[str(cap)]=operating_point(y[ix['val']],baseval,cap)[0]
    datasets={'test':(X[ix['test']],B[ix['test']],[rows[i] for i in ix['test']])}
    for p in sorted(cache.iterdir()):
        if p.is_dir() and p.name!='main':datasets[p.name]=load(p)
    for name,(x,b,rs) in datasets.items():
        bs=score_activations(checkpoint,b).numpy();report['baseline'][name]={k:summarize_groups(rs,bs,t) for k,t in base_thresholds.items()}
    for seed in [42,43,44]:
        torch.manual_seed(seed);np.random.seed(seed)
        model=mod.GuardMLP(4096*3,1024,1,.1,'gelu').to(args.device)
        opt=torch.optim.AdamW(model.parameters(),lr=.0003,weight_decay=.001)
        best=None;history=[];start=time.monotonic()
        for epoch in range(1,args.epochs+1):
            model.train()
            for idx in torch.randperm(len(train),device=args.device).split(256):
                logits=model(train[idx]).squeeze(-1)
                loss=torch.nn.functional.binary_cross_entropy_with_logits(logits,yt[idx],pos_weight=(len(yt)-yt.sum())/yt.sum())
                opt.zero_grad(set_to_none=True);loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),5);opt.step()
            model.eval()
            with torch.inference_mode():scores=torch.cat([model(v).squeeze(-1) for v in val.split(512)]).cpu().numpy()
            th,m=operating_point(y[ix['val']],scores,.02);key=(m['tpr'],-m['fpr'],m['auroc'])
            history.append({'epoch':epoch,**m})
            if best is None or key>best['key']:best={'key':key,'epoch':epoch,'state':copy.deepcopy({k:v.cpu() for k,v in model.state_dict().items()}),'threshold':th,'validation':m}
            if epoch==1 or epoch%5==0:print(json.dumps({'seed':seed,'epoch':epoch,'best_epoch':best['epoch'],'val':m,'elapsed':time.monotonic()-start}),flush=True)
        model.load_state_dict(best['state']);model.eval()
        with torch.inference_mode():vs=torch.cat([model(v).squeeze(-1) for v in val.split(512)]).cpu().numpy()
        thresholds={str(cap):operating_point(y[ix['val']],vs,cap)[0] for cap in [.01,.02,.05]}
        item={'selected_epoch':best['epoch'],'thresholds':thresholds,'validation':best['validation'],'parameters':model.count_parameters(),'training_seconds':time.monotonic()-start,'history':history,'evaluations':{}}
        predictions=[]
        for name,(x,b,rs) in datasets.items():
            with torch.inference_mode():s=torch.cat([model(norm(v).to(args.device)).squeeze(-1).cpu() for v in x.split(512)]).numpy()
            bs=score_activations(checkpoint,b).numpy()
            item['evaluations'][name]={k:summarize_groups(rs,s,t) for k,t in thresholds.items()}
            for r,a,c in zip(rs,s,bs):predictions.append({'dataset':name,'sample_id':r['sample_id'],'label':r['label'],'category':r.get('category'),'score':float(a),'baseline_score':float(c)})
        torch.save({'state_dict':best['state'],'layers':LAYERS,'thresholds':thresholds,'hidden':1024,'seed':seed,'normalization':'per-layer RMS','upstream':report['upstream_source_sha256']},out/f'mlp_seed_{seed}.pt')
        (out/f'predictions_seed_{seed}.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in predictions))
        report['seeds'][str(seed)]=item
        (out/'mlp_report.json').write_text(json.dumps(report,indent=2))
    print('COMPLETE',flush=True)
if __name__=='__main__':main()
