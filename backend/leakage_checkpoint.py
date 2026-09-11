"""Strict CPU scorer for the supplied unified Qwen3.5-2B leakage MLP."""
import hashlib
import math
from pathlib import Path

import torch
from torch import nn


class LeakageCheckpoint:
    def __init__(self, path, model_path):
        path = Path(path)
        self.sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        ck = torch.load(path, map_location='cpu', weights_only=True)
        contract = ck['extraction_contract']
        if (ck['schema'] != 'perspective_watch.activation_probe_checkpoint.v2'
                or ck['classifier_type'] != 'multilayer_mlp'
                or ck['selected_layers'] != [14]
                or ck['feature_layer_indices'] != [14]
                or ck['feature_type'] != 'residual' or ck['feature_transform'] != 'raw'
                or contract['position'] != 'last_nonpad_token_of_full_no_thinking_generation_prompt'
                or contract['layer_semantics'] != 'zero_based_decoder_block_output_before_final_RMSNorm'
                or contract['hidden_size'] != 2048 or contract['num_layers'] != 24
                or contract['model_config_sha256'] != hashlib.sha256((Path(model_path) / 'config.json').read_bytes()).hexdigest()):
            raise ValueError('Unsupported leakage checkpoint/extraction contract')
        arch = ck['architecture']
        if (arch['input_size'] != 2048 or arch['hidden_sizes'] != [64, 32]
                or arch['activation'] != 'gelu' or arch['input_layer_norm'] is not True):
            raise ValueError('Unsupported leakage MLP architecture')
        self.mean, self.std = ck['mean'].float(), ck['std'].float()
        if self.mean.shape != (1, 2048) or self.std.shape != (1, 2048):
            raise ValueError('Invalid leakage normalization shape')
        modules = [nn.LayerNorm(2048, elementwise_affine=False)]
        previous = 2048
        for size in arch['hidden_sizes']:
            modules.extend([nn.Linear(previous, size), nn.GELU(), nn.Dropout(arch['dropout'])])
            previous = size
        modules.append(nn.Linear(previous, 1))
        self.model = nn.Module()
        self.model.network = nn.Sequential(*modules)
        self.model.load_state_dict(ck['state_dict'], strict=True)
        self.model.eval()
        if any(not torch.isfinite(v).all() for v in [self.mean, self.std, *self.model.parameters()]) or not (self.std > 0).all():
            raise ValueError('Non-finite leakage parameters')
        self.logit_threshold = float(ck['threshold'])
        self.threshold = float(ck['probability_threshold'])
        if (ck['prediction_rule'] != 'logit >= threshold' or not math.isfinite(self.logit_threshold)
                or not 0 < self.threshold < 1
                or abs(self.threshold - torch.sigmoid(torch.tensor(self.logit_threshold, dtype=torch.float64)).item()) > 1e-10):
            raise ValueError('Invalid leakage threshold')

    @torch.inference_mode()
    def score(self, hidden):
        x = torch.as_tensor(hidden).float().reshape(1, 2048)
        logit = self.model.network((x - self.mean) / self.std.clamp_min(1e-5)).item()
        if not math.isfinite(logit):
            raise ValueError('Non-finite leakage logit')
        return torch.sigmoid(torch.tensor(logit, dtype=torch.float64)).item(), logit >= self.logit_threshold
