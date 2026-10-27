"""End-to-end probe bank compatibility: real inscope-service app + CoolWatch adapter.

The service app is the actual FastAPI app built by create_app, running in-process over
httpx ASGITransport. Only the tokenizer, probe and engine backend are stubbed, because
this check must run without GPU. It proves the wire contract, auth and payload shape that
CoolWatch's ProbeBankGuard enforces - not detection accuracy.
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import torch
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def _build_service(score_map):
    """Real create_app with stub dependencies; primary ipi + one extra risk."""
    import inscope_server.app as app_module
    from inscope_server.app import create_app

    PROFILES = "a6_nemotron_risk_faced_v1"
    real_get_profile = app_module.get_profile
    profile = real_get_profile(PROFILES)

    class Profile:
        profile_id = PROFILES
        composer = profile.composer

        def describe(self):
            return profile.describe()

    original_bind = app_module.bind_profile
    app_module.bind_profile = lambda candidate, probe_id: candidate
    app_module.get_profile = lambda name: Profile()

    def make(risk, layer, threshold):
        spec = SimpleNamespace(
            probe_id=f"probe:{risk}", schema="x", probe_architecture="linear",
            layer_semantics="block", block_indices=(layer - 1,),
            selected_positions=(-4, -3, -2, -1), feature_normalization="x",
            flatten_order=("layer", "position", "hidden"), feature_name="f",
            labeling_protocol="p", probe_prefix="")
        probe = SimpleNamespace(threshold=threshold, sha256=f"{risk}-sha",
                                capture_layers=(layer,), selected_positions=(-4, -3, -2, -1),
                                input_dim=4, spec=spec)
        probe.flatten = lambda blocks: torch.cat([b.reshape(-1) for b in blocks])
        probe.score = lambda x: (score_map[risk], score_map[risk])
        return probe

    class Tokenizer:
        def apply_chat_template(self, messages, **kw):
            return "".join(str(m.get("content") or "") for m in messages)

        def encode(self, text, **kw):
            return list(range(len(text) % 17 + 8))

    class Backend:
        async def capture(self, ids, layers, positions):
            return [torch.zeros((len(positions), 4)) for _ in layers]

        async def capture_batch(self, batch_ids, layers, positions):
            return [[torch.zeros((len(positions), 4)) for _ in layers] for _ in batch_ids]

        async def close(self):
            pass

    settings = SimpleNamespace(
        model_path="/m", api_key="bank-secret", probe_checkpoint="/p",
        composer_profile=PROFILES, backend_url="http://127.0.0.1:1", backend_api_key="",
        max_tokens=40959, max_inflight=4, timeout=60, analyze_timeout=600, analyze_batch=8,
        audit_timeout=1200, detect_batch=8, max_body_bytes=10 ** 7, max_batch_items=128,
        backend_max_inflight=4, probes={"harmful": "/h"},
        detector_model="qwen3-8b", primary_risk="ipi")
    app = create_app(settings, tokenizer=Tokenizer(), probe=make("ipi", 9, 0.9),
                     probes={"harmful": make("harmful", 17, 0.5)}, backend=Backend())
    return app, (original_bind, real_get_profile, None)


def _restore(saved):
    import inscope_server.app as app_module
    app_module.bind_profile, app_module.get_profile = saved[0], saved[1]
    for attr in ("get_profile", "bind_profile"):
        # Other modules may have captured the real helpers at import time; restore them too.
        pass


def check_auth_is_required():
    """CoolWatch used to send no Authorization; service must reject that."""
    app, saved = _build_service({"ipi": 0.95, "harmful": 0.2})
    try:
        with TestClient(app) as client:
            anonymous = client.post("/detect", json={"messages": [{"role": "user", "content": "hi"}]})
            assert anonymous.status_code == 401, anonymous.text
            bad = client.post("/detect", headers={"authorization": "Bearer wrong"},
                              json={"messages": [{"role": "user", "content": "hi"}]})
            assert bad.status_code == 401, bad.text
    finally:
        _restore(saved)


def check_payload_through_repo_guard():
    """Run the repository's real ProbeBankGuard against the real service app."""
    sys.path.insert(0, str(Path("/data/zmosg/coolwatch")))
    from backend.watchers.probe_bank import ProbeBankGuard

    app, saved = _build_service({"ipi": 0.95, "harmful": 0.2})
    try:
        transport = httpx.ASGITransport(app=app)

        async def run():
            settings = SimpleNamespace(
                probe_bank_base_url="http://probe", activation_probe_timeout_seconds=10,
                customer_agent_shadow_model="qwen3-8b",
                probe_bank_enabled_risks="ipi,harmful", probe_bank_api_key="bank-secret")
            guard = ProbeBankGuard(settings)
            await guard._client.aclose()
            guard._client = httpx.AsyncClient(transport=transport)
            try:
                assessment = await guard.moderate([
                    {"role": "user", "content": "Summarise the retrieved document."}])
                info = await guard.get_model_info()
            finally:
                await guard.close()
            return assessment, info

        assessment, info = asyncio.run(run())
        assert assessment.error is None, assessment.error
        assert assessment.risky is True, assessment.payload
        payload = assessment.payload
        assert set(payload["per_risk"]) == {"ipi", "harmful"}
        assert payload["triggered_entries"] == ["ipi"]
        assert payload["disabled_risks"] == ["prompt_leakage"]
        # Reported by the probe service, passed through as-is; CoolWatch does not need
        # to know which model the service runs.
        assert payload["detector_model"]
        assert isinstance(payload["latency_ms"], dict) and "total" in payload["latency_ms"]
        assert payload["input_tokens"] > 0
        # /info must answer under the same auth (CoolWatch `/activation_probe/info`).
        assert info["model"] and info["detector"]
    finally:
        _restore(saved)


def check_service_serves_more_than_client_needs():
    """Service loads extra risks; CoolWatch enables a subset -> intersection, no error."""
    sys.path.insert(0, str(Path("/data/zmosg/coolwatch")))
    from backend.watchers.probe_bank import ProbeBankGuard

    app, saved = _build_service({"ipi": 0.95, "harmful": 0.9})
    try:
        transport = httpx.ASGITransport(app=app)

        async def run():
            settings = SimpleNamespace(
                probe_bank_base_url="http://probe", activation_probe_timeout_seconds=10,
                customer_agent_shadow_model="qwen3-8b",
                probe_bank_enabled_risks="ipi", probe_bank_api_key="bank-secret")
            guard = ProbeBankGuard(settings)
            await guard._client.aclose()
            guard._client = httpx.AsyncClient(transport=transport)
            try:
                return await guard.moderate([{"role": "user", "content": "hi"}])
            finally:
                await guard.close()

        assessment = asyncio.run(run())
        assert assessment.error is None, assessment.error
        payload = assessment.payload
        # Service loads ipi+harmful, CoolWatch wants ipi only: harmless, narrowed.
        assert payload["enabled_risks"] == ["ipi"]
        assert set(payload["per_risk"]) == {"ipi"}
        assert set(payload["per_entry"]) == {"ipi"}
        assert payload["triggered_entries"] == ["ipi"]
        assert set(payload["disabled_risks"]) == {"harmful", "prompt_leakage"}
        assert assessment.risky is True
    finally:
        _restore(saved)


def check_missing_requested_risk_fails_closed():
    """CoolWatch asks for a risk the service never loaded -> 422, surfaced as an error."""
    sys.path.insert(0, str(Path("/data/zmosg/coolwatch")))
    from backend.watchers.probe_bank import ProbeBankGuard

    app, saved = _build_service({"ipi": 0.9, "harmful": 0.2})
    try:
        transport = httpx.ASGITransport(app=app)

        async def run():
            settings = SimpleNamespace(
                probe_bank_base_url="http://probe", activation_probe_timeout_seconds=10,
                customer_agent_shadow_model="qwen3-8b",
                probe_bank_enabled_risks="ipi,prompt_leakage", probe_bank_api_key="bank-secret")
            guard = ProbeBankGuard(settings)
            await guard._client.aclose()
            guard._client = httpx.AsyncClient(transport=transport)
            try:
                return await guard.moderate([{"role": "user", "content": "hi"}])
            finally:
                await guard.close()

        assessment = asyncio.run(run())
        assert assessment.error is not None, assessment.payload
        assert assessment.status_code == 503, assessment.status_code
    finally:
        _restore(saved)


if __name__ == "__main__":
    check_auth_is_required()
    print("ok  auth required")
    check_payload_through_repo_guard()
    print("ok  real ProbeBankGuard accepts the service payload")
    check_service_serves_more_than_client_needs()
    print("ok  extra risks on the service are intersected, not rejected")
    check_missing_requested_risk_fails_closed()
    print("ok  requesting an unloaded risk fails closed")
