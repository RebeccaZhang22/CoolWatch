import asyncio,json
from pathlib import Path
import sys
REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))
from backend.app import customer_agent_service as agent
from backend.customer_agent_schemas import CustomerAgentRunRequest

async def main():
    root=REPO_ROOT
    payload=json.loads((root/'evaluation/results/rag-miss-20260918/current/checkpoints.json').read_text())[0]['request']
    request=CustomerAgentRunRequest(message=payload['messages'][-1]['content'],attack_id='rag_extraction',defenses=['activation_probe'],model_params=dict(model='qwen3-8b',vllm_port=8104,temperature=1,top_p=.8,max_tokens=8192,enable_reasoning=False))
    result=await agent.run(request)
    data=result.model_dump(mode='json')
    signal=next(s for s in data['defense_signals'] if s['defense_id']=='activation_probe')
    assert signal['blocked'] and signal['metadata']['per_risk']['prompt_leakage']['flagged']
    assert data['verdict']=='blocked' and not data['tool_trace']
    (REPO_ROOT / 'evaluation/results/leakage-toolctx-deploy-20260918' / 'agent-smoke.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'verdict':data['verdict'],'leakage':signal['metadata']['per_risk']['prompt_leakage'],'bank_version':signal['metadata']['bank_version']},ensure_ascii=False))

asyncio.run(main())
