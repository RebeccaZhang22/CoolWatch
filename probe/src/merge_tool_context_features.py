"""Reuse compatible v3 Qwen3 features and append freshly extracted tool views."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import torch
from transformers import AutoTokenizer
from probe_features import load_shards
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.qwen3_rendering import normalize_tool_calls


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--base',type=Path,required=True)
    ap.add_argument('--run',type=Path,required=True)
    args=ap.parse_args()
    torch.set_num_threads(4)
    base_data=args.base/'leakage_data'
    addition_data=args.run/'additions_data'
    base_features=args.base/'leakage_features'
    addition_features=args.run/'additions_features'
    old=json.loads((base_features/'main/manifest.json').read_text())
    new=json.loads((addition_features/'main/manifest.json').read_text())
    ignored={'rendering','samples','data_sha256','num_shards'}
    for key in old:
        if key not in ignored and old[key]!=new.get(key):
            raise ValueError(f'Incompatible feature contract: {key}')
    contract={k:v for k,v in new.items() if k not in {'samples','data_sha256','num_shards'}}
    base_rows=[json.loads(x) for x in (base_data/'all_samples.jsonl').read_text().splitlines()]
    extra_rows=[json.loads(x) for x in (addition_data/'all_samples.jsonl').read_text().splitlines()]
    assert hashlib.sha256((base_data/'all_samples.jsonl').read_bytes()).hexdigest()==old['data_sha256']
    assert hashlib.sha256((addition_data/'all_samples.jsonl').read_bytes()).hexdigest()==new['data_sha256']
    tokenizer=AutoTokenizer.from_pretrained(old['model_path'],local_files_only=True)
    for row in base_rows:
        assert not row.get('tools') and not any(m.get('tool_calls') for m in row['messages'])
        original=tokenizer.apply_chat_template(row['messages'],tokenize=False,add_generation_prompt=True,enable_thinking=True)
        updated=tokenizer.apply_chat_template(normalize_tool_calls(row['messages']),tools=None,tokenize=False,add_generation_prompt=True,enable_thinking=True)
        if original!=updated:
            raise ValueError('Legacy rendering changed; cached activations cannot be reused')
    print('All 19580 legacy rendered prompts remain byte-identical',flush=True)
    data=args.run/'combined_data'; features=args.run/'combined_features'; out=features/'main'
    data.mkdir(exist_ok=False);out.mkdir(parents=True,exist_ok=False)
    rows=base_rows+extra_rows
    raw=''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows)
    (data/'all_samples.jsonl').write_text(raw)
    digest=hashlib.sha256(raw.encode()).hexdigest()
    manifest=dict(schema='protected_asset_theft.tool_context.v1',samples=len(rows),
        base_manifest=json.loads((base_data/'manifest.json').read_text()),
        additions_manifest=json.loads((addition_data/'manifest.json').read_text()),
        by_split=dict(Counter(r['split'] for r in rows)),by_label=dict(Counter(r['label'] for r in rows)),
        reuse_check='Every legacy rendered prompt is byte-identical; model, layer, dtype, config hash and library versions match.',
        selection='Validation only, FPR <= 2% overall and separately by stage. Original test/audits and known regression excluded from selection.')
    (data/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    offset=0;index=0
    paths=[(p,old['data_sha256']) for p in sorted((base_features/'main').glob('shard_*_of_*.pt'))]
    paths += [(p,new['data_sha256']) for p in sorted((addition_features/'main').glob('shard_*_of_*.pt'))]
    for p,expected_hash in paths:
        shard=torch.load(p,map_location='cpu',weights_only=False)
        assert shard['data_sha256']==expected_hash
        is_new=p.parent==addition_features/'main'
        metadata=[]
        for row in shard['metadata']:
            absolute=row['sample_index']+(len(base_rows) if is_new else 0)
            assert row['sample_id']==rows[absolute]['sample_id']
            metadata.append({**row,'sample_index':absolute})
        torch.save({**contract,'contract':contract,'data_sha256':digest,'num_shards':len(paths),
                    'shard_index':index,'features':shard['features'],'metadata':metadata},out/f'shard_{index:03d}_of_{len(paths):03d}.pt')
        index+=1;offset+=len(metadata)
    assert offset==len(rows)
    (out/'manifest.json').write_text(json.dumps({**contract,'samples':len(rows),'data_sha256':digest,'num_shards':len(paths)},indent=2))
    (data/'external_audits').mkdir()
    for source in [base_features,addition_features]:
        for directory in sorted(source.iterdir()):
            if directory.is_dir() and directory.name!='main':
                (features/directory.name).symlink_to(directory.resolve(),target_is_directory=True)
    for source in [base_data,addition_data]:
        for path in sorted((source/'external_audits').glob('*.jsonl')):
            (data/'external_audits'/path.name).symlink_to(path.resolve())
    print(json.dumps({'samples':offset,'shards':index,'splits':manifest['by_split']}),flush=True)


if __name__=='__main__':
    main()
