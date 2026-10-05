"""Replay exact saved detector inputs; does not regenerate Agent/tool outputs."""
import argparse
import json
from pathlib import Path
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--url', default='http://127.0.0.1:8302')
    args = parser.parse_args()
    for path in sorted(args.directory.glob('checkpoint-*.request.json')):
        request = urllib.request.Request(args.url.rstrip('/') + '/detect', data=path.read_bytes(), headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=90) as response:
            result = json.load(response)
        old = json.loads(path.with_name(path.name.replace('.request.', '.response.')).read_text())['payload']
        print(json.dumps({'checkpoint': path.name, 'original_ipi': old['per_risk']['ipi'], 'replayed_ipi': result['per_risk']['ipi'], 'same_bank': old['bank_version'] == result['bank_version'], 'input_tokens': result['input_tokens'], 'detector_model': result['detector_model']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
