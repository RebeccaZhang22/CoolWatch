"""Reuse only freshly extracted Qwen3 features, preserving source fixed splits."""
import hashlib
import json
from pathlib import Path
import sys
import torch

root=Path(sys.argv[1]); torch.set_num_threads(4)
ids=set(json.loads((root/'harmful_natural_ids.json').read_text()))
selected=[]; features=[]; contract=None
for folder in ['harmful_context_features/main','leakage_features/main']:
    for path in sorted((root/folder).glob('shard_*_of_*.pt')):
        ck=torch.load(path,map_location='cpu',weights_only=False)
        if contract is not None and contract!=ck['contract']: raise ValueError('Extraction contracts differ')
        contract=ck['contract']
        for i,row in enumerate(ck['metadata']):
            if folder.startswith('leakage') and row['sample_id'] not in ids: continue
            selected.append({**row,'sample_index':len(selected),'category':'harmful' if folder.startswith('harmful') else 'natural_safe'})
            features.append(ck['features']['residual'][i].clone())
# Record original materialized messages too; downstream scoring uses the shards.
source=[]
for folder in ['harmful_context_data','leakage_data']:
    source += [r for r in map(json.loads,(root/folder/'all_samples.jsonl').open()) if folder.startswith('harmful') or r['sample_id'] in ids]
data=root/'harmful_v2_data'; data.mkdir(exist_ok=True)
raw=''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in source)
(data/'all_samples.jsonl').write_text(raw)
(data/'manifest.json').write_text(json.dumps(dict(samples=len(selected),sources=['harmful_context_data','leakage_data natural/normal sources only'],split='Original source fixed splits; same-split context augmentation',extraction_contract=contract,source_data_sha256=hashlib.sha256(raw.encode()).hexdigest()),indent=2))
out=root/'harmful_v2_features/main'; out.mkdir(parents=True,exist_ok=True)
digest=hashlib.sha256(raw.encode()).hexdigest()
count=(len(selected)+511)//512
for i in range(count):
    start=i*512; end=min(start+512,len(selected))
    torch.save({**contract,'contract':contract,'data_sha256':digest,'num_shards':count,'shard_index':i,'features':{'residual':torch.stack(features[start:end])},'metadata':selected[start:end]},out/f'shard_{i:03d}_of_{count:03d}.pt')
(out/'manifest.json').write_text(json.dumps({**contract,'samples':len(selected),'data_sha256':digest,'num_shards':count},indent=2))
print('Merged',len(selected),'samples')
