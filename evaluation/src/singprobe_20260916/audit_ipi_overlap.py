import hashlib,json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[3];OUT=ROOT/'evaluation/results/singprobe_20260916';CACHE=ROOT/'.runtime/singprobe-20260916';FYH=Path('/ssd/workspace/djs/follow-your-heart');DATA=FYH/'results/probe_traces/external/mixed_qwen35_2b_20260910'
sys.path.insert(0,str(ROOT/'probe/src'))
from train_qwen3_probe import metrics

def main():
 split=json.load((FYH/'results/external_eval_qwen35_2b_20260910/domain_adapt_lr1e-4_l2pen10/split.json').open());adapt={k:set(v) for k,v in split['adapt_traces'].items()};seen=set();items={};traintrace=set();testtrace=set()
 for p in sorted((DATA/'grid_points').glob('*/decision_points.jsonl')):
  src='injecagent' if p.parent.name.startswith('injecagent') else 'agentdyn'
  for r in (json.loads(l) for l in p.open()):
   req=r.get('replay_request') or r['request_payload'];body={k:req[k] for k in ['messages','tools'] if req.get(k)};h=hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()).hexdigest();items[r['decision_point_id']]=h
   trace=r.get('trace_id') or r['decision_point_id']
   if trace in adapt[src]:seen.add(h);traintrace.add(trace)
   else:testtrace.add(trace)
 assert not traintrace&testtrace
 report={'adaptation_traces':len(traintrace),'heldout_traces':len(testtrace),'trace_overlap':0,'models':{}}
 ipi=json.load((OUT/'ipi_report.json').open())
 for seed in [42,43,44]:
  pred=[json.loads(l) for l in (OUT/f'ipi_singprobe_mlp_{seed}_predictions.jsonl').open()];fresh=[r for r in pred if items[r['sample_id']] not in seen];report['exact_message_overlap_count']=len(pred)-len(fresh)
  y=[r['label'] for r in fresh];scores=[r['score'] for r in fresh];bs=[r['incumbent_logit'] for r in fresh];th=ipi['models'][f'singprobe_mlp_{seed}']['threshold'];report['models'][str(seed)]={'no_exact_adaptation_overlap':{'singprobe':metrics(y,scores,th),'incumbent':metrics(y,bs,0)}}
  # Resample whole test traces, keeping all decision points in each selected trace.
  groups={}
  for r in pred:
   group=groups.setdefault(r['trace_id'],np.zeros(8));y=r['label'];p=r['score']>=th;b=r['incumbent_logit']>=0
   group[:]+=np.array([y,1-y,p*y,p*(1-y),b*y,b*(1-y),p==y,b==y])
  counts=np.stack(list(groups.values()));rng=np.random.default_rng(20260916);deltas=[]
  for _ in range(2000):
   c=counts[rng.integers(0,len(counts),len(counts))].sum(0);deltas.append([(c[2]-c[4])/c[0],(c[3]-c[5])/c[1],(c[6]-c[7])/(c[0]+c[1])])
  report['models'][str(seed)]['paired_trace_bootstrap_delta_ci95']={k:np.quantile(np.array(deltas)[:,i],[.025,.975]).tolist() for i,k in enumerate(['tpr','fpr','accuracy'])}
 (OUT/'ipi_overlap_report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
if __name__=='__main__':main()
