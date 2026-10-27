"""End-to-end adapter compatibility: real inscope-service apps + CoolWatch adapter.

Deployment shape under test (decision A): **one instance = one risk**. Each instance
here is a real FastAPI app built by `create_app`, running in-process over an
httpx transport; one app per risk. Only tokenizer, probe and engine backend are
stubbed, because this must run without GPU. It proves the wire contract, auth and
the fan-out/merge that CoolWatch's ProbeBankGuard performs - not detection accuracy.

Run directly (``python evaluation/tests/test_probe_bank_e2e.py``) or under pytest.
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import torch
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[1]
# Checkout root, so `import backend` and `import inscope_server` both work no
# matter which directory this file is run from.
ROOT = REPO.parent
for entry in (str(ROOT), str(REPO), "/data/zmosg/inscope-service"):
    if entry not in sys.path:
        sys.path.insert(0, entry)


def _original_service_helpers():
    """Snapshot the unpatched profile helpers before any instance is built."""
    import inscope_server.app as app_module
    return {"get_profile": app_module.get_profile, "bind_profile": app_module.bind_profile}


_ORIGINAL_HELPERS = _original_service_helpers()


def _build_service(score, load=("ipi",), instance="ipi"):
    """One real service instance that evaluates exactly one risk.

    `load` lists the checkpoints this instance registers; a single-risk instance
    registers one. `instance` only labels the stubbed checkpoint identity so a
    test can tell two instances apart in the merged response.
    """
    import inscope_server.app as app_module
    from inscope_server.app import create_app

    # Restored by _restore(); must be the originals, not the previous instance's
    # patched pair, so consecutive instances do not nest patches.
    real_get_profile = _ORIGINAL_HELPERS["get_profile"]
    real_bind = _ORIGINAL_HELPERS["bind_profile"]
    profiles = "a6_nemotron_risk_faced_v1"
    profile = real_get_profile(profiles)

    class Profile:
        profile_id = profiles
        composer = profile.composer

        def describe(self):
            return profile.describe()

    app_module.bind_profile = lambda candidate, probe_id: candidate
    app_module.get_profile = lambda name: Profile()

    def make(risk, layer, threshold):
        # `risk` is the *instance* label used in the checkpoint identity; the
        # service itself always calls its single risk "indirect_prompt_injection".
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
        probe.score = lambda x: (score, score)
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
        composer_profile=profiles, backend_url="http://127.0.0.1:1", backend_api_key="",
        max_tokens=40959, max_inflight=4, timeout=60, analyze_timeout=600, analyze_batch=8,
        audit_timeout=1200, detect_batch=8, max_body_bytes=10 ** 7, max_batch_items=128,
        backend_max_inflight=4, probes={},
        detector_model="qwen3-8b", primary_risk=load[0])
    extra = {risk: make(f"{instance}-{risk}", 9 + 8 * index, 0.9)
             for index, risk in enumerate(load) if index}
    app = create_app(settings, tokenizer=Tokenizer(), probe=make(instance, 9, 0.9),
                     probes=extra or None, backend=Backend())
    return app, (real_bind, real_get_profile)


def _restore(saved):
    """Restore the profile helpers a check patched.

    `saved` is a list because `_run_two_instances` builds several instances in a
    row; the first entry is the pristine pair. A bare pair works too.
    """
    import inscope_server.app as app_module
    if not saved:
        return
    if isinstance(saved, list) and saved and isinstance(saved[0], tuple):
        bind, get = saved[0]
    else:
        bind, get = saved
    app_module.bind_profile, app_module.get_profile = bind, get


def _asgi_client(app):
    from httpx import ASGITransport, AsyncClient
    return AsyncClient(transport=ASGITransport(app=app))


def _run_two_instances(scores, requested=("ipi", "harmful")):
    """Build one service app per risk and drive the real guard against them."""
    from backend.watchers.probe_bank import ProbeBankGuard

    built, saved = {}, []
    for risk in requested:
        app, restore = _build_service(scores[risk], instance=risk)
        built[risk] = app
        saved.append(restore)
    try:
        async def run():
            endpoints = ",".join(f"{risk}=http://{risk}.instance" for risk in requested)
            guard = ProbeBankGuard(SimpleNamespace(
                probe_bank_base_url="http://probe", activation_probe_timeout_seconds=10,
                customer_agent_shadow_model="qwen3-8b",
                probe_bank_enabled_risks=",".join(requested), probe_bank_api_key="bank-secret",
                probe_bank_risk_endpoints=endpoints))
            await guard._client.aclose()
            clients = {f"http://{risk}.instance": _asgi_client(app) for risk, app in built.items()}

            class Router:
                """Route each request to the ASGI app of the instance it targets."""
                def __init__(self, clients):
                    self.clients = clients

                async def post(self, url, headers=None, json=None):
                    client = self.clients[url.split("/detect")[0]]
                    return await client.post(url, headers=headers, json=json)

                async def get(self, url, headers=None):
                    client = self.clients[url.split("/info")[0]]
                    return await client.get(url, headers=headers)

                async def aclose(self):  # guard.close() still works
                    pass

            guard._client = Router(clients)
            try:
                assessment = await guard.moderate(
                    [{"role": "user", "content": "Summarise the retrieved document."}])
                info = await guard.get_model_info()
            finally:
                for client in clients.values():
                    await client.aclose()
                await guard.close()
            return assessment, info
        return asyncio.run(run())
    finally:
        _restore(saved)


def check_auth_is_required():
    """CoolWatch used to send no Authorization; a service must reject that."""
    app, saved = _build_service(0.95)
    try:
        with TestClient(app) as client:
            anonymous = client.post("/detect", json={"messages": [{"role": "user", "content": "hi"}]})
            assert anonymous.status_code == 401, anonymous.text
            bad = client.post("/detect", headers={"authorization": "Bearer wrong"},
                              json={"messages": [{"role": "user", "content": "hi"}]})
            assert bad.status_code == 401, bad.text
    finally:
        _restore(saved)


def check_two_instances_merge():
    """One instance per risk: ipi flags, harmful does not -> merged per_risk."""
    assessment, info = _run_two_instances({"ipi": 0.95, "harmful": 0.2})
    assert assessment.error is None, assessment.error
    payload = assessment.payload
    assert assessment.risky is True, payload
    assert set(payload["per_risk"]) == {"ipi", "harmful"}, payload
    assert payload["triggered_entries"] == ["ipi"], payload
    assert set(payload["disabled_risks"]) == {"prompt_leakage"}
    assert all(isinstance(row["score"], float) for row in payload["per_risk"].values())
    assert payload["input_tokens"] > 0
    # Each risk came from its own instance, with its own checkpoint identity.
    assert "ipi@ipi-sha" in payload["bank_version"], payload["bank_version"]
    assert "harmful@harmful-sha" in payload["bank_version"], payload["bank_version"]
    # /info is composite but keeps the legacy single-risk fields working.
    assert set(info["per_risk"]) == {"ipi", "harmful"}, info
    assert info["detector"], info


def check_single_instance_benign():
    assessment, _ = _run_two_instances({"ipi": 0.05}, requested=("ipi",))
    assert assessment.error is None, assessment.error
    assert assessment.risky is False
    assert assessment.payload["per_risk"]["ipi"]["flagged"] is False


def check_subset_of_risks():
    """A single-risk instance deployment only asks for the risk it enabled."""
    from backend.watchers.probe_bank import ProbeBankGuard
    guard = ProbeBankGuard(SimpleNamespace(
        probe_bank_base_url="http://probe", activation_probe_timeout_seconds=10,
        customer_agent_shadow_model="qwen3-8b",
        probe_bank_enabled_risks="ipi", probe_bank_api_key="bank-secret",
        probe_bank_risk_endpoints=""))
    assert guard.endpoints == {"ipi": "http://probe"}
    assert guard.enabled_risks == ("ipi",)
    asyncio.run(guard.close())


def check_multi_risk_without_endpoints_is_rejected():
    """Two risks on one base_url is a configuration error, not a silent guess."""
    from backend.watchers.probe_bank import ProbeBankGuard
    try:
        ProbeBankGuard(SimpleNamespace(
            probe_bank_base_url="http://probe", activation_probe_timeout_seconds=10,
            probe_bank_enabled_risks="ipi,harmful", probe_bank_api_key="bank-secret",
            probe_bank_risk_endpoints=""))
    except ValueError as error:
        assert "exactly one risk" in str(error), error
    else:
        raise AssertionError("multi-risk config without per-risk endpoints was accepted")


def check_unreachable_instance_fails_closed():
    """One instance down is an error, never 'the other risks passed'."""
    from backend.watchers.probe_bank import ProbeBankGuard
    guard = ProbeBankGuard(SimpleNamespace(
        probe_bank_base_url="http://probe", activation_probe_timeout_seconds=2,
        customer_agent_shadow_model="qwen3-8b",
        probe_bank_enabled_risks="ipi,harmful", probe_bank_api_key="bank-secret",
        probe_bank_risk_endpoints="ipi=http://127.0.0.1:1,harmful=http://127.0.0.1:2"))

    async def run():
        try:
            return await guard.moderate([{"role": "user", "content": "hi"}])
        finally:
            await guard.close()
    assessment = asyncio.run(run())
    assert assessment.error is not None, assessment.payload
    assert assessment.risky is None


if __name__ == "__main__":
    for check, label in [
        (check_auth_is_required, "auth required"),
        (check_two_instances_merge, "two single-risk instances merge into per_risk"),
        (check_single_instance_benign, "single instance benign"),
        (check_subset_of_risks, "single-risk deployment keeps its endpoints"),
        (check_multi_risk_without_endpoints_is_rejected, "multi-risk without endpoints rejected"),
        (check_unreachable_instance_fails_closed, "unreachable instance fails closed"),
    ]:
        check()
        print(f"ok  {label}")
