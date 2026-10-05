"""Replay fixed detector inputs; no business model/tool execution or config changes."""
import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8302')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    tools = json.loads((root / 'tools.json').read_text())
    cases = json.loads((root / 'ablations.json').read_text())
    for case in cases:
        payload = {
            'messages': case['messages'],
            'tools': None if case['case'] == 'full_context_without_tool_schema' else tools,
        }
        request = Request(
            args.base_url.rstrip('/') + '/detect',
            data=json.dumps(payload, ensure_ascii=False).encode(),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        with urlopen(request, timeout=65) as response:
            result = json.load(response)
        print(json.dumps({
            'case': case['case'],
            'recorded_ipi': case['per_risk']['ipi'],
            'current_ipi': result['per_risk']['ipi'],
            'bank_version': result['bank_version'],
        }, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
