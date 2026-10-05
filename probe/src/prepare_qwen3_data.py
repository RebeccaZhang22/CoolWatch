"""Reuse the audited leakage v3 splits and materialize grouped harmful samples."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run-root', type=Path, required=True)
    ap.add_argument('--source-root', type=Path, default=Path('/ssd/workspace/djs/zhuanli'))
    ap.add_argument('--leakage-data', type=Path, default=Path('/share/workspace/zyt/agent-guard/analysis/protected_asset_theft_v3_qwen35_2b/data/v3'))
    args = ap.parse_args()
    sys.path.insert(0, str(args.source_root / 'framework/safety_probe'))
    from common import build_splits
    args.run_root.mkdir(parents=True, exist_ok=True)
    link = args.run_root / 'leakage_data'
    if link.exists():
        if link.resolve() != args.leakage_data.resolve():
            raise ValueError('Existing leakage dataset differs')
    else:
        link.symlink_to(args.leakage_data.resolve(), target_is_directory=True)
    path = args.source_root / 'data/harmful/samples.jsonl'
    rows = [json.loads(line) for line in path.open()]
    splits = build_splits([r['split_group']['cluster'] for r in rows], [r['labels']['risk_faced'] for r in rows], 11)
    out = args.run_root / 'harmful_data'
    out.mkdir(exist_ok=True)
    samples = [dict(sample_id=r['sample_id'], messages=r['messages'], label=r['labels']['risk_faced'],
                    split=str(s), group_id=r['split_group']['cluster'], category='harmful',
                    source=r['meta']['source'], language='en') for r,s in zip(rows,splits)]
    content = ''.join(json.dumps(r)+'\n' for r in samples)
    target = out / 'all_samples.jsonl'
    if target.exists() and target.read_text() != content:
        raise ValueError('Refusing to change an existing training dataset')
    target.write_text(content)
    (out / 'manifest.json').write_text(json.dumps(dict(source=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        split_seed=11, split_method='upstream build_splits grouped by cluster', counts=dict(Counter(splits)), samples=len(rows)),indent=2))
    # Fail before extraction if a group or identical full conversation crosses splits.
    for dataset in [out, link]:
        seen = {}
        for line in (dataset/'all_samples.jsonl').open():
            row = json.loads(line)
            for value in [('group', row.get('group_id')), ('messages', json.dumps(row['messages'],sort_keys=True))]:
                if value[1] is None:
                    continue
                if value in seen and seen[value] != row['split']:
                    raise ValueError(f'Cross-split overlap in {dataset}: {value[0]}')
                seen[value] = row['split']


if __name__ == '__main__':
    main()
