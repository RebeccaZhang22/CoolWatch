"""Validated Qwen3-8B linear/MLP checkpoints sharing one extraction contract."""
import hashlib
import math
from pathlib import Path

import torch
from torch import nn


class Qwen3Checkpoint:
    def __init__(self, path, model_path, risk):
        path = Path(path)
        self.sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        ck = torch.load(path, map_location='cpu', weights_only=True)
        config = Path(model_path) / 'config.json'
        contract = ck['extraction_contract']
        self.layer = ck['selected_layers'][0]
        if (ck['schema'] != 'perspective_watch.activation_probe_checkpoint.v2'
                or ck['task'] != risk or ck['selected_layers'] != [self.layer]
                or ck['feature_layer_indices'] != [self.layer] or not 0 <= self.layer < 36
                or ck['feature_type'] != 'residual' or ck['feature_transform'] != 'raw'
                or contract['position'] != 'last_nonpad_token_of_full_thinking_generation_prompt'
                or contract['layer_semantics'] != 'zero_based_decoder_block_output_before_final_RMSNorm'
                or contract['hidden_size'] != 4096 or contract['num_layers'] != 36
                or contract['model_config_sha256'] != hashlib.sha256(config.read_bytes()).hexdigest()):
            raise ValueError('Unsupported Qwen3 checkpoint/extraction contract')
        self.mean, self.std = ck['mean'].float(), ck['std'].float()
        if self.mean.shape != (1, 4096) or self.std.shape != (1, 4096):
            raise ValueError('Invalid probe normalization shape')
        self.classifier_type = ck['classifier_type']
        if self.classifier_type == 'linear':
            self.model = nn.Linear(4096, 1)
            self.model.weight.data.copy_(ck['weight'].reshape(1,4096))
            self.model.bias.data.copy_(ck['bias'].reshape(1))
        elif self.classifier_type == 'multilayer_mlp':
            arch = ck['architecture']
            if (arch['input_size'] != 4096 or arch['activation'] != 'gelu'
                    or arch['input_layer_norm'] is not True or arch['hidden_sizes'] not in ([64,32],[128,32])):
                raise ValueError('Unsupported probe MLP architecture')
            modules = [nn.LayerNorm(4096, elementwise_affine=False)]
            previous = 4096
            for size in arch['hidden_sizes']:
                modules.extend([nn.Linear(previous, size), nn.GELU(), nn.Dropout(arch['dropout'])])
                previous = size
            modules.append(nn.Linear(previous, 1))
            self.model = nn.Sequential(*modules)
            self.model.load_state_dict({k.removeprefix('network.'):v for k,v in ck['state_dict'].items()}, strict=True)
        else:
            raise ValueError('Unsupported classifier')
        self.model.eval()
        if any(not torch.isfinite(v).all() for v in [self.mean,self.std,*self.model.parameters()]) or not (self.std > 0).all():
            raise ValueError('Invalid probe parameters')
        self.logit_threshold = float(ck['threshold'])
        self.threshold = float(ck['probability_threshold'])
        if (ck['prediction_rule'] != 'logit >= threshold' or not math.isfinite(self.logit_threshold)
                or not 0 < self.threshold < 1
                or abs(self.threshold - torch.sigmoid(torch.tensor(self.logit_threshold,dtype=torch.float64)).item()) > 1e-10):
            raise ValueError('Invalid probe threshold')

    @torch.inference_mode()
    def score(self, hidden):
        x = torch.as_tensor(hidden).float().reshape(1,4096)
        logit = self.model((x-self.mean)/self.std.clamp_min(1e-5)).item()
        if not math.isfinite(logit):
            raise ValueError('Non-finite probe score')
        return torch.sigmoid(torch.tensor(logit,dtype=torch.float64)).item(), logit >= self.logit_threshold
