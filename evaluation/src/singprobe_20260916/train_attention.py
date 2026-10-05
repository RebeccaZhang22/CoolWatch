#!/usr/bin/env python3
"""Train official causal MQA on full Qwen3 context features, binary boundary labels."""
import copy,json,random,sys,time
from pathlib import Path
import numpy as np
import torch
from attention_core import official,last_forward,batch_features
ROOT=Path(__file__).resolve().parents[3];OUT=ROOT/'evaluation/results/singprobe_20260916';CACHE=ROOT/'.runtime/singprobe-20260916'
sys.path.insert(0,str(ROOT/'probe/src'))
from train_qwen3_probe import operating_point

def verify():
 cls=official();torch.manual_seed(7);m=cls(12,3,1,8,8,32)
 results=[]
 for n in [7,32,41]:
  a=torch.randn(2,n,36,requires_grad=True);ref=m(a)[:,-1,0];ref.sum().backward();g=a.grad.clone();a.grad=None
  got=last_forward(m,a[:,-32:]);got.sum().backward();err=float((ref-got).detach().abs().max());ge=float((g-a.grad).abs().max());assert err<2e-6 and ge<2e-6,(err,ge);results.append({'length':n,'max_score_error':err,'max_input_gradient_error':ge})
 # Different sequence lengths share a left-padded training batch.
 a=torch.randn(1,7,36);b=torch.randn(1,19,36);p=torch.zeros(2,19,36);p[0,-7:]=a;p[1]=b
 mask=torch.zeros(2,19,dtype=torch.bool);mask[0,-7:]=True;mask[1]=True
 with torch.inference_mode():
  ref=torch.cat([m(a)[:,-1,0],m(b)[:,-1,0]]);actual=last_forward(m,p,mask)
  error=(ref-actual).abs().max().item();assert error<2e-6
 results.append({'left_padding_max_score_error':error})
 return results

def main():
 torch.set_num_threads(4);verification=verify();cache=OUT/'sequence_cache/fit';assert (cache/'complete.json').exists()
 train=[];val=[];start=time.monotonic()
 for p in sorted(cache.glob('*.pt')):
  d=torch.load(p,map_location='cpu',weights_only=False)
  for r,x in zip(d['rows'],d['features']):(train if r['split']=='train' else val).append((r,x))
 print('loaded',len(train),len(val),'seconds',time.monotonic()-start,flush=True)
 report={'scope':'Official GuardAttnProbe Qwen3 binary query-boundary adaptation; full backbone context, 2048-token causal probe window; no response safety/hallucination task labels','verification':verification,'train':len(train),'val':len(val),'config':{'layers':[11,23,35],'heads':8,'head_dim':64,'epochs':10,'lr':.0003,'weight_decay':.01,'batch_size':16,'seed':42,'selection':'validation max TPR at <=2% FPR then AUROC'},'history':[]}
 torch.manual_seed(42);rng=random.Random(42);model=official()(4096,3,1,8,64,2048).to('cuda');opt=torch.optim.AdamW(model.parameters(),lr=.0003,weight_decay=.01)
 pos=sum(r['label'] for r,_ in train);pw=torch.tensor((len(train)-pos)/pos,device='cuda');best=None;report['positive_class_weight']=float(pw);report['feature_contract']=json.load((OUT/'sequence_cache/contract.json').open())
 for epoch in range(1,11):
  model.train();order=list(range(len(train)));rng.shuffle(order);start=time.monotonic()
  for step in range(0,len(order),16):
   batch=[train[i] for i in order[step:step+16]];x,mask=batch_features([x for _,x in batch],'cuda');y=torch.tensor([r['label'] for r,_ in batch],dtype=torch.float32,device='cuda')
   with torch.autocast('cuda',dtype=torch.bfloat16):loss=torch.nn.functional.binary_cross_entropy_with_logits(last_forward(model,x,mask).float(),y,pos_weight=pw)
   opt.zero_grad(set_to_none=True);loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),2.);opt.step()
   if step%1600==0:print('train',epoch,step,'loss',float(loss),'seconds',round(time.monotonic()-start,1),flush=True)
  model.eval();scores=[]
  with torch.inference_mode():
   for j in range(0,len(val),16):
    x,mask=batch_features([x for _,x in val[j:j+16]],'cuda')
    with torch.autocast('cuda',dtype=torch.bfloat16):scores.extend(last_forward(model,x,mask).float().cpu().tolist())
  y=np.array([r['label'] for r,_ in val]);scores=np.array(scores);threshold,m=operating_point(y,scores,.02);key=(m['tpr'],-m['fpr'],m['auroc'])
  report['history'].append({'epoch':epoch,'validation':m,'seconds':time.monotonic()-start});print(report['history'][-1],flush=True)
  if best is None or key>best['key']:best={'key':key,'epoch':epoch,'state_dict':copy.deepcopy({k:v.cpu() for k,v in model.state_dict().items()}),'thresholds':{str(cap):operating_point(y,scores,cap)[0] for cap in [.01,.02,.05]},'validation':m}
 torch.save(best,OUT/'attention.pt');report['selected']={k:v for k,v in best.items() if k!='state_dict'};report['parameters']=sum(p.numel() for p in model.parameters());(OUT/'attention_training_report.json').write_text(json.dumps(report,indent=2));print('COMPLETE',flush=True)
if __name__=='__main__':main()
