"""Route-level contract tests for the probe-backed product paths.

The fan-out adapter tests prove the detector wiring. These tests prove what a
*caller* sees: the public `/v1/moderations` route and the customer-Agent
`defended` guarantee. They exist because passing adapter tests once hid a
route-level type regression (a scalar `latency_ms` unpacked as a mapping), so
nothing here should re-implement route logic; the real functions are executed.

No network, no database, no GPU, no detector accuracy claims.
"""
import ast
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.watchers.probe_bank import BankAssessment


APP_SOURCE = ROOT / "backend" / "app.py"
AGENT_SOURCE = ROOT / "backend" / "customer_agent.py"


def _toplevel(name):
    """Extract one top-level definition without importing `backend.app`."""
    tree = ast.parse(APP_SOURCE.read_text(encoding="utf-8"))
    node = next(item for item in tree.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name)
    if isinstance(node, ast.AsyncFunctionDef):
        node.decorator_list = []
    return node


def bank_payload(flagged, *, latency=100):
    return {
        "overall": flagged,
        "enabled_risks": ["ipi"],
        "disabled_risks": ["harmful", "prompt_leakage"],
        "per_risk": {"ipi": {"score": 0.97 if flagged else 0.04, "threshold": 0.9, "flagged": flagged}},
        "per_entry": {"ipi": 0.97 if flagged else 0.04},
        "triggered_entries": ["ipi"] if flagged else [],
        "detector_model": "Qwen3-8B-FP8",
        "bank_version": "ipi@sha-abc",
        "input_tokens": 17,
        "latency_ms": latency,
    }


def run_moderations(assessment):
    """Execute the real route with an injected assessment; return (status, body, usage writes)."""
    usage = SimpleNamespace(append=lambda **_: setattr(usage, "writes", usage.writes + 1), writes=0)
    guard = SimpleNamespace(moderate=_constant(assessment))
    namespace = dict(
        Request=Request, JSONResponse=JSONResponse, time=__import__("time"), uuid4=__import__("uuid").uuid4,
        probe_bank_guard=guard, auth_store=SimpleNamespace(current_user=lambda **_: {"id": "u1"}),
        usage_store=usage,
    )
    module = ast.Module(body=[_toplevel("_as_millis"), _toplevel("standardized_moderate")], type_ignores=[])
    exec(compile(module, str(APP_SOURCE), "exec"), namespace)
    app = FastAPI()
    app.post("/v1/moderations")(namespace["standardized_moderate"])

    async def call():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post("/v1/moderations", headers={"Authorization": "Bearer t"},
                                     json={"messages": [{"role": "user", "content": "hi"}]})

    response = asyncio.run(call())
    return response.status_code, response.json(), usage.writes


def _constant(value):
    async def moderate(*_, **__):
        return value
    return moderate


class ModerationRouteContractTests(unittest.TestCase):
    def test_benign_success_returns_scalar_latency_and_records_usage(self):
        status, body, writes = run_moderations(BankAssessment(bank_payload(False), 100))
        self.assertEqual(status, 200)
        self.assertEqual(body["action"], "pass")
        self.assertIsInstance(body["latency_ms"]["detector"], (int, float))
        self.assertIsInstance(body["latency_ms"]["total"], (int, float))
        self.assertEqual(body["per_risk"]["ipi"]["flagged"], False)
        self.assertEqual(writes, 1)

    def test_attack_success_returns_block_and_records_usage(self):
        status, body, writes = run_moderations(BankAssessment(bank_payload(True), 100))
        self.assertEqual(status, 200)
        self.assertEqual(body["action"], "block")
        self.assertEqual(body["triggered_entries"], ["ipi"])
        self.assertEqual(writes, 1)

    def test_detector_error_is_never_reported_as_pass(self):
        assessment = BankAssessment({}, 100, "Probe service for ipi failed: boom", 503)
        status, body, writes = run_moderations(assessment)
        self.assertEqual(status, 503)
        self.assertIn("error", body)
        self.assertNotIn("action", body)
        self.assertEqual(writes, 0)


AGENT_IMPORT_ERROR = None
try:  # pragma: no cover - import guard only
    from backend import customer_agent as agent_module
except Exception as exc:  # pragma: no cover
    agent_module = None
    AGENT_IMPORT_ERROR = exc


@unittest.skipIf(agent_module is None, f"customer_agent import unavailable: {AGENT_IMPORT_ERROR}")
class DefendedModeContractTests(unittest.TestCase):
    """A `defended` request must refuse rather than silently run undetected."""

    def _agent(self, *, enabled, activation_backend="probe_bank"):
        agent = agent_module.CustomerServiceAgent.__new__(agent_module.CustomerServiceAgent)
        agent.settings = SimpleNamespace(
            activation_probe_backend=activation_backend,
            customer_agent_enable_runtime_probes=True,
        )
        agent.runtime_config = SimpleNamespace(
            snapshot=lambda: (SimpleNamespace(defense_pipeline=tuple(enabled)), None)
        )
        return agent

    def test_enabled_defenses_excludes_probes_when_runtime_probes_disabled(self):
        agent = self._agent(enabled=["activation_probe", "qwen_guard"])
        agent.settings.customer_agent_enable_runtime_probes = False
        self.assertEqual(agent._enabled_defenses(), ("qwen_guard",))

    def test_requested_defense_that_is_not_enabled_is_detectable(self):
        agent = self._agent(enabled=["qwen_guard"])
        requested = ["activation_probe", "qwen_guard"]
        enabled = set(agent._enabled_defenses())
        dropped = sorted(set(requested) - enabled)
        self.assertEqual(dropped, ["activation_probe"])


class DefaultDefenseTests(unittest.TestCase):
    """A default request must actually run, not be refused for its own defaults.

    The shipped default listed `safegauge`, which the probe-bank backend never
    serves, so the defended-mode guard turned every default `/v1/guardrails`
    call into a refusal.
    """

    def test_default_defenses_are_served_by_probe_bank(self):
        from backend.customer_agent_schemas import default_customer_defenses
        # Mirrors CustomerServiceAgent._enabled_defenses: the probe-bank backend
        # drops `safegauge`, so a default that asks for it is always refused.
        probe_bank_served = {"activation_probe"}
        dropped = sorted(set(default_customer_defenses()) - probe_bank_served)
        self.assertEqual(dropped, [], "default request asks for a method probe_bank cannot serve")

    def test_default_request_keeps_detection_enabled(self):
        from backend.customer_agent_schemas import default_customer_defenses
        self.assertTrue(default_customer_defenses(), "a default defended run must not start undetected")


class ProbeHealthTests(unittest.TestCase):
    """Partial probe failure is an outage: detection is fail-closed per risk."""

    def test_partial_unavailable_is_reported_unreachable(self):
        agent = DefendedModeContractTests._agent(self, enabled=["qwen_guard"])
        agent.activation_probe_guard = SimpleNamespace(
            bank_guard=SimpleNamespace(
                enabled_risks=["harmful", "ipi"],
                get_model_info=_constant({
                    "enabled_risks": ["harmful", "ipi"],
                    "unavailable": [{"risk": "ipi", "base_url": "http://x", "error": "boom"}],
                }),
            )
        )
        enabled_risks, error, reachable = asyncio.run(agent._probe_health())
        self.assertIs(reachable, False)
        self.assertIn("ipi", error or "")
        self.assertEqual(enabled_risks, ["harmful", "ipi"])

    def test_all_instances_healthy_is_reachable(self):
        agent = DefendedModeContractTests._agent(self, enabled=["qwen_guard"])
        agent.activation_probe_guard = SimpleNamespace(
            bank_guard=SimpleNamespace(
                enabled_risks=["ipi"],
                get_model_info=_constant({"enabled_risks": ["ipi"], "unavailable": []}),
            )
        )
        _, error, reachable = asyncio.run(agent._probe_health())
        self.assertIs(reachable, True)
        self.assertIsNone(error)


class GuardrailsErrorMappingTests(unittest.TestCase):
    """A refused defended run is a service state problem, so it must be 503."""

    def test_refused_run_maps_to_503(self):
        route = _toplevel("guardrails_api")
        namespace = dict(
            HTTPException=__import__("fastapi").HTTPException,
            GuardrailsApiRequest=SimpleNamespace,
            CustomerAgentRunRequest=lambda **kwargs: SimpleNamespace(**kwargs),
        )

        async def refuse(*_, **__):
            raise RuntimeError("防护方法运行异常，本次业务执行已暂停，请稍后重试。")

        namespace["customer_agent_service"] = SimpleNamespace(run=refuse)
        exec(compile(ast.Module(body=[route], type_ignores=[]), str(APP_SOURCE), "exec"), namespace)
        payload = SimpleNamespace(input="hi", session_id=None)
        with self.assertRaises(__import__("fastapi").HTTPException) as caught:
            asyncio.run(namespace["guardrails_api"](payload))
        self.assertEqual(caught.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
