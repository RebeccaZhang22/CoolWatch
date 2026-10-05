#!/usr/bin/env python3
"""Frozen Qwen3 extraction: sequence tails for attention training, last tokens for audit.
Base model sees all tokens. A 2048-token tail is sufficient for the final-query
output of SingProbe's one attention block with sliding_window=2048.
"""
import argparse,hashlib,json,sys,time
from pathlib import Path
import torch
from transformers import AutoModelForCausalLM,AutoTokenizer
ROOT=Path(__file__).resolve().parents[3];OUT=ROOT/'evaluation/results/singprobe_20260916';CACHE=ROOT/'.runtime/singprobe-20260916';LAYERS=[11,23,35];WINDOW=2048

def canonical(messages):return hashlib.sha256(json.dumps(messages,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--attention-audit',action='store_true');args=ap.parse_args()
 torch.set_num_threads(4);out=CACHE/('attention_audit_cache' if args.attention_audit else 'sequence_cache');out.mkdir(exist_ok=True)
 if args.attention_audit:
  from attention_core import official,last_forward,batch_features
  attn=official()(4096,3,1,8,64,2048).to('cuda');attn.load_state_dict(torch.load(OUT/'attention.pt',map_location='cpu',weights_only=False)['state_dict']);attn.eval()
 tokenizer=AutoTokenizer.from_pretrained(ROOT/'.runtime/models/Qwen3-8B',local_files_only=True)
 raw=[json.loads(l) for l in (ROOT/'.runtime/qwen3-8b-retrain-20260915/leakage_data/all_samples.jsonl').open()]
 groups={'fit':[r for r in raw if r['split'] in ['train','val']]}
 seen={s:set() for s in ['train','val','test']};queries={s:set() for s in seen}
 for r in raw:
  seen[r['split']].add(canonical(r['messages']));queries[r['split']].add(r['messages'][-1]['content'].strip())
 for name in ['sys_mixed','rag_mixed']:
  groups[name]=[]
  for suffix,label in [('attack',1),('benign',0)]:
   for i,r in enumerate(json.load((ROOT/f'.other/leakgauge/data_input/{name}/unseen_all_{suffix}.json').open())):
    h=canonical(r['messages']);q=r['messages'][-1]['content'].strip()
    groups[name].append({'messages':r['messages'],'sample_id':f'{name}_{suffix}_{i}','label':label,'split':'audit','category':name,'overlap':{s:h in v for s,v in seen.items()},'query_overlap':{s:q in v for s,v in queries.items()}})
 reference=json.load((ROOT/'.runtime/qwen3-8b-retrain-20260915/reference-v2.json').open())
 groups['test']=[r for r in raw if r['split']=='test']
 groups['scenario']=[{'sample_id':r['name'],'messages':r['payload']['messages'],'tools':r['payload'].get('tools'),'split':'audit','reference':r['reference'],'category':'finance_scenario'} for r in reference]
 model=AutoModelForCausalLM.from_pretrained(ROOT/'.runtime/models/Qwen3-8B',local_files_only=True,dtype=torch.bfloat16,attn_implementation='sdpa').to('cuda').eval();base=model.model
 captured={};lengths=[];fit=False
 def hook(index):
  def capture(module,inputs,output):
   h=output[0] if isinstance(output,tuple) else output
   if index in LAYERS:
    captured[index]=[h[i,max(0,n-WINDOW):n].to('cpu',dtype=torch.float16) if fit or args.attention_audit else h[i,n-1].to('cpu',dtype=torch.float16) for i,n in enumerate(lengths)]
   if index in [12,22]:captured['base'+str(index)]=torch.stack([h[i,n-1] for i,n in enumerate(lengths)]).to('cpu',dtype=torch.float16)
  return capture
 handles=[base.layers[i].register_forward_hook(hook(i)) for i in sorted(set(LAYERS+[12,22]))]
 contract={'model':str((ROOT/'.runtime/models/Qwen3-8B').resolve()),'layers':LAYERS,'window':WINDOW,'base_input':'full conversation, no truncation','tail':'last <=2048 tokens after full base-model forward','dtype':'BF16 base / FP16 cache','template':'Qwen3 enable_thinking=True add_generation_prompt=True','source_revision':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
 (out/'contract.json').write_text(json.dumps(contract,indent=2))
 # Audit first so benchmark scores are available while sequence extraction runs.
 if args.attention_audit:
  # Predeclared 512-example RAG audit subset, hash-ranked within labels; no score selection.
  groups['rag_mixed']=sum([sorted([r for r in groups['rag_mixed'] if r['label']==label],key=lambda r:hashlib.sha256(r['sample_id'].encode()).hexdigest())[:256] for label in [0,1]],[])
 for name in (['sys_mixed','rag_mixed','scenario','test'] if args.attention_audit else ['sys_mixed','rag_mixed','scenario','fit']):
  rows=groups[name];fit=name=='fit';folder=out/name;folder.mkdir(exist_ok=True)
  encoded=[]
  for r in rows:
   kw={'tools':r['tools']} if r.get('tools') else {}
   text=tokenizer.apply_chat_template(r['messages'],tokenize=False,add_generation_prompt=True,enable_thinking=True,**kw)
   ids=tokenizer.encode(text,add_special_tokens=False)
   if len(ids)>16384:raise ValueError((r['sample_id'],len(ids)))
   encoded.append((r,ids))
  encoded.sort(key=lambda x:len(x[1]));start=time.monotonic()
  print(name,len(rows),'tokens',sum(len(v) for _,v in encoded),flush=True)
  for startidx in range(0,len(encoded),64):
   target=folder/f'{startidx//64:04d}.pt';subset=encoded[startidx:startidx+64]
   if target.exists():
    saved=torch.load(target,map_location='cpu',weights_only=False);assert [r['sample_id'] for r in saved['rows']]==[r['sample_id'] for r,_ in subset];continue
   feats=[];b12=[];b22=[];meta=[];attn_scores=[];offset=0
   while offset<len(subset):
    stop=offset+1
    while stop<len(subset) and stop-offset<16 and (stop-offset+1)*len(subset[stop][1])<=8192:stop+=1
    batch=subset[offset:stop];lengths=[len(v) for _,v in batch];width=max(lengths)
    ids=torch.full((len(batch),width),tokenizer.pad_token_id,dtype=torch.long,device='cuda');mask=torch.zeros_like(ids)
    for i,(_,t) in enumerate(batch):ids[i,:len(t)]=torch.tensor(t,device='cuda');mask[i,:len(t)]=1
    captured={}
    with torch.inference_mode():base(input_ids=ids,attention_mask=mask,use_cache=False)
    for i,(r,t) in enumerate(batch):
     feature=torch.stack([captured[l][i] for l in LAYERS],dim=-2)
     if args.attention_audit:
      ax,am=batch_features([feature],'cuda')
      with torch.inference_mode(),torch.autocast('cuda',dtype=torch.bfloat16):attn_scores.append(float(last_forward(attn,ax,am)[0]))
      feature=feature[-1].clone()
     feats.append(feature);meta.append({k:v for k,v in r.items() if k not in ['messages','tools','query','system_prompt'] }|{'token_count':len(t),'message_sha256':canonical(r['messages'])})
    b12.extend(captured['base12']);b22.extend(captured['base22']);offset=stop
   torch.save({'rows':meta,'features':feats,'attention_scores':attn_scores,'baseline12':torch.stack(b12),'baseline22':torch.stack(b22),'contract':contract},target)
   if (startidx//64)%8==0:print(name,min(startidx+64,len(rows)),len(rows),'seconds',round(time.monotonic()-start,1),flush=True)
  (folder/'complete.json').write_text(json.dumps({'n':len(rows),'tokens':sum(len(v) for _,v in encoded),'seconds':time.monotonic()-start}))
 print('COMPLETE',flush=True)
if __name__=='__main__':main()
