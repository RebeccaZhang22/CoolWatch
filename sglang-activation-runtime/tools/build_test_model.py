"""Build deterministic small official-architecture models without network access."""
import argparse
from pathlib import Path
import torch
from tokenizers import Tokenizer
from tokenizers.models import WordLevel
from tokenizers.pre_tokenizers import Whitespace
from transformers import PreTrainedTokenizerFast, Qwen3Config, Qwen3ForCausalLM

parser=argparse.ArgumentParser()
parser.add_argument("--architecture",choices=["qwen3","qwen3.5","qwen3.5-moe","llama"],default="qwen3")
args=parser.parse_args()
root=Path(__file__).resolve().parents[1]/"artifacts"/f"tiny-{args.architecture}"
root.mkdir(parents=True,exist_ok=True)
torch.manual_seed(42)
common=dict(vocab_size=256,hidden_size=128,intermediate_size=256,num_hidden_layers=4,
            num_attention_heads=2,num_key_value_heads=2,head_dim=64,
            max_position_embeddings=2048,bos_token_id=2,eos_token_id=1,pad_token_id=0,
            tie_word_embeddings=False)
if args.architecture.startswith("qwen3.5"):
    from transformers import Qwen3_5TextConfig, Qwen3_5ForCausalLM
    if args.architecture.endswith("moe"):
        from transformers import Qwen3_5MoeTextConfig as Qwen3_5TextConfig
        from transformers import Qwen3_5MoeForCausalLM as Qwen3_5ForCausalLM
        common.update(num_experts=4,num_experts_per_tok=2,moe_intermediate_size=128,
                      shared_expert_intermediate_size=128)
    config=Qwen3_5TextConfig(**common,full_attention_interval=4,linear_num_key_heads=2,linear_num_value_heads=2,
        linear_key_head_dim=64,linear_value_head_dim=64,
        layer_types=["linear_attention","linear_attention","linear_attention","full_attention"],
        rope_parameters={"rope_type":"default","rope_theta":10000000,
                         "partial_rotary_factor":0.25,"mrope_section":[2,3,3],"mrope_interleaved":True})
    model=Qwen3_5ForCausalLM(config)
elif args.architecture=="llama":
    from transformers import LlamaConfig, LlamaForCausalLM
    model=LlamaForCausalLM(LlamaConfig(**common))
else:
    model=Qwen3ForCausalLM(Qwen3Config(**common))
model.to(torch.bfloat16).save_pretrained(root)
tok=Tokenizer(WordLevel({f"t{i}":i for i in range(256)},unk_token="t0"))
tok.pre_tokenizer=Whitespace()
tokenizer=PreTrainedTokenizerFast(tokenizer_object=tok,unk_token="t0",eos_token="t1",bos_token="t2",pad_token="t0")
tokenizer.chat_template="{% for message in messages %}{{ message['content'] }} {% endfor %}"
tokenizer.save_pretrained(root)
print(root)
