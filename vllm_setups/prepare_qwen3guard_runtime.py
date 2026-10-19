"""Create an isolated SGLang copy with mixed logprob request handling fixed."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
source = Path(importlib.util.find_spec("sglang").origin).parent
destination = root / ".runtime/qwen3guard-heldout/python/sglang"
if not destination.exists():
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
path = destination / "srt/managers/scheduler_components/batch_result_processor.py"
original = path.read_text()
patched = original
replacements = {}
for variable, field in (("v", "next_token_token_ids_logprobs_val"),
                        ("v", "next_token_top_logprobs_val"),
                        ("x", "next_token_top_logprobs_idx")):
    before = f"{variable}.tolist() for {variable} in logits_output.{field}"
    after = f"{variable}.tolist() if torch.is_tensor({variable}) else {variable} for {variable} in logits_output.{field}"
    count = patched.count(before)
    if count:
        assert count == 2, (field, count)
        patched = patched.replace(before, after)
    else:
        assert patched.count(after) == 2, f"Unexpected SGLang source for {field}"
    replacements[field] = count
path.write_text(patched)
record = {"source_package": str(source), "isolated_package": str(destination),
          "reason": "SGLang 0.5.19 mixed logprob/non-logprob batches can contain Python list placeholders; only tensors need tolist().",
          "file": str(path), "patched_sha256": hashlib.sha256(patched.encode()).hexdigest(),
          "replacements": replacements}
(destination.parent.parent / "runtime_patch.json").write_text(json.dumps(record, indent=2) + "\n")
print(json.dumps(record, indent=2))
