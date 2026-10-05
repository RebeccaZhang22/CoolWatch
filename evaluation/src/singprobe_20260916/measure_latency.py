"""Probe-head microbenchmark; excludes base-model prefill and all service overhead."""
import importlib.util,json,sys,time
from pathlib import Path
import numpy as np
import torch
from attention_core import official,last_forward
ROOT=Path(__file__).resolve().parents[3];OUT=ROOT/'evaluation/results/singprobe_20260916';CACHE=ROOT/'.runtime/singprobe-20260916';sys.path.insert(0,str(ROOT/'probe/src'))
from probe_classifiers import MultilayerResidualMLP

def main():
 torch.set_num_threads(4);torch.manual_seed(42)
 bc=torch.load(ROOT/'probe/qwen3-8b/prompt_leakage/best_probe.pt',map_location='cpu',weights_only=False);a=bc['architecture'];baseline=MultilayerResidualMLP(a['input_size'],a['hidden_sizes'],a['dropout']).cuda().eval();baseline.load_state_dict(bc['state_dict']);mean=bc['mean'].cuda().flatten();std=bc['std'].cuda().flatten()
 spec=importlib.util.spec_from_file_location('sguard','/tmp/agent-guard-SingProbe-20260916/models/guard.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);mlp=mod.GuardMLP(12288,1024,1,.1).cuda().eval();mlp.load_state_dict(torch.load(OUT/'mlp_seed_42.pt',map_location='cpu',weights_only=False)['state_dict']);attn=official()(4096,3,1,8,64,2048).cuda().eval();attn.load_state_dict(torch.load(OUT/'attention.pt',map_location='cpu',weights_only=False)['state_dict'])
 report={'device':torch.cuda.get_device_name(),'torch':torch.__version__,'measurement':'GPU CUDA events, 20 warmup +100 measured calls, FP32 MLP/baseline and BF16 autocast Attention matching evaluations; includes head feature normalization; excludes base prefill, capture and HTTP; GPU is shared with an existing serving allocation; no exclusive-device isolation','parameters':{'current':sum(p.numel() for p in baseline.parameters()),'MLP':sum(p.numel() for p in mlp.parameters()),'Attention':sum(p.numel() for p in attn.parameters())},'measurements':[]}
 for batch in [1,16]:
  for arch in ['current','MLP','Attention']:
   for length in ([128,512,2048] if arch=='Attention' else [1]):
    x=torch.randn(batch,length,3,4096,device='cuda')
    def call():
     if arch=='current':return baseline((x[:,0,0]-mean)/std)
     v=(x*torch.rsqrt(x.square().mean(-1,keepdim=True)+1e-6)).flatten(2)
     if arch=='MLP':return mlp(v[:,0])
     with torch.autocast('cuda',dtype=torch.bfloat16):return last_forward(attn,v)
    with torch.inference_mode():
     for _ in range(20):call()
     torch.cuda.synchronize();timings=[]
     for _ in range(100):
      begin=torch.cuda.Event(enable_timing=True);end=torch.cuda.Event(enable_timing=True);begin.record();call();end.record();end.synchronize();timings.append(begin.elapsed_time(end))
    report['measurements'].append({'head':arch,'batch':batch,'tokens':length,'median_ms':float(np.median(timings)),'p95_ms':float(np.quantile(timings,.95))})
 (OUT/'latency_report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
if __name__=='__main__':main()
