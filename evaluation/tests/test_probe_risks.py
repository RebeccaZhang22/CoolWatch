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
    def test_selection_validation(self):
        self.assertEqual(parse_enabled_risks(), ('ipi',))
        self.assertEqual(set(parse_enabled_risks('ipi,harmful')), {'ipi','harmful'})
        for invalid in ['', 'ipi,typo', 'ipi,']:
            with self.assertRaises(ValueError): parse_enabled_risks(invalid)

    async def test_adapter_only_accepts_enabled_results(self):
        settings = SimpleNamespace(probe_bank_base_url='http://test', activation_probe_timeout_seconds=10,
                                   customer_agent_shadow_model='qwen3-8b', probe_bank_enabled_risks='ipi')
        guard = ProbeBankGuard(settings)
        await guard._client.aclose()
        payload = dict(detector_model='qwen3-8b', bank_version='test-bank', input_tokens=20,
                       per_risk={'ipi':dict(flagged=False,score=0.1,threshold=0.91)}, enabled_risks=['ipi'])
        guard._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200,json=payload)))
        try:
            clean = await guard.moderate([{'role':'user','content':'test'}])
            self.assertIsNone(clean.error)
            self.assertFalse(clean.risky)
            payload['per_risk']['ipi'].update(flagged=True,score=0.99)
            self.assertTrue((await guard.moderate([])).risky)
            payload['per_risk']['harmful'] = dict(flagged=True,score=0.99,threshold=0.8)
            self.assertIsNotNone((await guard.moderate([])).error)
            payload['per_risk'] = {}
            self.assertIsNotNone((await guard.moderate([])).error)
        finally:
            await guard.close()

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
