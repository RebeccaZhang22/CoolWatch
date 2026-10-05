"""Authorized deployment, preserving original runtime parameters and rollback files."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import tempfile
import time
from urllib.request import Request, urlopen

root=Path('/share/workspace/zyt/agent-guard-open')
out=root/'diagnostics/leakage-toolctx-deploy-20260918'
active=root/'probe/qwen3-8b/prompt_leakage'
candidate=active/'tool_context_v1'
old_pid=1948116
expected_new='141414e1543807a26a343165903408046c438227a7b6e1503470c560964520c0'
expected_old='8a4af4740b39a40694196aa22f3cdf514931da74f156ae578371c4c441eefbc8'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def get(route,payload=None):
    req=Request('http://127.0.0.1:8302/'+route,data=json.dumps(payload).encode() if payload is not None else None,headers={'Content-Type':'application/json'})
    with urlopen(req,timeout=65) as res:return json.load(res)
def save(name,value):(out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def replace(source,destination):
    temp=destination.with_name(destination.name+'.deploying')
    shutil.copy2(source,temp);os.replace(temp,destination)

assert sha(candidate/'best_probe.pt')==expected_new
assert sha(active/'best_probe.pt')==expected_old
command=Path(f'/proc/{old_pid}/cmdline').read_text().strip('\0').split('\0')
assert 'backend.qwen3_probe_bank_server' in command and command[command.index('--port')+1]=='8302'
env=dict(s.split('=',1) for s in Path(f'/proc/{old_pid}/environ').read_text().split('\0') if '=' in s)
assert os.getpgid(old_pid)==old_pid and env.get('CUDA_VISIBLE_DEVICES')=='0'
old_bank=get('bank');assert get('batch-stats')['active']==0
save('before-bank.json',old_bank)
backup=active/'rollback_pre_tool_context_20260918'
backup.mkdir(exist_ok=False)
for name in ['best_probe.pt','training_report.json']:shutil.copy2(active/name,backup/name)


def start():
    new_command=command.copy()
    instance=Path(tempfile.mkdtemp(prefix='run-deploy-',dir=root/'.runtime/probe-bank-8b'))
    new_command[new_command.index('--spool')+1]=str(instance/'spool')
    log=(instance/'server.log').open('w')
    proc=subprocess.Popen(new_command,env=env,cwd=root,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    log.close()
    (root/'.runtime/pids/probe-bank-qwen3-8b.pid').write_text(str(proc.pid)+'\n')
    print('Started bank',proc.pid,'log',instance/'server.log',flush=True)
    return proc,instance


def wait_ready(proc):
    deadline=time.monotonic()+240
    while time.monotonic()<deadline:
        if proc.poll() is not None:raise RuntimeError(f'Bank process exited: {proc.returncode}')
        try:
            if get('health/ready')['ready']:return get('bank')
        except Exception:pass
        time.sleep(1)
    raise TimeoutError('Bank readiness timeout')

replace(candidate/'best_probe.pt',active/'best_probe.pt')
replace(candidate/'report.json',active/'training_report.json')
print('Old checkpoint backed up; stopping idle original bank',flush=True)
os.killpg(old_pid,signal.SIGTERM)
for _ in range(40):
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        try:s.bind(('127.0.0.1',8302));break
        except OSError:time.sleep(1)
else:raise RuntimeError('Old listener did not close')
time.sleep(3)
proc=None
try:
    proc,instance=start();bank=wait_ready(proc)
    entries={e['risk']:e for e in bank['entries']}
    assert entries['prompt_leakage']['checkpoint_id']=='sha256:'+expected_new
    for risk in ['harmful','ipi']:
        assert entries[risk]==next(e for e in old_bank['entries'] if e['risk']==risk)
    audit=[json.loads(x) for x in (root/'data/activation_probe/tool_context_v1/external_audits/reported_rag_tool_context.jsonl').read_text().splitlines()]
    results=[]
    for row in audit:
        payload={k:row.get(k) for k in ['messages','tools']}
        response=get('detect',payload)
        assert response['per_risk']['prompt_leakage']['flagged']==bool(row['label'])
        results.append(dict(id=row['sample_id'],label=row['label'],response=response))
    save('after-bank.json',bank);save('smoke.json',results)
    save('deployment.json',dict(status='deployed',pid=proc.pid,server_log=str(instance/'server.log'),
         old_sha256=expected_old,new_sha256=expected_new,rollback_directory=str(backup),bank_version=bank['bank_version']))
    print('DEPLOYED AND FIVE REGRESSION CASES PASSED',flush=True)
except Exception as error:
    if proc is not None:
        try:os.killpg(proc.pid,signal.SIGTERM);proc.wait(timeout=25)
        except ProcessLookupError:pass
        except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
    replace(backup/'best_probe.pt',active/'best_probe.pt')
    replace(backup/'training_report.json',active/'training_report.json')
    restored,instance=start();wait_ready(restored)
    save('deployment.json',dict(status='rolled_back',error=str(error),pid=restored.pid))
    raise
