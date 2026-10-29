"""Risk selection tests; synthetic vectors do not measure detector accuracy."""
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx
from backend.probe_risks import parse_enabled_risks
from backend.watchers.probe_bank import ProbeBankGuard


class RiskSelectionTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _detect_payload(**overrides):
        """inscope-service /detect 的最小合法响应。"""
        payload = dict(risk='indirect_prompt_injection', model='qwen3-8b', probability=0.1, logit=-2.2,
                       threshold=0.9777, label='benign',
                       composer=dict(probe_id='attention_block:test'),
                       checkpoint_sha256='a' * 64, input_tokens=20,
                       blocks=[dict(message_index=3, kind='block', start=0, end=10,
                                    attention_weight=0.9, attention_contribution=1.2,
                                    source_message_indices=[3])],
                       coordinate_system='compiled_messages',
                       importance_semantics='cached cumulative-prefix evidence')
        payload.update(overrides)
        return payload

    def test_selection_validation(self):
        self.assertEqual(parse_enabled_risks(), ('ipi',))
        self.assertEqual(set(parse_enabled_risks('ipi,harmful')), {'ipi','harmful'})
        for invalid in ['', 'ipi,typo', 'ipi,']:
            with self.assertRaises(ValueError): parse_enabled_risks(invalid)

    def _guard(self, endpoints=''):
        settings = SimpleNamespace(probe_bank_base_url='http://test',
                                   probe_bank_risk_endpoints=endpoints,
                                   activation_probe_timeout_seconds=10,
                                   customer_agent_shadow_model='qwen3-8b',
                                   probe_bank_enabled_risks='ipi')
        return ProbeBankGuard(settings)

    async def test_adapter_accepts_one_detector_per_risk(self):
        guard = self._guard()
        await guard._client.aclose()
        payload = self._detect_payload()
        guard._client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json=payload)))
        try:
            clean = await guard.moderate([{'role': 'user', 'content': 'test'}])
            self.assertIsNone(clean.error)
            self.assertFalse(clean.risky)
            self.assertEqual(list(clean.payload['per_risk']), ['ipi'])
            self.assertEqual(clean.payload['probes']['ipi']['checkpoint_sha256'], 'a' * 64)
            payload.update(probability=0.99, label='attack')
            self.assertTrue((await guard.moderate([])).risky)
        finally:
            await guard.close()

    async def test_adapter_rejects_a_detector_answering_another_risk(self):
        guard = self._guard()
        await guard._client.aclose()
        payload = self._detect_payload(risk='harmful')
        guard._client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json=payload)))
        try:
            assessment = await guard.moderate([{'role': 'user', 'content': 'x'}])
            self.assertIn('answers for', assessment.error)
            self.assertEqual(assessment.status_code, 503)
        finally:
            await guard.close()

    async def test_adapter_rejects_self_contradicting_verdict(self):
        guard = self._guard()
        await guard._client.aclose()
        payload = self._detect_payload(probability=0.2, label='attack')
        guard._client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json=payload)))
        try:
            self.assertIn('contradicts', (await guard.moderate([])).error)
        finally:
            await guard.close()

    async def test_endpoints_must_cover_every_enabled_risk(self):
        self.assertEqual(self._guard().endpoints, {'ipi': 'http://test'})
        self.assertEqual(self._guard('ipi=http://a/').endpoints, {'ipi': 'http://a'})
        with self.assertRaises(ValueError):
            self._guard('ipi=http://a,harmful=http://b')  # harmful 未启用
        with self.assertRaises(ValueError):
            self._guard('harmful=http://b')  # ipi 没有端点

    def test_disabled_weights_are_not_loaded_or_scored(self):
        import torch
        from backend.activation_probe_server import ProbeBank
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root/'model';model.mkdir()
            (model/'config.json').write_text(json.dumps(dict(model_type='qwen3',hidden_size=4096,num_hidden_layers=36)))
            probe = root/'probe';(probe/'indirect_prompt_injection').mkdir(parents=True)
            checkpoint = probe/'indirect_prompt_injection/best_layer_22.pt'
            torch.save(dict(schema='fyh.probe_checkpoint.v2',selected_layer_index=22,
                selected_layer_indices=[22],selected_positions=[-1],input_dim=4096,
                training_config={'feature_normalization':'standard'},
                model_state_dict={'input_mean':torch.zeros(4096),'input_std':torch.ones(4096),
                                  'probe.weight':torch.zeros(4096),'probe.bias':torch.zeros(1)}),checkpoint)
            with patch('backend.activation_probe_server.IPI_SHA256',hashlib.sha256(checkpoint.read_bytes()).hexdigest()), \
                 patch('backend.activation_probe_server.AutoTokenizer.from_pretrained'), \
                 patch('backend.activation_probe_server.Qwen3Checkpoint',side_effect=AssertionError('disabled weight loaded')) as disabled:
                bank = ProbeBank(model, probe, 0.91)
                disabled.assert_not_called()
            self.assertEqual(bank.layers, {'ipi':22})
            self.assertEqual(bank.capture['targets'], [{'layer':22,'site':'block_output'}])
            result = bank.score({22:torch.zeros(4096)},20)
            self.assertEqual(set(result['per_risk']), {'ipi'})
            self.assertEqual(result['enabled_risks'], ['ipi'])
            self.assertEqual(set(result['disabled_risks']), {'harmful','prompt_leakage'})
            self.assertFalse(result['overall'])
            bank.ipi['probe.bias'][0] = 10
            self.assertTrue(bank.score({22:torch.zeros(4096)},20)['overall'])
