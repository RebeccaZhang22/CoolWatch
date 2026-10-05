"""Real HTTP reference parity, held-out replay, batching and input rejection."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[2] / "probe/src")]
import random

import httpx


async def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--url',default='http://127.0.0.1:8303'); ap.add_argument('--run-root',type=Path,required=True); ap.add_argument('--output',type=Path,required=True); args=ap.parse_args()
    root=args.run_root
    result={'reference':[],'held_out':{}}
    async with httpx.AsyncClient(timeout=65) as client:
        async def detect(payload):
            response=await client.post(args.url+'/detect',json=payload); response.raise_for_status(); data=response.json()
            assert data['detector_model']=='qwen3-8b'
            assert set(data['per_risk'])=={'harmful','prompt_leakage','ipi'}
            assert data['overall']==any(v['flagged'] for v in data['per_risk'].values())
            return data
        for row in json.loads((root/'reference-v2.json').read_text()):
            data=await detect(row['payload'])
            delta={k:abs(v['score']-data['per_risk'][k]['score']) for k,v in row['reference'].items()}
            assert data['input_tokens']==row['input_tokens']
            assert max(delta.values())<.1,(row['name'],delta)
            assert all(v['flagged']==data['per_risk'][k]['flagged'] for k,v in row['reference'].items()),row['name']
            if row['name'] in ['hello','finance','lpr_clean','funds_clean']: assert not data['overall'],(row['name'],data)
            result['reference'].append(dict(name=row['name'],response=data,absolute_score_difference=delta))
        rng=random.Random(20260915)
        for task,risk in [('harmful_v2','harmful'),('leakage','prompt_leakage')]:
            rows=[json.loads(l) for l in (root/(task+'_data')/'all_samples.jsonl').open()]
            rows=[r for r in rows if r['split']=='test']
            selected=[]
            for label in [0,1]: selected+=rng.sample([r for r in rows if r['label']==label],32)
            sem=asyncio.Semaphore(8)
            async def one(row):
                async with sem: data=await detect({'messages':row['messages']})
                return dict(sample_id=row['sample_id'],label=row['label'],result=data['per_risk'][risk],batch_size=data['batch_size'])
            replies=await asyncio.gather(*(one(row) for row in selected))
            result['held_out'][risk]=dict(n=len(replies),tp=sum(r['label']==1 and r['result']['flagged'] for r in replies),fp=sum(r['label']==0 and r['result']['flagged'] for r in replies),predictions=replies)
        for payload,expected in [({'messages':[]},400),({'messages':[{'role':'user','content':'word '*20000}]},413)]:
            response=await client.post(args.url+'/detect',json=payload); assert response.status_code==expected,(response.status_code,expected)
        result['batch_stats']=(await client.get(args.url+'/batch-stats')).json()
        assert result['batch_stats']['ready'] and result['batch_stats']['largest_batch']>1
        result['bank']=(await client.get(args.url+'/bank')).json()
    args.output.write_text(json.dumps(result,indent=2))
    print(json.dumps({risk:{k:v for k,v in r.items() if k!='predictions'} for risk,r in result['held_out'].items()}))
    print('reference cases',len(result['reference']),'largest batch',result['batch_stats']['largest_batch'])


if __name__=='__main__': asyncio.run(main())
