#!/usr/bin/env python3
import importlib.util,json,sys
from pathlib import Path
import numpy as np
import torch
ROOT=Path(__file__).resolve().parents[3];OUT=ROOT/'evaluation/results/singprobe_20260916';CACHE=ROOT/'.runtime/singprobe-20260916';sys.path.insert(0,str(ROOT/'probe/src'))
from probe_classifiers import score_activations
from train_qwen3_probe import metrics

def main():
 torch.set_num_threads(4)
 spec=importlib.util.spec_from_file_location('sguard','/tmp/agent-guard-SingProbe-20260916/models/guard.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
 baseline=torch.load(ROOT/'probe/qwen3-8b/prompt_leakage/best_probe.pt',map_location='cpu',weights_only=False)
 allreport={}
 for name in ['sys_mixed','rag_mixed','scenario']:
  p=CACHE/'sequence_cache'/name
  if not (p/'complete.json').exists():continue
  shards=[torch.load(f,map_location='cpu',weights_only=False) for f in sorted(p.glob('*.pt'))]
  rows=[r for s in shards for r in s['rows']];x=torch.stack([f for s in shards for f in s['features']]).float();b=torch.cat([s['baseline12'] for s in shards])[:,None,:]
  x=(x*torch.rsqrt(x.square().mean(-1,keepdim=True)+1e-6)).flatten(1)
  bs=score_activations(baseline,b).numpy();entry={'n':len(rows),'models':{}}
  pred=[{'sample_id':r['sample_id'],'label':r.get('label'),'baseline_score':float(s),'baseline_flagged':bool(s>=baseline['threshold'])} for r,s in zip(rows,bs)]
  if name=='scenario':
   for r,prediction in zip(rows,pred):
    ref=r['reference']['prompt_leakage'];score=float(torch.sigmoid(torch.tensor(prediction['baseline_score'])));prediction['reference']=r['reference'];prediction['reference_score_difference']=abs(score-ref['score']);assert prediction['baseline_flagged']==ref['flagged'],r['sample_id']
  else:
   y=np.array([r['label'] for r in rows]);entry['baseline']=metrics(y,bs,baseline['threshold'])
   for field in ['overlap','query_overlap']:entry[field]={s:sum(r[field][s] for r in rows) for s in ['train','val','test']}
  for seed in [42,43,44]:
   ck=torch.load(OUT/f'mlp_seed_{seed}.pt',map_location='cpu',weights_only=False);model=mod.GuardMLP(12288,1024,1,.1);model.load_state_dict(ck['state_dict']);model.eval()
   with torch.inference_mode():scores=torch.cat([model(v).flatten() for v in x.split(512)]).numpy()
   threshold=ck['thresholds']['0.02']
   for r,score in zip(pred,scores):r[f'singprobe_{seed}_score']=float(score);r[f'singprobe_{seed}_flagged']=bool(score>=threshold)
   if name!='scenario':
    masks={'all':np.ones(len(y),dtype=bool),'no_exact_train_val_overlap':np.array([not(r['overlap']['train'] or r['overlap']['val']) for r in rows]),'no_query_train_val_overlap':np.array([not(r['query_overlap']['train'] or r['query_overlap']['val']) for r in rows])}
    entry['models'][str(seed)]={k:{'singprobe':metrics(y[mask],scores[mask],threshold),'baseline':metrics(y[mask],bs[mask],baseline['threshold'])} for k,mask in masks.items() if mask.any()}
  if name=='scenario':entry['cases']=pred
  (OUT/f'{name}_predictions.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in pred));allreport[name]=entry
 (OUT/'benchmark_report.json').write_text(json.dumps(allreport,indent=2));print(json.dumps(allreport,indent=2))
if __name__=='__main__':main()
