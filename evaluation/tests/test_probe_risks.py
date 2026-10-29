"""Per-risk probe fan-out adapter tests.

Deployment contract under test: **one probe service instance evaluates exactly one
risk**, so N risks = N instances, merged back into one `per_risk` view here.
Synthetic responses only; this measures wiring, never detector accuracy.
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest

import httpx
import json

# Checkout root, so `import backend` works whether this file is run from the repo
# root or from evaluation/.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.probe_risks import parse_enabled_risks, parse_risk_endpoints
from backend.watchers import probe_bank as bank
from backend.watchers.probe_bank import ProbeBankGuard


def settings(**overrides):
    base = dict(probe_bank_enabled_risks="ipi", probe_bank_risk_endpoints="",
                probe_bank_base_url="http://test", probe_bank_api_key="test-bank-key",
                activation_probe_timeout_seconds=10)
    base.update(overrides)
    return SimpleNamespace(**base)


def detect_payload(probability, threshold=0.9, model="Qwen3-8B-FP8", sha="sha-abc", risk="indirect_prompt_injection"):
    """One single-risk service's response, in inscope-service 0.6.0 shape."""
    return dict(logit=0.0, probability=probability, threshold=threshold,
                label="attack" if probability >= threshold else "benign",
                risk=risk, model=model, input_tokens=17,
                request_id="req_x", latency_ms=1.0,
                composer_profile="a6_nemotron_risk_faced_v1", checkpoint_sha256=sha,
                blocks=[dict(message_index=0, kind="block", start=0, end=2,
                             source_message_indices=[0])],
                coordinate_system="compiled_messages",
                importance_semantics="cached cumulative-prefix evidence")


class EndpointResolutionTests(unittest.TestCase):
    def test_single_risk_uses_legacy_base_url(self):
        self.assertEqual(ProbeBankGuard(settings()).endpoints, {"ipi": "http://test"})

    def test_multi_risk_needs_one_endpoint_each(self):
        # One instance cannot answer for another risk, so this must not silently pass.
        with self.assertRaisesRegex(ValueError, "exactly one risk"):
            ProbeBankGuard(settings(probe_bank_enabled_risks="harmful,ipi"))

    def test_multi_risk_with_explicit_endpoints(self):
        guard = ProbeBankGuard(settings(
            probe_bank_enabled_risks="harmful,ipi",
            probe_bank_risk_endpoints="harmful=http://127.0.0.1:8301/,ipi=http://h:9302"))
        self.assertEqual(guard.endpoints,
                         {"harmful": "http://127.0.0.1:8301", "ipi": "http://h:9302"})

    def test_endpoint_for_disabled_risk_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "not enabled"):
            ProbeBankGuard(settings(probe_bank_risk_endpoints="harmful=http://127.0.0.1:8301"))

    def test_malformed_endpoint_lists_rejected(self):
        for raw in ["ipi", "nope=http://x:1", "ipi=http://x:1,ipi=http://y:2", "ipi=ftp://x:1"]:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_risk_endpoints(raw)

    def test_risk_selection_validation(self):
        self.assertEqual(parse_enabled_risks(), ("ipi",))
        self.assertEqual(set(parse_enabled_risks("ipi,harmful")), {"ipi", "harmful"})
        for invalid in ["", "ipi,typo", "ipi,"]:
            with self.assertRaises(ValueError):
                parse_enabled_risks(invalid)


class FanOutTests(unittest.IsolatedAsyncioTestCase):
    async def _guard(self, responses, risks=("ipi",), **setting_overrides):
        """Guard whose per-risk HTTP is a MockTransport keyed by risk port."""
        setting_overrides.setdefault(
            "probe_bank_risk_endpoints",
            ",".join(f"{risk}=http://probe:{8301 + index}" for index, risk in enumerate(risks)))
        guard = ProbeBankGuard(settings(probe_bank_enabled_risks=",".join(risks), **setting_overrides))
        await guard._client.aclose()
        seen = []

        def handler(request):
            port = request.url.port
            risk = by_port[port]
            seen.append((risk, request))
            if request.url.path == "/info":
                # The live service advertises its risk code here (KNOWN_RISKS),
                # e.g. "ipi" — not the model risk name.
                return httpx.Response(200, json={"risks": [{"risk": risk}]})
            value = responses[risk]
            if isinstance(value, Exception):
                return httpx.Response(getattr(value, "status_code", 500), json={"detail": "boom"})
            return httpx.Response(200, json=value)

        # Give every risk a distinct port so the handler can tell instances apart.
        guard.probes = tuple(bank._RiskProbe(risk, f"http://probe:{8301 + index}")
                             for index, risk in enumerate(risks))
        by_port = {8301 + index: risk for index, risk in enumerate(risks)}
        guard._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return guard, seen

    async def test_info_then_detect_happy_path(self):
        # Identity first (/info), then score (/detect). The registry speaks
        # risk codes ("ipi"); the /detect payload carries the model risk name
        # ("indirect_prompt_injection") — two different identifiers by design.
        guard, seen = await self._guard({"ipi": detect_payload(0.15)})
        try:
            assessment = await guard.moderate([{"role": "user", "content": "x"}])
        finally:
            await guard.close()
        self.assertIsNone(assessment.error, assessment.error)
        self.assertEqual(assessment.payload["per_risk"]["ipi"]["score"], 0.15)
        self.assertTrue(any(request.url.path == "/info" for _, request in seen))
        self.assertTrue(any(request.url.path == "/detect" for _, request in seen))

    async def test_detect_risk_must_be_model_name_not_code(self):
        # A /detect payload answering with the risk code instead of the model
        # risk name means the wire contract broke; fail closed.
        guard, _ = await self._guard({"ipi": detect_payload(0.15, risk="ipi")})
        try:
            result = await guard.moderate([{"role": "user", "content": "hi"}])
        finally:
            await guard.close()
        self.assertIsNotNone(result.error)
        self.assertIn("indirect_prompt_injection", result.error)
        self.assertIsNone(result.risky)

    async def test_two_instances_merge_into_per_risk(self):
        guard, seen = await self._guard(
            {"harmful": detect_payload(0.93, risk="harmful", sha="sha_harmful"),
             "ipi": detect_payload(0.10, sha="sha_ipi")},
            risks=("harmful", "ipi"))
        try:
            result = await guard.moderate([{"role": "user", "content": "hi"}])
        finally:
            await guard.close()
        self.assertIsNone(result.error, result.error)
        payload = result.payload
        self.assertEqual(set(payload["per_risk"]), {"harmful", "ipi"})
        self.assertTrue(payload["per_risk"]["harmful"]["flagged"])
        self.assertFalse(payload["per_risk"]["ipi"]["flagged"])
        self.assertTrue(payload["overall"])
        self.assertTrue(result.risky)
        self.assertEqual(payload["triggered_entries"], ["harmful"])
        self.assertEqual(set(payload["disabled_risks"]), {"prompt_leakage"})
        # Each instance's identity is preserved; nothing is flattened to one bank.
        self.assertIn("harmful@sha_harmful", payload["bank_version"])
        self.assertIn("ipi@sha_ipi", payload["bank_version"])
        self.assertEqual(payload["detector_model"], "Qwen3-8B-FP8")
        # Each instance is identified, then scored: one /info and one /detect.
        self.assertEqual(sorted(request.url.path for _, request in seen), ["/detect", "/detect", "/info", "/info"])
        for _, request in seen:
            self.assertEqual(request.headers["authorization"], "Bearer test-bank-key")
        detect_requests = [request for _, request in seen if request.url.path == "/detect"]
        self.assertTrue(all(json.loads(request.content)["explain"] is True for request in detect_requests))
        self.assertEqual(payload["per_risk_detail"]["ipi"]["blocks"][0]["source_message_indices"], [0])

    async def test_single_instance_benign(self):
        guard, _ = await self._guard({"ipi": detect_payload(0.05)})
        try:
            result = await guard.moderate([{"role": "user", "content": "hi"}])
        finally:
            await guard.close()
        self.assertIsNone(result.error, result.error)
        self.assertFalse(result.risky)
        self.assertEqual(result.payload["per_risk"]["ipi"],
                         {"score": 0.05, "threshold": 0.9, "flagged": False})

    async def test_one_instance_failing_fails_closed(self):
        guard, _ = await self._guard({"ipi": detect_payload(0.05), "harmful": RuntimeError("down")},
                                     risks=("ipi", "harmful"))
        try:
            result = await guard.moderate([{"role": "user", "content": "hi"}])
        finally:
            await guard.close()
        # One risk unavailable is never reported as "the others passed".
        self.assertIsNotNone(result.error)
        self.assertIn("harmful", result.error)
        self.assertIsNone(result.risky)

    async def test_http_error_status_is_passed_through(self):
        # A 429 from the instance must stay a 429: the caller maps it to a
        # "retry later" error rather than treating it like any other failure.
        guard, _ = await self._guard({"ipi": None},
                                     probe_bank_risk_endpoints="ipi=http://probe:8301")
        guard._client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(429, json={"detail": "overloaded"})))
        try:
            result = await guard.moderate([{"role": "user", "content": "hi"}])
        finally:
            await guard.close()
        self.assertIsNotNone(result.error)
        self.assertEqual(result.status_code, 429)

    async def test_label_threshold_mismatch_is_an_error(self):
        bad = detect_payload(0.10)
        bad["label"] = "attack"
        guard, _ = await self._guard({"ipi": bad})
        try:
            result = await guard.moderate([{"role": "user", "content": "hi"}])
        finally:
            await guard.close()
        self.assertIn("inconsistent", result.error or "")

    async def test_missing_probability_is_an_error(self):
        guard, _ = await self._guard({"ipi": {"threshold": 0.9, "label": "benign", "model": "m"}})
        try:
            result = await guard.moderate([{"role": "user", "content": "hi"}])
        finally:
            await guard.close()
        self.assertIsNotNone(result.error)

    async def test_missing_model_is_an_error(self):
        payload = detect_payload(0.05)
        payload["model"] = ""
        guard, _ = await self._guard({"ipi": payload})
        try:
            self.assertIsNotNone((await guard.moderate([])).error)
        finally:
            await guard.close()

    async def test_legacy_flagged_without_probability_row_is_rejected(self):
        # The service must report probability/threshold; a pre-computed row alone
        # would let a future service flatten its verdict and hide the score.
        guard, _ = await self._guard({"ipi": dict(model="m", per_risk={
            "ipi": dict(flagged=False, score=0.1, threshold=0.9)})})
        try:
            self.assertIsNotNone((await guard.moderate([])).error)
        finally:
            await guard.close()

    async def test_wrong_instance_identity_fails_closed(self):
        # A harmful URL that actually loaded IPI must not be scored as harmful.
        guard, seen = await self._guard({"harmful": detect_payload(0.93)}, risks=("harmful",))

        def handler(request):
            seen.append(("harmful", request))
            if request.url.path == "/info":
                return httpx.Response(200, json={"risks": [{"risk": "ipi"}]})
            return httpx.Response(200, json=detect_payload(0.93))

        await guard._client.aclose()
        guard._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            result = await guard.moderate([{"role": "user", "content": "hi"}])
        finally:
            await guard.close()
        self.assertIsNotNone(result.error)
        self.assertIn("advertises ipi", result.error)
        self.assertIsNone(result.risky)
        self.assertTrue(all(request.url.path == "/info" for _, request in seen))

    async def test_multi_risk_instance_is_rejected(self):
        guard, _ = await self._guard({"ipi": detect_payload(0.05)})

        def handler(request):
            return httpx.Response(200, json={"risks": [{"risk": "ipi"}, {"risk": "harmful"}]})

        await guard._client.aclose()
        guard._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            result = await guard.moderate([{"role": "user", "content": "hi"}])
        finally:
            await guard.close()
        self.assertIn("advertises ipi,harmful", result.error or "")
        self.assertIsNone(result.risky)


class ModelInfoTests(unittest.IsolatedAsyncioTestCase):
    async def test_composite_info_keeps_legacy_top_level_fields(self):
        guard = ProbeBankGuard(settings(probe_bank_enabled_risks="harmful,ipi",
                                        probe_bank_risk_endpoints="harmful=http://h1,ipi=http://h2"))

        async def fake_fetch(probe):
            if probe.risk == "ipi":
                return {"detector": "linear:arm6", "model": "Qwen3-8B-FP8", "threshold": 0.9,
                        "risks": [{"risk": "ipi"}]}
            raise ValueError("down")
        guard._fetch_info = fake_fetch
        info = await guard.get_model_info()
        self.assertEqual(info["enabled_risks"], ["harmful", "ipi"])
        self.assertEqual(set(info["per_risk"]), {"ipi"})
        self.assertEqual([item["risk"] for item in info["unavailable"]], ["harmful"])
        # First *working* instance populates the legacy single-risk fields.
        self.assertEqual(info["threshold"], 0.9)

    async def test_wrong_risk_identity_is_unavailable(self):
        guard = ProbeBankGuard(settings())

        async def fake_fetch(probe):
            return {"risks": [{"risk": "harmful"}]}
        guard._fetch_info = fake_fetch
        info = await guard.get_model_info()
        self.assertNotIn("ipi", info["per_risk"])
        self.assertEqual(len(info["unavailable"]), 1)
        self.assertIn("advertises harmful", info["unavailable"][0]["error"])

    async def test_all_instances_down_raises(self):
        guard = ProbeBankGuard(settings())

        async def fake_fetch(probe):
            raise ValueError("down")
        guard._fetch_info = fake_fetch
        with self.assertRaisesRegex(ValueError, "ipi"):
            await guard.get_model_info()


if __name__ == "__main__":
    unittest.main()
