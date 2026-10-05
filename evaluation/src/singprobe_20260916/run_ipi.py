#!/usr/bin/env python3
"""Same 90% trace holdout as audit page; fit new heads on remaining 10% only.
80/20 of adaptation traces for optimization/selection; historical adapted baseline
has additional AgentDojo pretraining and is reported separately.
"""
import copy,hashlib,importlib.util,json,sys,time
from pathlib import Path
import numpy as np
import torch
ROOT=Path(__file__).resolve().parents[3];OUT=ROOT/'evaluation/results/singprobe_20260916';CACHE=ROOT/'.runtime/singprobe-20260916'
FYH=Path('/ssd/workspace/djs/follow-your-heart');SRC=FYH/'exps/0910-evaluate-more-ipi-benchmarks/scripts';DATA=FYH/'results/probe_traces/external/mixed_qwen35_2b_20260910';ADAPT=FYH/'results/external_eval_qwen35_2b_20260910/domain_adapt_lr1e-4_l2pen10'
sys.path[:0]=[str(SRC),str(ROOT/'probe/src')]
from standalone_score import load_features_from_split_dir,load_labels
from train_qwen3_probe import metrics,operating_point

def main():
 torch.set_num_threads(4);labels=load_labels(DATA/'labels/risk_faced/labels.jsonl');split=json.load((ADAPT/'split.json').open());adapt={k:set(v) for k,v in split['adapt_traces'].items()}
 rows=[];xx=[]
 for p in sorted((DATA/'features/layersweep').iterdir()):
  if not p.is_dir():continue
  ids,x,layers=load_features_from_split_dir(p,[7,15,23]);assert layers==[7,15,23]
  dps={r['decision_point_id']:r for r in (json.loads(l) for l in (DATA/'grid_points'/p.name/'decision_points.jsonl').open())}
  source='injecagent' if p.name.startswith('injecagent') else 'agentdyn'
  for i,id in enumerate(ids):
   if id not in labels:continue
   r=dps[id];trace=r.get('trace_id') or id
   if trace not in adapt[source]:s='test'
   else:s='val' if int(hashlib.sha256(trace.encode()).hexdigest(),16)%5==0 else 'train'
   rows.append({'sample_id':id,'trace_id':trace,'label':labels[id],'source':source,'split':s});xx.append(x[i,:,0,:])
 X=torch.stack(xx);Y=np.array([r['label'] for r in rows]);ix={s:np.array([i for i,r in enumerate(rows) if r['split']==s]) for s in ['train','val','test']}
 assert len(ix['test'])==13629
 orig=torch.load(ADAPT/'checkpoints/adapted_layer_07.pt',map_location='cpu',weights_only=False)
 print('baseline state keys',orig.keys(),flush=True)
 st=orig['model_state_dict']
 orig={'input_mean':st['input_mean'],'input_std':st['input_std'],'probe_weight':st['probe.weight'].flatten(),'probe_bias':st['probe.bias'].squeeze()}
 base=(((X[:,0]-orig['input_mean'])/orig['input_std'])@orig['probe_weight']+orig['probe_bias']).numpy()
 spec=importlib.util.spec_from_file_location('sguard','/tmp/agent-guard-SingProbe-20260916/models/guard.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 device='cpu';xn=(X*torch.rsqrt(X.square().mean(-1,keepdim=True)+1e-6)).flatten(1).to(device)
 report={'scope':'Official SingProbe MLP binary last-token adaptation on cached Qwen3.5-2B features; no sequence Attention','layers':[7,15,23],'splits':{s:len(i) for s,i in ix.items()},'split_protocol':'exact historic 90% trace holdout, deterministic 80/20 split of remaining adaptation traces; no test selection','incumbent_caveat':'historical adapted linear has AgentDojo pretraining plus 10% adaptation; new heads start from scratch on 80% of the adaptation subset','models':{}}
 for arch in ['linear_scratch','singprobe_mlp']:
  for seed in [42,43,44]:
   torch.manual_seed(seed);model=(torch.nn.Linear(xn.shape[1],1) if arch=='linear_scratch' else m.GuardMLP(xn.shape[1],1024,1,.1)).to(device)
   opt=torch.optim.AdamW(model.parameters(),lr=.0003,weight_decay=.001);yt=torch.tensor(Y[ix['train']],dtype=torch.float32,device=device);train=xn[ix['train']];val=xn[ix['val']];best=None
   for epoch in range(1,31):
    model.train()
    for idx in torch.randperm(len(train)).split(128):
     loss=torch.nn.functional.binary_cross_entropy_with_logits(model(train[idx]).flatten(),yt[idx],pos_weight=(len(yt)-yt.sum())/yt.sum());opt.zero_grad(set_to_none=True);loss.backward();opt.step()
    model.eval()
    with torch.inference_mode():vs=model(val).flatten().numpy()
    th,met=operating_point(Y[ix['val']],vs,.02);key=(met['tpr'],-met['fpr'],met['auroc'])
    if best is None or key>best['key']:best={'key':key,'epoch':epoch,'threshold':th,'validation':met,'state_dict':copy.deepcopy(model.state_dict())}
   model.load_state_dict(best['state_dict']);model.eval()
   with torch.inference_mode():score=torch.cat([model(v).flatten() for v in xn.split(512)]).numpy()
   entry={'epoch':best['epoch'],'validation':best['validation'],'threshold':best['threshold'],'evaluations':{}}
   for source in ['all','agentdyn','injecagent']:
    idx=np.array([i for i in ix['test'] if source=='all' or rows[i]['source']==source]);entry['evaluations'][source]=metrics(Y[idx],score[idx],best['threshold'])
   report['models'][f'{arch}_{seed}']=entry
   torch.save(best,OUT/f'ipi_{arch}_{seed}.pt')
   (OUT/f'ipi_{arch}_{seed}_predictions.jsonl').write_text(''.join(json.dumps(rows[i]|{'score':float(score[i]),'incumbent_logit':float(base[i])})+'\n' for i in ix['test']))
   print(arch,seed,entry['evaluations']['all'],flush=True)
 report['incumbent']={}
 for source in ['all','agentdyn','injecagent']:
  idx=np.array([i for i in ix['test'] if source=='all' or rows[i]['source']==source]);report['incumbent'][source]=metrics(Y[idx],base[idx],0.)
 (OUT/'ipi_report.json').write_text(json.dumps(report,indent=2));print('COMPLETE',flush=True)
if __name__=='__main__':main()
