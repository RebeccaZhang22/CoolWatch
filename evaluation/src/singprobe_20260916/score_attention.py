import json,sys
from pathlib import Path
import numpy as np
import torch
ROOT=Path(__file__).resolve().parents[3];OUT=ROOT/'evaluation/results/singprobe_20260916';CACHE=ROOT/'.runtime/singprobe-20260916';sys.path.insert(0,str(ROOT/'probe/src'))
from train_qwen3_probe import metrics
from probe_classifiers import score_activations

def main():
 torch.set_num_threads(4);ck=torch.load(OUT/'attention.pt',map_location='cpu',weights_only=False);base=torch.load(ROOT/'probe/qwen3-8b/prompt_leakage/best_probe.pt',map_location='cpu',weights_only=False);report={}
 for name in ['sys_mixed','rag_mixed','scenario','test']:
  folder=CACHE/'attention_audit_cache'/name;assert (folder/'complete.json').exists()
  shards=[torch.load(p,map_location='cpu',weights_only=False) for p in sorted(folder.glob('*.pt'))];rows=[r for d in shards for r in d['rows']];s=np.array([v for d in shards for v in d['attention_scores']]);b=score_activations(base,torch.cat([d['baseline12'] for d in shards])[:,None,:]).numpy();pred=[]
  for r,a,c in zip(rows,s,b):pred.append({'sample_id':r['sample_id'],'label':r.get('label'),'score':float(a),'flagged':bool(a>=ck['thresholds']['0.02']),'baseline_score':float(c),'baseline_flagged':bool(c>=base['threshold'])})
  if name=='scenario':report[name]={'cases':pred}
  else:
   y=np.array([r['label'] for r in rows]);entry={'all':{'attention':metrics(y,s,ck['thresholds']['0.02']),'baseline':metrics(y,b,base['threshold'])}}
   entry['policies']={cap:metrics(y,s,threshold) for cap,threshold in ck['thresholds'].items()}
   if 'overlap' in rows[0]:
    for field in ['overlap','query_overlap']:
     mask=np.array([not (r[field]['train'] or r[field]['val']) for r in rows])
     if mask.any():entry['no_'+field]={'attention':metrics(y[mask],s[mask],ck['thresholds']['0.02']),'baseline':metrics(y[mask],b[mask],base['threshold'])}
   report[name]=entry
  (OUT/f'attention_{name}_predictions.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in pred))
 (OUT/'attention_report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
if __name__=='__main__':main()
