"""Compare frozen old/new checkpoints on the same held-out activation features."""
import argparse
import json
from pathlib import Path
import sys
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[2] / "probe/src")]
import numpy as np
import torch
from probe_features import load_shards
from probe_classifiers import score_activations
from train_qwen3_probe import metrics


def score(checkpoint, features):
    layer=checkpoint['selected_layers'][0]
    return score_activations(checkpoint,features[:,layer:layer+1]).numpy()


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--run',type=Path,required=True)
    ap.add_argument('--old-checkpoint',type=Path,required=True)
    ap.add_argument('--output',type=Path)
    args=ap.parse_args();torch.set_num_threads(4)
    output=args.output or Path(__file__).resolve().parents[2]/'evaluation/results'/args.run.name
    output.mkdir(parents=True,exist_ok=True)
    old=torch.load(args.old_checkpoint,map_location='cpu',weights_only=False)
    new=torch.load(args.run/'probe/best_probe.pt',map_location='cpu',weights_only=False)
    checkpoints={'old':old,'new':new}
    result={'checkpoints':{k:dict(layer=c['selected_layers'][0],threshold=c['probability_threshold'],classifier=c['classifier_type']) for k,c in checkpoints.items()},'sets':{}}
    features,rows,_=load_shards(args.run/'combined_features/main')
    ids=[i for i,r in enumerate(rows) if r['split']=='test']
    subset=features[ids];meta=[rows[i] for i in ids]
    scores={name:score(c,subset) for name,c in checkpoints.items()}
    masks={'combined_test':np.ones(len(meta),dtype=bool),
           'legacy_test':np.array([r.get('dataset_origin')!='tool_context_v1' for r in meta]),
           'tool_context_test':np.array([r.get('dataset_origin')=='tool_context_v1' for r in meta])}
    for stage in sorted({r.get('stage') for r in meta if r.get('stage')}):
        masks['tool_test_'+stage]=np.array([r.get('stage')==stage for r in meta])
    for source in sorted({r['source'] for r in meta if r.get('dataset_origin')=='tool_context_v1'}):
        masks[source]=np.array([r['source']==source for r in meta])
    y=np.array([r['label'] for r in meta])
    for name,mask in masks.items():
        result['sets'][name]={key:metrics(y[mask],s[mask],checkpoints[key]['threshold']) for key,s in scores.items()}
    failures=[]
    for i,r in enumerate(meta):
        if r.get('dataset_origin')=='tool_context_v1' and (scores['new'][i]>=new['threshold'])!=bool(r['label']):
            failures.append({**r,'old_logit':float(scores['old'][i]),'new_logit':float(scores['new'][i])})
    (output/'tool_test_errors.json').write_text(json.dumps(failures,ensure_ascii=False,indent=2)+'\n')
    del features,subset
    for directory in sorted((args.run/'combined_features').iterdir()):
        if directory.name=='main' or not directory.is_dir():
            continue
        feats,meta,_=load_shards(directory)
        scores={name:score(c,feats) for name,c in checkpoints.items()}
        result['sets'][directory.name]={name:metrics([r['label'] for r in meta],s,checkpoints[name]['threshold']) for name,s in scores.items()}
        if directory.name=='reported_rag_tool_context':
            result['reported_cases']=[{'id':r['sample_id'],'label':r['label'],**{
                name:{'score':float(torch.sigmoid(torch.tensor(float(s[i]),dtype=torch.float64))),
                      'flagged':bool(s[i]>=checkpoints[name]['threshold'])} for name,s in scores.items()}}
                for i,r in enumerate(meta)]
    (output/'comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':
    main()
