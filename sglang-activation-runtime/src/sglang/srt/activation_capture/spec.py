"""Wire validation and token selection. No CUDA imports in the HTTP process."""
import os


def enabled():
    return os.environ.get("SGLANG_ACTIVATION_CAPTURE", "0") == "1"


def max_targets():
    return int(os.environ.get("SGLANG_ACTIVATION_MAX_TARGETS", "8"))


def validate(spec, *, num_layers, hidden_size, prompt_len, max_new_tokens):
    if spec is None:
        return None
    if not enabled():
        raise ValueError("activation_capture requires SGLANG_ACTIVATION_CAPTURE=1")
    if not isinstance(spec, dict) or set(spec) - {"targets", "tokens", "encoding"}:
        raise ValueError("activation_capture accepts targets, tokens, encoding")
    targets = spec.get("targets")
    if not isinstance(targets, list) or not 1 <= len(targets) <= max_targets():
        raise ValueError(f"targets must contain 1..{max_targets()} entries")
    normalized = []
    for target in targets:
        if not isinstance(target, dict) or set(target) != {"layer", "site"}:
            raise ValueError("each target needs exactly layer and site")
        layer, site = target["layer"], target["site"]
        if type(layer) is not int or not 0 <= layer < num_layers:
            raise ValueError(f"layer must be a zero-based integer in [0, {num_layers})")
        if site not in ("block_output", "ffn_output"):
            raise ValueError("site must be block_output or ffn_output")
        if target in normalized:
            raise ValueError("duplicate activation target")
        normalized.append(dict(target))
    tokens = spec.get("tokens", {"prompt": "last", "generated": "none"})
    if not isinstance(tokens, dict) or set(tokens) - {"prompt", "generated"}:
        raise ValueError("tokens accepts prompt and generated")
    prompt = tokens.get("prompt", "last")
    if isinstance(prompt, list):
        if any(type(p) is not int or not 0 <= p < prompt_len for p in prompt):
            raise ValueError("prompt indices must be within the tokenized prompt")
        prompt = sorted(set(prompt))
        count = len(prompt)
    elif prompt in ("all", "last", "none"):
        count = prompt_len if prompt == "all" else int(prompt == "last")
    else:
        raise ValueError("prompt must be all, last, none, or a list of token positions")
    generated = tokens.get("generated", "none")
    if generated not in ("none", "processed"):
        raise ValueError("generated must be none or processed (input-token alignment)")
    encoding = spec.get("encoding", "base64")
    if encoding not in ("base64", "float_list"):
        raise ValueError("encoding must be base64 or float_list")
    count += max_new_tokens if generated == "processed" else 0
    limit = int(os.environ.get("SGLANG_ACTIVATION_MAX_BYTES", str(128 * 1024**2)))
    # Conservatively allow FP32 even when the model uses two-byte activations.
    if count * len(targets) * hidden_size * 4 > limit:
        raise ValueError(f"activation request exceeds {limit} raw bytes; select fewer tokens")
    return {"targets": normalized, "tokens": {"prompt": prompt, "generated": generated},
            "encoding": encoding}


def selected_positions(spec, start, length, prompt_len):
    """Positions belong to tokens being evaluated, never next-token predictions."""
    prompt = spec["tokens"]["prompt"]
    explicit = set(prompt) if isinstance(prompt, list) else None
    return [p for p in range(start, start + length)
            if (p >= prompt_len and spec["tokens"]["generated"] == "processed")
            or (p < prompt_len and (prompt == "all" or
                (prompt == "last" and p == prompt_len - 1) or
                (explicit is not None and p in explicit)))]


def prefix_limit(req, limit):
    spec = getattr(req, "activation_capture", None)
    if spec is None:
        return limit
    # Retractions can reuse already exported positions. Chunked prefill retains
    # its own KV without reentering this initial prefix matching path.
    seen = getattr(req, "_activation_seen", set())
    wanted = selected_positions(spec, 0, len(req.origin_input_ids), len(req.origin_input_ids))
    missing = [p for p in wanted if (0, p) not in seen]
    if missing:
        return min(limit, missing[0]) if limit is not None else missing[0]
    return limit
