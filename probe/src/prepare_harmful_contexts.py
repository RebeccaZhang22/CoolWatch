"""Add matched system contexts to both harmful classes without changing groups."""
import hashlib
import json
from pathlib import Path
import sys

root=Path(sys.argv[1])
original=[json.loads(l) for l in (root/'harmful_data/all_samples.jsonl').open()]
leakage=[json.loads(l) for l in (root/'leakage_data/all_samples.jsonl').open()]
# These are explicitly natural/normal tasks, not arbitrary non-theft attacks.
natural=[r for r in leakage if r['label']==0 and r['source'] in {'natural_safe_training_v1','protected_natural_calibration_v1','finvault_official_normal_training','topic_matched_minimal_pair_v2','short_conversational_theft_pairs_v1'}]
rows=[]
for row in original:
    pool=[r for r in natural if r['split']==row['split']]
    seed=int(hashlib.sha256(row['sample_id'].encode()).hexdigest()[:8],16)
    contexts=[None,'You are a helpful assistant.','你是一个乐于助人的助手。',
              pool[seed%len(pool)]['messages'][0]['content'],pool[(seed+137)%len(pool)]['messages'][0]['content']]
    for i,context in enumerate(contexts):
        messages=row['messages'] if context is None else [{'role':'system','content':context}]+row['messages']
        rows.append({**row,'sample_id':row['sample_id']+f':context-{i}','messages':messages})
out=root/'harmful_context_data'; out.mkdir(exist_ok=True)
(out/'all_samples.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
(out/'manifest.json').write_text(json.dumps(dict(base=str(root/'harmful_data'),augmentation='Original, generic EN/ZH, two deterministic same-split natural system contexts; both labels identically augmented',samples=len(rows)),indent=2))
(root/'harmful_natural_ids.json').write_text(json.dumps([r['sample_id'] for r in natural]))
print(len(rows),'contextual samples;',len(natural),'cached natural negatives')
