"""Audit the live probe bank against reference labels; never execute business tools.

python evaluation/src/run_judge.py --suite in-the-wild
python evaluation/src/run_judge.py --suite benchmark --risk ipi --limit-per-dataset 10
This is a classification judge, not an LLM judge of generated answers/leak success.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[2]
RISKS=('harmful','prompt_leakage','ipi')


def read_jsonl(path):
    with path.open() as handle:
        for line in handle:
            if line.strip():yield json.loads(line)


def normalize(row,risk):
    payload=row.get('replay_request') or row.get('request') or row
    messages=payload.get('messages')
    if messages is None and isinstance(row.get('system_prompt'),str) and isinstance(row.get('query'),str):
        messages=[{'role':'system','content':row['system_prompt']},{'role':'user','content':row['query']}]
    if not isinstance(messages,list) or not messages or any(not isinstance(m,dict) or not m.get('role') for m in messages):
        raise ValueError('A complete messages conversation is required; plain attack strings are not silently promoted to user messages')
    normalized=[]
    for message in messages:
        message=dict(message)
        content=message.get('content')
        if isinstance(content,list):
            if any(not isinstance(part,dict) or part.get('type')!='text' or not isinstance(part.get('text'),str) for part in content):
                raise ValueError('Only text content blocks are supported; non-text content cannot be silently discarded')
            message['content']=''.join(part['text'] for part in content)
        elif content is None:
            message['content']=''
        elif not isinstance(content,str):
            raise ValueError('Unsupported message content')
        normalized.append(message)
    label=row.get('label')
    # This named frozen corpus contains injected decision points only.
    if label is None and row.get('schema') and 'injection_message_indices' in row and row.get('decision_point_id'):
        label=1
    if label is not None and (type(label) is not int or label not in (0,1)):
        raise ValueError('label must be 0, 1 or null')
    if row.get('risk',risk)!=risk:raise ValueError('Case risk does not match selected dataset risk')
    identifier=row.get('sample_id') or row.get('decision_point_id')
    if not identifier:raise ValueError('Missing stable case identifier')
    return identifier,label,{'messages':normalized,'tools':payload.get('tools')}


def summarize(rows):
    counts=Counter({'tp':0,'tn':0,'fp':0,'fn':0,'unlabeled':0,'errors':0})
    for row in rows:
        if row.get('error'):
            counts['errors']+=1;continue
        if row['label'] is None:
            counts['unlabeled']+=1;continue
        key=('tp' if row['flagged'] else 'fn') if row['label'] else ('fp' if row['flagged'] else 'tn')
        counts[key]+=1
    pos=counts['tp']+counts['fn'];neg=counts['tn']+counts['fp']
    return {**counts,'samples':len(rows),'scored_labeled':pos+neg,
            'recall':counts['tp']/pos if pos else None,'false_positive_rate':counts['fp']/neg if neg else None,
            'accuracy':(counts['tp']+counts['tn'])/(pos+neg) if pos+neg else None}


def get(url,payload=None):
    req=Request(url,data=json.dumps(payload).encode() if payload is not None else None,
                headers={'Content-Type':'application/json'})
    with urlopen(req,timeout=65) as response:return json.load(response)


def validate_result(response,bank,risk):
    if response.get('bank_version')!=bank['bank_version']:raise ValueError('Bank changed during audit')
    if set(response.get('per_risk',{}))!=set(RISKS):raise ValueError('Incomplete detector response')
    for name,r in response['per_risk'].items():
        if type(r.get('flagged')) is not bool:raise ValueError('Invalid verdict')
        for field in ['score','threshold']:
            if not isinstance(r.get(field),(float,int)) or not math.isfinite(r[field]) or not 0<=r[field]<=1:
                raise ValueError('Invalid score or threshold')
        if r['threshold']!=bank['thresholds'][name]['balanced']:raise ValueError('Threshold changed during audit')
    return response['per_risk'][risk]


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--suite',choices=['in-the-wild','benchmark'],default='in-the-wild')
    ap.add_argument('--risk',choices=RISKS)
    ap.add_argument('--dataset',type=Path,help='A specific JSONL; requires --risk')
    ap.add_argument('--base-url',default='http://127.0.0.1:8302')
    ap.add_argument('--output',type=Path,help='New directory under evaluation/results/')
    ap.add_argument('--limit-per-dataset',type=int)
    args=ap.parse_args()
    if args.limit_per_dataset is not None and args.limit_per_dataset<1:ap.error('limit must be positive')
    if args.dataset:
        if not args.risk:ap.error('--dataset requires --risk')
        datasets=[{'risk':args.risk,'path':str(args.dataset.resolve())}]
    elif args.suite=='in-the-wild':
        datasets=[{'risk':r,'path':f'evaluation/dataset/in-the-wild/{r}/queries.jsonl'} for r in RISKS if not args.risk or args.risk==r]
    else:
        datasets=json.loads((ROOT/'evaluation/dataset/benchmark/catalog.json').read_text())['runnable_datasets']
        datasets=[d for d in datasets if not args.risk or d['risk']==args.risk]
    # Validate all selected rows before making requests. No unlabeled/error row
    # may disappear into the denominator of a reported success rate.
    selected=[];seen=set();source_hashes={}
    for dataset in datasets:
        p=Path(dataset['path']);p=p if p.is_absolute() else ROOT/p
        source_hashes[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
        for i,row in enumerate(read_jsonl(p)):
            if args.limit_per_dataset and i>=args.limit_per_dataset:break
            identifier,label,payload=normalize(row,dataset['risk'])
            key=(str(p),identifier)
            if key in seen:raise ValueError('Duplicate sample identifier in dataset')
            seen.add(key);selected.append((dataset['risk'],str(p),identifier,label,payload))
    if not selected:raise ValueError('No cases selected')
    output=args.output or ROOT/'evaluation/results'/datetime.now(timezone.utc).strftime('audit-%Y%m%dT%H%M%S%fZ')
    output=output.resolve()
    if not output.is_relative_to((ROOT/'evaluation/results').resolve()):ap.error('Output must be under evaluation/results/')
    output.mkdir(parents=True,exist_ok=False)
    base=args.base_url.rstrip('/');bank=get(base+'/bank')
    (output/'bank.json').write_text(json.dumps(bank,indent=2)+'\n')
    rows=[]
    with (output/'predictions.jsonl').open('w') as handle:
        for risk,source,identifier,label,payload in selected:
            record={'risk':risk,'dataset':source,'sample_id':identifier,'label':label,
                    'request_sha256':hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()}
            try:
                response=get(base+'/detect',payload);target=validate_result(response,bank,risk)
                record.update(target,response=response)
            except Exception as error:
                record['error']=str(error)
            rows.append(record);handle.write(json.dumps(record,ensure_ascii=False)+'\n');handle.flush()
    metrics={'judge':'probe_decision_vs_reference_label','suite':args.suite,
             'input_normalization':'Text content blocks concatenated verbatim; null content becomes empty string; non-text rejected; no truncation.',
             'sample_limit_per_dataset':args.limit_per_dataset,'partial_run':args.limit_per_dataset is not None,
             'label_policies':{d['path']:d.get('label_policy', 'explicit_dataset_labels' if args.dataset else 'rag_export_is_leakage_v1') for d in datasets},
             'source_sha256':source_hashes,'bank_version':bank['bank_version'],
             'overall':summarize(rows),'per_risk':{r:summarize([x for x in rows if x['risk']==r]) for r in RISKS if any(x['risk']==r for x in rows)}}
    (output/'metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2)+'\n')
    lines=['# Probe classification audit','',f'Bank: `{bank["bank_version"]}`','',
           'Scores measure detector classification, not generated-answer leakage or tool execution success. Null labels are scored but excluded from classification metrics.', '',
           '| Risk | Cases | TP | FN | FP | TN | Unlabeled | Errors |','|---|---:|---:|---:|---:|---:|---:|---:|']
    for risk,m in metrics['per_risk'].items():
        lines.append('| '+risk+' | '+' | '.join(str(m[k]) for k in ['samples','tp','fn','fp','tn','unlabeled','errors'])+' |')
    (output/'README.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({'output':str(output),'metrics':metrics['per_risk']},ensure_ascii=False),flush=True)
    if metrics['overall']['errors']:raise SystemExit(1)


if __name__=='__main__':main()
