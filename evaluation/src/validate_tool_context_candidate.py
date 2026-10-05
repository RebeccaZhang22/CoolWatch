"""Exercise a candidate in an isolated SGLang bank; never replace the live bank."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sys
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[2] / "probe/src")]
import random
import signal
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen


def get(url,payload=None):
    req=Request(url,data=json.dumps(payload).encode() if payload is not None else None,
                headers={'Content-Type':'application/json'})
    with urlopen(req,timeout=65) as response:
        return json.load(response)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--run',type=Path,required=True)
    ap.add_argument('--source-root',type=Path,default=Path('/ssd/workspace/djs/zhuanli'))
    ap.add_argument('--old-url',default='http://127.0.0.1:8302')
    ap.add_argument('--output',type=Path)
    args=ap.parse_args()
    args.run=args.run.resolve()
    output=args.output or Path(__file__).resolve().parents[2]/'evaluation/results'/args.run.name
    output.mkdir(parents=True,exist_ok=True)
    with socket.socket() as s:
        s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    instance=Path(tempfile.mkdtemp(prefix='candidate-server-',dir=args.run))
    command=[sys.executable,'-m','backend.qwen3_probe_bank_server',
        '--source-root',str(args.source_root),'--model-path',str(Path('.runtime/models/Qwen3-8B').resolve()),
        '--spool',str(instance/'spool'),'--port',str(port),'--mem-fraction','0.50',
        '--content-safety-checkpoint',str(Path('probe/qwen3-8b/content_safety/best_probe.pt').resolve()),
        '--ipi-checkpoint',str(Path('probe/qwen3-8b/indirect_prompt_injection/best_layer_22.pt').resolve()),
        '--leakage-checkpoint',str(args.run/'probe/best_probe.pt'),
        '--max-batch','8','--batch-tokens','16384','--max-inflight','32']
    url=f'http://127.0.0.1:{port}'
    log=(instance/'server.log').open('w')
    proc=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    try:
        deadline=time.monotonic()+240
        while time.monotonic()<deadline:
            if proc.poll() is not None:
                raise RuntimeError(f'Candidate server exited; see {instance}/server.log')
            try:
                if get(url+'/health/ready')['ready']:
                    break
            except Exception:
                time.sleep(1)
        else:
            raise TimeoutError('Candidate readiness timeout')
        print('Isolated candidate server ready',flush=True)
        data=[json.loads(x) for x in (args.run/'additions_data/all_samples.jsonl').read_text().splitlines()]
        audit=[json.loads(x) for x in (args.run/'additions_data/external_audits/reported_rag_tool_context.jsonl').read_text().splitlines()]
        rng=random.Random(20260918)
        cases=list(audit)
        for stage in ['pre_tools','post_tool','post_tool_with_schema']:
            for label in [0,1]:
                pool=[r for r in data if r['split']=='test' and r.get('stage')==stage and r['label']==label]
                cases.extend(rng.sample(pool,min(4,len(pool))))
        banks={'old':get(args.old_url+'/bank'),'new':get(url+'/bank')}
        def run_case(row):
            payload={k:row.get(k) for k in ['messages','tools']}
            return dict(sample_id=row['sample_id'],label=row['label'],stage=row.get('stage','reported'),
                        request=payload,old=get(args.old_url+'/detect',payload),new=get(url+'/detect',payload))
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(run_case,cases))
        report={'banks':banks,'server_log':str(instance/'server.log'),'cases':results}
        (output/'http-comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        for r in results[:len(audit)]:
            print(json.dumps({k:r[k] for k in ['sample_id','label']} | {
                name:r[name]['per_risk']['prompt_leakage'] for name in ['old','new']},ensure_ascii=False),flush=True)
        for name in ['old','new']:
            actual=results[len(audit):]
            print(name,'held-out HTTP',json.dumps({
                'tp':sum(r['label']==1 and r[name]['per_risk']['prompt_leakage']['flagged'] for r in actual),
                'fn':sum(r['label']==1 and not r[name]['per_risk']['prompt_leakage']['flagged'] for r in actual),
                'fp':sum(r['label']==0 and r[name]['per_risk']['prompt_leakage']['flagged'] for r in actual),
                'tn':sum(r['label']==0 and not r[name]['per_risk']['prompt_leakage']['flagged'] for r in actual)}),flush=True)
        assert get(args.old_url+'/bank')['bank_version']==banks['old']['bank_version']
    finally:
        # This process group was created above solely for this candidate bank.
        try:
            os.killpg(proc.pid,signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid,signal.SIGKILL);proc.wait()
        log.close()


if __name__=='__main__':
    main()
