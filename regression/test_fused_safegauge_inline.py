from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.chat_orchestrator import ChatOrchestrator
from backend.moderation import ModerationService
from backend.schemas import ChatRequest, ModerationRequest, ScenarioPayload
from backend.watchers.inline_probing.client import (
    InlineProbingAssessment,
    build_inline_probing_request,
    input_attempt_fingerprint,
)
from backend.watchers.safegauge.client import (
    SafeGaugeAssessment,
    SafeGaugeGuard,
    SafeGaugeInlineAssessment,
)
from backend.watchers.safegauge.detector import LogProbsPrompt

ROOT = Path(__file__).resolve().parents[1]
OVERLAY_INLINE = (
    ROOT / "recipe/inline_probing/"
    "qwen3-8b-indirect-prompt-injection-assistant-prefix-probing/"
    "vllm-0.25.1-overlay/vllm/v1/inline_probing.py"
)
CHECKPOINT_ID = "sha256:" + "a" * 64


def load_overlay_inline_module():
    spec = importlib.util.spec_from_file_location("test_overlay_inline", OVERLAY_INLINE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeTokenizer:
    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
        assert tokenize is True and add_generation_prompt is True
        return {"input_ids": [10, 11, 12]}

    def encode(self, text, *, add_special_tokens):
        assert add_special_tokens is False
        return [20, 21]


class FakeCompletionResponse:
    def __init__(self, inline_result):
        self.choices = [
            SimpleNamespace(
                prompt_token_ids=[10, 11, 12, 20, 21],
                prompt_logprobs=[
                    None,
                    None,
                    None,
                    {20: {"logprob": -0.2}},
                    {21: {"logprob": -0.3}},
                ],
            )
        ]
        self.inline_result = inline_result

    def model_dump(self, *, mode):
        assert mode == "json"
        return {"inline_probing": self.inline_result}


class FakeCompletions:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class FusedProtocolTests(unittest.TestCase):
    def test_fingerprint_covers_raw_prompt_and_explicit_target(self):
        first = {"model": "m", "prompt": [1, 2], "max_tokens": 1}
        second = {"model": "m", "prompt": [1, 3], "max_tokens": 1}
        self.assertNotEqual(
            input_attempt_fingerprint(first),
            input_attempt_fingerprint(second),
        )
        request = build_inline_probing_request(
            first,
            expected_checkpoint_id=CHECKPOINT_ID,
            timeout_seconds=2,
            target_token_index=1,
        )
        self.assertEqual(request["target_token_index"], 1)
        with self.assertRaises(ValueError):
            build_inline_probing_request(
                first,
                expected_checkpoint_id=CHECKPOINT_ID,
                timeout_seconds=2,
                target_token_index=True,
            )

    def test_scheduler_contract_uses_explicit_prompt_index(self):
        module = load_overlay_inline_module()
        config = module.InlineProbingConfig(
            schema=module.CONFIG_SCHEMA,
            checkpoint_schema=module.CHECKPOINT_SCHEMA,
            scorer_contract_version=module.SCORER_CONTRACT,
            checkpoint_path="probe.pt",
            checkpoint_sha256="a" * 64,
            model_family="qwen3",
            model_revision="Qwen3-8B",
            target_layer=4,
            requested_position=-1,
            effective_position=-1,
            activation_kind="residual_stream_block_output",
            hidden_width=4096,
            normalization="checkpoint",
            tensor_parallel_size=1,
            pipeline_parallel_size=1,
        )
        payload = build_inline_probing_request(
            {"model": "m", "prompt": [1, 2, 3, 4, 5]},
            expected_checkpoint_id=CHECKPOINT_ID,
            timeout_seconds=2,
            target_token_index=2,
        )
        spec = module.make_capture_spec(
            request_id="request-1",
            request_payload=payload,
            prompt_token_ids=[1, 2, 3, 4, 5],
            scheduled_start=0,
            scheduled_count=5,
            scheduler_step=1,
            config=config,
        )
        self.assertEqual(spec.target_token_index, 2)

        before_target = module.make_capture_spec(
            request_id="request-1",
            request_payload=payload,
            prompt_token_ids=[1, 2, 3, 4, 5],
            scheduled_start=0,
            scheduled_count=2,
            scheduler_step=1,
            config=config,
        )
        target_chunk = module.make_capture_spec(
            request_id="request-1",
            request_payload=payload,
            prompt_token_ids=[1, 2, 3, 4, 5],
            scheduled_start=2,
            scheduled_count=2,
            scheduler_step=2,
            config=config,
        )
        self.assertIsNone(before_target)
        self.assertEqual(target_chunk.target_token_index, 2)

    def test_safegauge_fused_request_preserves_raw_token_prompt(self):
        inline_result = {
            "schema": "inline_probing.result.v1",
            "status": "ok",
            "checkpoint_id": CHECKPOINT_ID,
        }
        response = FakeCompletionResponse(inline_result)
        completions = FakeCompletions(response)
        extractor = LogProbsPrompt.__new__(LogProbsPrompt)
        extractor.mode = "server"
        extractor.client = SimpleNamespace(completions=completions)
        extractor.model = "qwen3-8b"
        extractor.tokenizer = FakeTokenizer()

        plan = extractor.prepare_fused_request(
            [{"role": "assistant", "content": "fixed suffix"}],
            logprobs_num=2,
        )
        self.assertEqual(plan.prompt_tokens, [10, 11, 12, 20, 21])
        self.assertEqual(plan.target_token_index, 2)
        payload = dict(plan.request_payload)
        payload["inline_probing_request"] = {"schema": "inline_probing.request.v1"}
        logprobs, dumped = extractor.execute_fused_request(plan, payload)

        self.assertEqual(logprobs, [-0.2, -0.3])
        self.assertEqual(dumped["inline_probing"], inline_result)
        call = completions.calls[0]
        self.assertEqual(call["prompt"], plan.prompt_tokens)
        self.assertFalse(call["extra_body"]["add_special_tokens"])
        self.assertEqual(
            call["extra_body"]["inline_probing_request"]["schema"],
            "inline_probing.request.v1",
        )


class FusedGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_guard_returns_both_assessments_from_one_detector_call(self):
        settings = SimpleNamespace(
            inline_probing_task="system_prompt_leakage_intent",
            inline_probing_threshold=0.5,
            inline_probing_expected_checkpoint_id=CHECKPOINT_ID,
            inline_probing_timeout_seconds=5,
            inline_probing_protocol="inline_probing",
        )
        guard = SafeGaugeGuard(settings)
        plan = SimpleNamespace(
            target_token_index=2,
            request_payload={
                "model": "qwen3-8b",
                "prompt": [10, 11, 12, 20, 21],
                "max_tokens": 1,
                "temperature": 0,
                "top_p": 0.95,
                "prompt_logprobs": 2,
                "return_token_ids": True,
                "add_special_tokens": False,
                "cache_salt": "unique",
            },
        )

        class FakeDetector:
            calls = 0

            def prepare_fused_request(self, messages):
                return plan

            def detect_fused(self, actual_plan, payload, threshold):
                self.calls += 1
                self.inline_request = payload["inline_probing_request"]
                return (
                    {
                        "task": "system_prompt_leakage_intent",
                        "label": "risk",
                        "probability": 0.9,
                        "threshold": 0.5,
                        "risky": True,
                        "logprobs": [-0.2, -0.3],
                    },
                    {
                        "inline_probing": {
                            "schema": "inline_probing.result.v1",
                            "status": "ok",
                            "checkpoint_id": CHECKPOINT_ID,
                            "score": 0.8,
                            "logit": 1.4,
                            "captured_token_index": 2,
                            "layer": 4,
                            "effective_position": -1,
                        }
                    },
                )

        detector = FakeDetector()
        guard._get_detector = AsyncMock(return_value=detector)
        result = await guard.moderate_messages_with_inline(
            [{"role": "user", "content": "test"}],
            task="system_prompt_leakage_intent",
        )

        self.assertEqual(detector.calls, 1)
        self.assertEqual(detector.inline_request["target_token_index"], 2)
        self.assertTrue(result.safegauge.risky)
        self.assertTrue(result.inline_probing.risky)

    async def test_moderation_service_fuses_compatible_tasks(self):
        safe = SafeGaugeAssessment(
            task="system_prompt_leakage_intent",
            label="safe",
            probability=0.1,
            threshold=0.5,
            logprobs=[],
            risky=False,
            raw_output="{}",
            latency_ms=10,
        )
        inline = InlineProbingAssessment(
            score=0.2,
            logit=-1.0,
            threshold=0.5,
            checkpoint_id=CHECKPOINT_ID,
            layer=4,
            effective_position=-1,
            protocol="inline_probing",
            raw_output=json.dumps({}),
            latency_ms=10,
        )
        safegauge_guard = SimpleNamespace(
            can_fuse_inline=lambda task: task == "system_prompt_leakage_intent",
            moderate_messages_with_inline=AsyncMock(
                return_value=SafeGaugeInlineAssessment(safe, inline)
            ),
            moderate_messages=AsyncMock(side_effect=AssertionError("not fused")),
        )
        inline_guard = SimpleNamespace(
            moderate_messages=AsyncMock(side_effect=AssertionError("not fused"))
        )
        service = ModerationService(
            qwen_guard_client=SimpleNamespace(),
            llama_prompt_guard_client=SimpleNamespace(),
            netease_yidun_client=SimpleNamespace(),
            safegauge_guard=safegauge_guard,
            inline_probing_guard=inline_guard,
        )
        response = await service.moderate(
            ModerationRequest(
                text="test",
                guards=["safegauge", "inline_probing"],
                task="system_prompt_leakage_intent",
                model="qwen3-8b",
            )
        )

        safegauge_guard.moderate_messages_with_inline.assert_awaited_once()
        self.assertEqual(list(response.results), ["safegauge", "inline_probing"])
        self.assertFalse(response.risky)

    async def test_moderation_service_does_not_fuse_mismatched_tasks(self):
        safe = SafeGaugeAssessment(
            task="system_prompt_leakage_intent",
            label="safe",
            probability=0.1,
            threshold=0.5,
            logprobs=[],
            risky=False,
            raw_output="{}",
            latency_ms=10,
        )
        inline = InlineProbingAssessment(
            score=0.2,
            logit=-1.0,
            threshold=0.5,
            checkpoint_id=CHECKPOINT_ID,
            layer=4,
            effective_position=-1,
            protocol="inline_probing",
            raw_output="{}",
            latency_ms=10,
        )
        safegauge_guard = SimpleNamespace(
            can_fuse_inline=lambda task: False,
            moderate_messages_with_inline=AsyncMock(
                side_effect=AssertionError("must remain separate")
            ),
            moderate_messages=AsyncMock(return_value=safe),
        )
        inline_guard = SimpleNamespace(moderate_messages=AsyncMock(return_value=inline))
        service = ModerationService(
            qwen_guard_client=SimpleNamespace(),
            llama_prompt_guard_client=SimpleNamespace(),
            netease_yidun_client=SimpleNamespace(),
            safegauge_guard=safegauge_guard,
            inline_probing_guard=inline_guard,
        )

        response = await service.moderate(
            ModerationRequest(
                text="test",
                guards=["safegauge", "inline_probing"],
                task="system_prompt_leakage_intent",
            )
        )

        safegauge_guard.moderate_messages_with_inline.assert_not_awaited()
        safegauge_guard.moderate_messages.assert_awaited_once()
        inline_guard.moderate_messages.assert_awaited_once()
        self.assertFalse(response.risky)

    async def test_chat_input_guards_use_fused_prefill_when_task_matches(self):
        safe = SafeGaugeAssessment(
            task="system_prompt_leakage_intent",
            label="safe",
            probability=0.1,
            threshold=0.5,
            logprobs=[],
            risky=False,
            raw_output="{}",
            latency_ms=10,
        )
        inline = InlineProbingAssessment(
            score=0.2,
            logit=-1.0,
            threshold=0.5,
            checkpoint_id=CHECKPOINT_ID,
            layer=4,
            effective_position=-1,
            protocol="inline_probing",
            raw_output="{}",
            latency_ms=10,
        )
        safegauge_guard = SimpleNamespace(
            can_fuse_inline=lambda task: task == "system_prompt_leakage_intent",
            moderate_messages_with_inline=AsyncMock(
                return_value=SafeGaugeInlineAssessment(safe, inline)
            ),
            moderate_messages=AsyncMock(side_effect=AssertionError("not fused")),
        )
        activation_guard = SimpleNamespace(
            moderate_messages=AsyncMock(side_effect=AssertionError("not fused"))
        )
        orchestrator = ChatOrchestrator(
            agent_loop=SimpleNamespace(),
            qwen_guard_client=SimpleNamespace(),
            llama_prompt_guard_client=SimpleNamespace(),
            netease_yidun_client=SimpleNamespace(),
            safegauge_guard=safegauge_guard,
            inline_probing_guard=SimpleNamespace(),
            activation_probe_guard=activation_guard,
        )
        request = ChatRequest(
            session_id="session",
            message="test",
            selected_guards=["safegauge", "inline_probing"],
            scenario=ScenarioPayload(
                id="prompt-test",
                category="prompt",
                systemPrompt="system",
            ),
        )

        assessments = await orchestrator._run_input_guard_checks(request)

        safegauge_guard.moderate_messages_with_inline.assert_awaited_once()
        self.assertIs(assessments["safegauge"], safe)
        self.assertIs(assessments["inline_probing"], inline)


if __name__ == "__main__":
    unittest.main()
