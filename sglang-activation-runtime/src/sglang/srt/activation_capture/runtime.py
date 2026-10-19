"""Sparse activation copies with graph-stable decode storage.

Only TP rank zero exports replicated post-collective activations. The other
ranks still execute all model collectives. No Python hooks, request-global
layer selection, disk spool, or changes to EAGLE hidden states are used.
"""
from dataclasses import dataclass
import base64

import torch
import triton

from .kernels import capture_decode, capture_extend
from .spec import enabled, max_targets, selected_positions

_recorder = None


def initialize(runner):
    global _recorder
    if not enabled() or runner.is_draft_worker:
        return
    if _recorder is not None:
        return
    args = runner.server_args
    unsupported = {
        "non-CUDA devices": not str(runner.device).startswith("cuda"),
        "pipeline parallel": getattr(args, "pp_size", 1) != 1,
        "DP attention": getattr(args, "enable_dp_attention", False),
        "sequence parallel": getattr(args, "enable_attn_tp_input_scattered", False)
            or getattr(args, "enable_layernorm_sp", False),
        "context parallel": getattr(args, "attn_cp_size", 1) != 1
            or getattr(args, "dcp_size", 1) != 1,
        "RL FP32 residual overrides": getattr(args, "rl_on_policy_target", None) is not None,
        "two batch overlap": getattr(args, "enable_two_batch_overlap", False),
        "speculative decoding": not runner.spec_algorithm.is_none(),
        "prefill/decode disaggregation": getattr(args, "disaggregation_mode", "null") != "null",
    }
    bad = [name for name, active in unsupported.items() if active]
    if bad:
        raise ValueError("activation capture does not yet support " + ", ".join(bad))
    config = runner.model_config.hf_config
    arch = config.architectures[0]
    if "Moe" in arch or "moe" in getattr(config, "model_type", ""):
        raise ValueError("MoE activation export is not enabled: its numerical reference validation is still unresolved")
    if arch not in ("Qwen3ForCausalLM", "Qwen2ForCausalLM", "LlamaForCausalLM",
                    "Qwen3_5ForCausalLM", "Qwen3_5ForConditionalGeneration"):
        raise ValueError(f"activation capture has no verified adapter for {arch}")
    config = getattr(config, "text_config", config)
    # Metadata-only on non-output ranks. No duplicate D2H or response buffers.
    if runner.ps.tp_rank != 0:
        return
    capacity = max(runner.max_running_requests,
                   max(getattr(args, "cuda_graph_bs_decode", None) or [1]),
                   getattr(args, "cuda_graph_max_bs_decode", None) or 1)
    _recorder = Recorder(config.num_hidden_layers, config.hidden_size,
                         capacity, runner.model_config.dtype, runner.device)


def begin(forward_batch):
    if _recorder is not None:
        _recorder.begin(forward_batch)


def finish(output, can_run_graph=False):
    output.activation_device_output = None
    if _recorder is not None:
        captured = _recorder.finish()
        if captured is not None:
            captured.execution = "cuda_graph" if can_run_graph else "eager"
            output.activation_device_output = captured


def tap(layer, hidden, residual, forward_batch):
    if _recorder is not None:
        _recorder.tap(layer, hidden, residual, forward_batch)


@dataclass
class CompositeDevice:
    first: object
    second: object

    def copy_to_host(self, copy):
        return CompositeHost(self.first.copy_to_host(copy), self.second.copy_to_host(copy))


@dataclass
class CompositeHost:
    first: object
    second: object

    def consume(self, batch, commits):
        self.first.consume(batch, commits)
        self.second.consume(batch, commits)


@dataclass
class Segment:
    rid: str
    target_index: int
    target: dict
    positions: list
    start: int
    end: int


class Recorder:
    def __init__(self, layers, width, capacity, dtype, device):
        self.layers, self.width, self.capacity = layers, width, capacity
        self.dtype, self.device = dtype, device
        self.table = torch.full((layers, 2, capacity), -1, dtype=torch.int32, device=device)
        self.decode_out = torch.empty((capacity * max_targets(), width), dtype=dtype, device=device)
        self.segments = []
        self.eager = {}
        self.output = None
        self.rows = 0
        self.last_decode_active = False

    def begin(self, fb):
        self.segments, self.eager, self.rows = [], {}, 0
        self.output = None
        plan = getattr(fb, "activation_plan", None) or []
        is_decode = fb.forward_mode.is_decode()
        active = any(entry["positions"] for entry in plan)
        if is_decode:
            if fb.batch_size > self.capacity:
                raise RuntimeError("activation decode capacity exceeded")
            # Avoid even a table H2D on batches with no captures following another
            # inactive decode. Reset once after an active batch to prevent stale rows.
            if not active and not self.last_decode_active:
                return
            table = torch.full(self.table.shape, -1, dtype=torch.int32, pin_memory=True)
            for entry in plan:
                for index, target in enumerate(entry["spec"]["targets"]):
                    if not entry["positions"]:
                        continue
                    site = int(target["site"] == "block_output")
                    table[target["layer"], site, entry["row_start"]] = self.rows
                    self.segments.append(Segment(entry["rid"], index, target,
                                                 entry["positions"], self.rows, self.rows + 1))
                    self.rows += 1
            self.table.copy_(table, non_blocking=True)
            self.output = self.decode_out
            self.last_decode_active = active
            return
        if not active:
            return
        by_layer = {}
        for entry in plan:
            positions = entry["positions"]
            if not positions:
                continue
            for index, target in enumerate(entry["spec"]["targets"]):
                by_layer.setdefault(target["layer"], []).append((entry, index, target))
        self.rows = sum(len(e["positions"]) for entries in by_layer.values() for e, _, _ in entries)
        self.output = torch.empty((self.rows, self.width), dtype=self.dtype, device=self.device)
        offset = 0
        for layer, entries in by_layer.items():
            rows, sites = [], []
            start = offset
            for entry, index, target in entries:
                positions = entry["positions"]
                rows.extend(entry["row_start"] + p - entry["position_start"] for p in positions)
                sites.extend([int(target["site"] == "block_output")] * len(positions))
                self.segments.append(Segment(entry["rid"], index, target, positions,
                                             offset, offset + len(positions)))
                offset += len(positions)
            indices = torch.tensor([rows, sites], dtype=torch.int32, pin_memory=True).to(
                self.device, non_blocking=True)
            self.eager[layer] = (indices, self.output[start:offset])

    def tap(self, layer, hidden, residual, fb):
        if hidden.ndim != 2 or hidden.shape[1] != self.width or hidden.stride(1) != 1:
            raise RuntimeError("activation adapter expected complete contiguous feature rows")
        if residual is not None and (residual.shape != hidden.shape or residual.stride(1) != 1):
            raise RuntimeError("activation adapter received a sharded or incompatible residual")
        # This branch is static during decode capture. Selection is NOT a Python
        # branch on live requests: both row destinations are read from GPU table.
        if fb.forward_mode.is_decode():
            if hidden.shape[0] > self.capacity:
                raise RuntimeError("graph token capacity exceeds activation capacity")
            capture_decode[(hidden.shape[0],)](
                hidden, residual if residual is not None else hidden, self.table,
                self.decode_out, layer, self.capacity, self.width, hidden.stride(0),
                residual.stride(0) if residual is not None else 0,
                residual is not None, triton.next_power_of_2(self.width))
        elif layer in self.eager:
            indices, output = self.eager[layer]
            capture_extend[(indices.shape[1],)](
                hidden, residual if residual is not None else hidden,
                indices[0], indices[1], output, self.width, hidden.stride(0),
                residual.stride(0) if residual is not None else 0,
                residual is not None, triton.next_power_of_2(self.width))

    def finish(self):
        if not self.rows:
            return None
        # The scheduler may replay the next graph before the D2H stream consumes
        # this result. Own a snapshot now, on the forward stream, before reuse.
        tensor = self.output[:self.rows]
        if tensor.data_ptr() == self.decode_out.data_ptr():
            tensor = tensor.clone()
        result = DeviceOutput(tensor, self.segments)
        self.output, self.eager, self.segments, self.rows = None, {}, [], 0
        return result


@dataclass
class DeviceOutput:
    tensor: torch.Tensor
    segments: list
    execution: str = "eager"

    def copy_to_host(self, copy):
        return HostOutput(copy(self.tensor), self.segments, self.execution)


@dataclass
class HostOutput:
    tensor: torch.Tensor
    segments: list
    execution: str = "eager"

    def consume(self, batch, commits):
        reqs = {r.rid: r for r in batch.reqs}
        for seg in self.segments:
            req = reqs.get(seg.rid)
            if req is None or req.is_retracted:
                continue
            seen = getattr(req, "_activation_seen", None)
            if seen is None:
                seen = req._activation_seen = set()
                req._activation_chunks = []
            # Drop repeated rows after retraction and speculative overlap's
            # extra forward after a request has already finished.
            token_ids = list(req.origin_input_ids) + list(req.output_ids)
            end = len(req.origin_input_ids) + (
                req.finished_len if req.finished_len is not None else len(req.output_ids))
            chosen = [i for i, p in enumerate(seg.positions)
                      if p < end and (seg.target_index, p) not in seen]
            if not chosen:
                continue
            positions = [seg.positions[i] for i in chosen]
            values = self.tensor[seg.start:seg.end]
            if len(chosen) != len(seg.positions):
                values = values[chosen]
            # One bulk byte copy; never a Python float object per activation.
            data = values.contiguous().view(torch.uint8).numpy().tobytes()
            req._activation_chunks.append({**seg.target,
                "positions": positions, "token_ids": [token_ids[p] for p in positions],
                "shape": [len(positions), self.tensor.shape[1]],
                "dtype": str(self.tensor.dtype).removeprefix("torch."),
                "execution": self.execution,
                "data": data})
            seen.update((seg.target_index, p) for p in positions)


def make_plan(batch):
    plan, row = [], 0
    decode = batch.forward_mode.is_decode()
    if not decode and not batch.forward_mode.is_extend():
        return plan
    for i, req in enumerate(batch.reqs):
        length = 1 if decode else int(batch.extend_lens[i])
        start = int(batch.seq_lens_cpu[i]) - 1 if decode else int(batch.prefix_lens[i])
        spec = getattr(req, "activation_capture", None)
        if spec is not None:
            plan.append({"rid": req.rid, "spec": spec, "row_start": row,
                         "position_start": start,
                         "positions": selected_positions(spec, start, length, len(req.origin_input_ids))})
        row += length
    return plan


def drain(req):
    chunks = getattr(req, "_activation_chunks", [])
    req._activation_chunks = []
    return chunks if getattr(req, "activation_capture", None) is not None else None


def response(chunks, state, finished=True):
    spec = state.obj.activation_capture
    if not getattr(state.obj, "stream", False):
        previous = getattr(state, "_activation_chunks", [])
        previous.extend(chunks)
        state._activation_chunks = previous
        chunks = previous
        if not finished:
            return None
    encoded = []
    for chunk in chunks:
        item = dict(chunk)
        if spec["encoding"] == "base64":
            item["data"] = base64.b64encode(item["data"]).decode("ascii")
        else:
            dtype = getattr(torch, item["dtype"])
            item["data"] = torch.frombuffer(bytearray(item["data"]), dtype=dtype).reshape(item["shape"]).tolist()
        encoded.append(item)
    return {"alignment": "input_token", "byte_order": "little", "encoding": spec["encoding"],
            "chunks": encoded, "stream_delta": bool(getattr(state.obj, "stream", False))}
