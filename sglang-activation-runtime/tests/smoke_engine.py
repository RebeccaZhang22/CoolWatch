import os
os.environ['SGLANG_ACTIVATION_CAPTURE'] = '1'
from pathlib import Path
import sglang

if __name__ == '__main__':
    engine = sglang.Engine(model_path=str(Path(__file__).resolve().parents[1] / 'artifacts/tiny-qwen3'),
        dtype='bfloat16', mem_fraction_static=0.025, max_total_tokens=2048,
        max_running_requests=16, context_length=512, chunked_prefill_size=16,
        cuda_graph_bs_decode=[1,2,4,8,16], disable_prefill_cuda_graph=True,
        attention_backend='triton', log_level='info')
    try:
        out=engine.generate(input_ids=[3,4,5,6],sampling_params={'max_new_tokens':4,'temperature':0,'ignore_eos':True},
            activation_capture={'targets':[{'layer':1,'site':'block_output'}],
                                'tokens':{'prompt':'all','generated':'processed'},'encoding':'float_list'})
        print('SMOKE',out['text'],[(c['positions'],c['shape']) for c in out['meta_info']['activations']['chunks']], flush=True)
    finally:
        engine.shutdown()
