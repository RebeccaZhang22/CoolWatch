"""Exact last-query computation of the official one-block GuardAttnProbe."""
import importlib.util
from pathlib import Path
import torch
import torch.nn.functional as F

def official():
 p=Path('/tmp/agent-guard-SingProbe-20260916/models/sglang_attn.py')
 spec=importlib.util.spec_from_file_location('official_attn',p);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 return module.GuardAttnProbe

def last_forward(model,x,mask=None):
 # Inputs are left padded; the final position is real for every row.
 qfeat=model.proj_q(x[:,-1:]);B=x.shape[0];H=model.num_query_heads;D=model.head_dim
 q=qfeat.view(B,1,H,D).transpose(1,2)
 k=model.proj_k(x).unsqueeze(1);v=model.proj_v(x).unsqueeze(1)
 attnmask=None if mask is None else mask[:,None,None,:]
 context=F.scaled_dot_product_attention(q,k,v,attn_mask=attnmask,enable_gqa=H!=1)
 o=model.o_proj(context.transpose(1,2).reshape(B,1,H*D))
 return model.classifier(model.norm(qfeat+o))[:,0,0]

def batch_features(tensors,device):
 n=max(len(x) for x in tensors);x=torch.zeros((len(tensors),n,3,4096),device=device,dtype=torch.float32);mask=torch.zeros((len(tensors),n),device=device,dtype=torch.bool)
 for i,t in enumerate(tensors):x[i,-len(t):]=t.to(device).float();mask[i,-len(t):]=True
 x=x*torch.rsqrt(x.square().mean(-1,keepdim=True)+1e-6)
 return x.flatten(2),mask
