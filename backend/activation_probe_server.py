"""Probe API backed by request-scoped SGLang activations, without hooks/spool.

The GPU server owns continuous batching. This process only renders prompts,
decodes the enabled last-token vectors, and evaluates the selected CPU classifiers.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
from contextlib import asynccontextmanager
import hashlib
import json
import logging
from pathlib import Path
import sys
import time

import httpx
import torch
from fastapi import FastAPI, HTTPException, Request
from transformers import AutoTokenizer

from backend.qwen3_checkpoint import Qwen3Checkpoint
from backend.probe_risks import DEFAULT_ENABLED_RISKS, parse_enabled_risks, risk_selection
from backend.qwen3_rendering import normalize_tool_calls

IPI_SHA256 = "a1e6ca136a49b769409d4b9679ae704f1f30b7d8550c4988a7a83aa8431f5278"
RUNTIME = "sglang-request-activation-v1"


class ProbeBank:
    def __init__(self, model_path: Path, probe_dir: Path, ipi_threshold: float, enabled_risks=DEFAULT_ENABLED_RISKS):
        self.enabled_risks = parse_enabled_risks(enabled_risks)
        self.model_path = model_path.resolve()
        config = json.loads((model_path / "config.json").read_text())
        if (config.get("model_type"), config.get("hidden_size"), config.get("num_hidden_layers")) != ("qwen3", 4096, 36):
            raise ValueError("Expected Qwen3-8B architecture")
        if not 0 < ipi_threshold < 1:
            raise ValueError("Invalid IPI threshold")
        self.tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
        self.probes = {
            risk: Qwen3Checkpoint(probe_dir / folder / "best_probe.pt", model_path, risk)
            for risk, folder in [("harmful", "content_safety"), ("prompt_leakage", "prompt_leakage")]
            if risk in self.enabled_risks
        }
        self.layers = {risk: probe.layer for risk, probe in self.probes.items()}
        self.thresholds = {risk: probe.threshold for risk, probe in self.probes.items()}
        if 'ipi' in self.enabled_risks:
            checkpoint_path = probe_dir / "indirect_prompt_injection/best_layer_22.pt"
            digest = hashlib.sha256(checkpoint_path.read_bytes()).hexdigest()
            if digest != IPI_SHA256:
                raise ValueError("IPI checkpoint checksum mismatch")
            ck = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
            if (ck["schema"] != "fyh.probe_checkpoint.v2" or ck["selected_layer_index"] != 22
                    or ck["selected_layer_indices"] != [22] or ck["selected_positions"] != [-1]
                    or ck["input_dim"] != 4096 or ck["training_config"]["feature_normalization"] != "standard"):
                raise ValueError("Unsupported IPI extraction contract")
            self.ipi = {k: v.float().reshape(-1) for k, v in ck["model_state_dict"].items()}
            if (any(self.ipi[k].numel() != 4096 for k in ("input_mean", "input_std", "probe.weight"))
                    or self.ipi["probe.bias"].numel() != 1
                    or any(not torch.isfinite(v).all() for v in self.ipi.values())
                    or not (self.ipi["input_std"] > 0).all()):
                raise ValueError("Invalid IPI parameters")
            self.layers['ipi'] = ck['selected_layer_index']
            self.thresholds['ipi'] = ipi_threshold
        self.entries = [dict(id=f"{risk}/qwen3-8b", risk=risk, layer=layer,
                             layer_hf=layer + 1, site="block_output", position="T-1",
                             method=self.probes[risk].classifier_type if risk != "ipi" else "linear_probe",
                             checkpoint_id="sha256:" + (self.probes[risk].sha256 if risk != "ipi" else digest))
                        for risk, layer in self.layers.items()]
        self.capture = dict(targets=[dict(layer=layer, site="block_output") for layer in sorted(set(self.layers.values()))],
                            tokens=dict(prompt="last", generated="none"), encoding="base64")
        identity = dict(entries=self.entries, thresholds=self.thresholds, runtime=RUNTIME, capture=self.capture,
                        numerical_mode="sglang_deterministic_bfloat16")
        self.version = "sha256:" + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()

    def render(self, payload):
        messages, tools = payload.get("messages"), payload.get("tools")
        if (not isinstance(messages, list) or not 1 <= len(messages) <= 128
                or any(not isinstance(m, dict) for m in messages)):
            raise ValueError("messages must contain 1..128 objects")
        if tools is not None and (not isinstance(tools, list) or any(not isinstance(t, dict) for t in tools)):
            raise ValueError("tools must be a list of objects")
        prompt = self.tokenizer.apply_chat_template(normalize_tool_calls(messages), tools=tools,
            tokenize=False, add_generation_prompt=True, enable_thinking=True)
        return self.tokenizer(prompt, add_special_tokens=False)["input_ids"]

    def decode(self, response, ids):
        activation = response["meta_info"]["activations"]
        if (activation["alignment"] != "input_token" or activation["encoding"] != "base64"
                or activation["byte_order"] != "little" or sys.byteorder != "little"):
            raise ValueError("Unexpected activation encoding/alignment")
        hidden = {}
        for chunk in activation["chunks"]:
            layer = chunk["layer"]
            if (layer not in self.layers.values() or layer in hidden or chunk["site"] != "block_output"
                    or chunk["positions"] != [len(ids) - 1] or chunk["token_ids"] != [ids[-1]]
                    or chunk["shape"] != [1, 4096] or chunk["dtype"] != "bfloat16"):
                raise ValueError("Activation does not match the probe extraction contract")
            raw = bytearray(base64.b64decode(chunk["data"], validate=True))
            if len(raw) != 8192:
                raise ValueError("Invalid activation byte count")
            vector = torch.frombuffer(raw, dtype=torch.bfloat16).float()
            if not torch.isfinite(vector).all():
                raise ValueError("Non-finite activation")
            hidden[layer] = vector
        if set(hidden) != set(self.layers.values()):
            raise ValueError("Missing probe activations")
        return hidden

    @torch.inference_mode()
    def score(self, hidden, input_tokens):
        per_risk, per_entry, triggered = {}, {}, []
        for entry in self.entries:
            risk = entry["risk"]
            vector = hidden[entry["layer"]]
            if risk == "ipi":
                state = self.ipi
                logit = ((vector - state["input_mean"]) / state["input_std"]) @ state["probe.weight"] + state["probe.bias"][0]
                score = torch.sigmoid(logit).item()
                flagged = score >= self.thresholds[risk]
            else:
                score, flagged = self.probes[risk].score(vector)
            per_risk[risk] = dict(score=score, threshold=self.thresholds[risk], flagged=flagged)
            per_entry[entry["id"]] = score
            if flagged:
                triggered.append(entry["id"])
        return dict(**risk_selection(self.enabled_risks), overall=bool(triggered), profile="balanced", per_risk=per_risk,
                    per_entry=per_entry, triggered_entries=triggered, detector_model="qwen3-8b",
                    bank_version=self.version, input_tokens=input_tokens, runtime=RUNTIME,
                    extraction=dict(layers=self.layers, site="block_output", position="last_prompt_token",
                                    layer_numbering="zero_based", dtype="bfloat16",
                                    numerical_mode="sglang_deterministic_bfloat16"))


def create_app(bank: ProbeBank, upstream: str, *, max_inflight=128, timeout=60):
    stats = dict(active=0, peak_active=0, completed=0, rejected=0, failed=0)

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(base_url=upstream.rstrip("/"), timeout=timeout,
                limits=httpx.Limits(max_connections=max_inflight, max_keepalive_connections=64)) as client:
            response = await client.get("/server_info")
            response.raise_for_status()
            info = response.json()
            if (Path(info["model_path"]).resolve() != bank.model_path
                    or info["served_model_name"] != "qwen3-8b" or info["dtype"] != "bfloat16"
                    or not info["enable_deterministic_inference"]):
                raise ValueError("Probe server requires the matching Qwen3-8B model in deterministic BF16 mode")
            app.state.client = client
            yield

    app = FastAPI(title="SGLang request activation probe bank", lifespan=lifespan)

    def status():
        return dict(**stats, max_inflight=max_inflight, timeout_seconds=timeout,
                    scheduler="sglang_continuous_batching", runtime=RUNTIME)

    @app.get("/health/ready")
    async def ready():
        try:
            response = await app.state.client.get("/health", timeout=3)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(503, "Activation model unavailable") from exc
        return dict(ready=True, **status())

    @app.get("/batch-stats")
    async def batch_stats():
        return status()

    @app.get("/bank")
    async def info():
        return dict(**risk_selection(bank.enabled_risks), model="qwen3-8b", hidden=4096, n_layers=36, max_len=16384,
                    layer_union=sorted({layer + 1 for layer in bank.layers.values()}),
                    layer_indices=bank.layers, entries=bank.entries,
                    thresholds={risk: {"balanced": value} for risk, value in bank.thresholds.items()},
                    fusion={risk: "single_probe" for risk in bank.layers},
                    calibration={risk: "checkpoint_standardization_then_sigmoid" for risk in bank.layers},
                    protocol="Qwen3-8B enable_thinking=True; full raw block residual T-1 before final RMSNorm",
                    activation_capture=bank.capture, bank_version=bank.version, batching=status(), runtime=RUNTIME)

    @app.get("/v1/models")
    async def models():
        await ready()
        return {"object": "list", "data": [{"id": "qwen3-8b", "object": "model"}]}

    @app.post("/detect")
    async def detect(request: Request):
        if stats["active"] >= max_inflight:
            stats["rejected"] += 1
            raise HTTPException(429, "Probe capacity full; retry with backoff", headers={"Retry-After": "1"})
        stats["active"] += 1
        stats["peak_active"] = max(stats["peak_active"], stats["active"])
        started = time.perf_counter()
        try:
            async with asyncio.timeout(timeout):
                body = bytearray()
                async for chunk in request.stream():
                    if len(body) + len(chunk) > 2 * 1024 * 1024:
                        raise HTTPException(413, "Request body exceeds 2 MiB")
                    body.extend(chunk)
                try:
                    payload = json.loads(body)
                    if not isinstance(payload, dict):
                        raise ValueError("Expected a JSON object")
                    ids = await asyncio.to_thread(bank.render, payload)
                except Exception as exc:
                    raise HTTPException(400, "Invalid conversation/template input") from exc
                if not ids or len(ids) > 16384:
                    raise HTTPException(413, "Input exceeds the trained 16384-token context limit")
                rendered = time.perf_counter()
                response = await app.state.client.post("/generate", json={
                    "input_ids": ids, "sampling_params": {"max_new_tokens": 1, "temperature": 0},
                    "activation_capture": bank.capture,
                })
                response.raise_for_status()
                result = bank.score(bank.decode(response.json(), ids), len(ids))
                result["latency_ms"] = dict(render=(rendered-started)*1000,
                    detect=(time.perf_counter()-rendered)*1000, total=(time.perf_counter()-started)*1000)
                stats["completed"] += 1
                return result
        except HTTPException:
            raise
        except (TimeoutError, httpx.TimeoutException) as exc:
            stats["failed"] += 1
            raise HTTPException(504, "Probe request deadline exceeded") from exc
        except Exception as exc:
            stats["failed"] += 1
            logging.exception("Request activation probe failed")
            raise HTTPException(503, "Activation extraction or scoring failed") from exc
        finally:
            stats["active"] -= 1

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--probe-dir", type=Path, required=True)
    parser.add_argument("--upstream", default="http://127.0.0.1:8303")
    parser.add_argument("--port", type=int, default=8302)
    parser.add_argument("--enabled-risks", default=DEFAULT_ENABLED_RISKS, help="Comma-separated probe risks; default: ipi")
    parser.add_argument("--ipi-threshold", type=float, default=0.91)
    parser.add_argument("--max-inflight", type=int, default=128)
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()
    if args.max_inflight <= 0 or args.timeout <= 0:
        parser.error("max-inflight and timeout must be positive")
    torch.set_num_threads(2)
    bank = ProbeBank(args.model_path, args.probe_dir, args.ipi_threshold, args.enabled_risks)
    import uvicorn
    uvicorn.run(create_app(bank, args.upstream, max_inflight=args.max_inflight, timeout=args.timeout),
                host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
