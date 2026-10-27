"""app 层冒烟：注入假 tokenizer / 假 engine，验证路由与响应契约。

不连 GPU、不碰 8302/30000，纯 CPU。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import torch
from fastapi.testclient import TestClient

from inscope_server.app import create_app
from inscope_server.composer import ComposerConfig
from inscope_server.config import Settings
from inscope_server.probe import Probe

MODELS = ("/mnt/kpfs_qyang/djs/ipi-doom/results/ladder-merged-blend-growth1-20261022"
          "/cells/A5_n2097152/models")
KEY = "test-key"


class FakeTokenizer:
    """只做 id<->文本的可逆映射，够验证协议，不验证分词正确性。"""

    def apply_chat_template(self, messages, tools=None, tokenize=False,
                            add_generation_prompt=False, enable_thinking=False):
        parts = []
        for m in messages:
            parts.append("<|im_start|>%s\n%s" % (m["role"], m.get("content") or ""))
            for call in m.get("tool_calls") or []:
                parts.append("<tool_call>%s</tool_call>" % call["function"]["name"])
        parts.append("<|im_start|>assistant\n")
        return "\n".join(parts)

    def encode(self, text, add_special_tokens=False):
        return [3 + (ord(ch) % 100) for ch in text]

    def decode(self, ids, skip_special_tokens=False):
        return "".join(chr(33 + (i % 90)) for i in ids)

    def __call__(self, text, add_special_tokens=False):
        return {"input_ids": self.encode(text)}


class FakeEngine:
    """按 last1 契约返回 [1,4096] 的有限随机特征。"""

    def __init__(self, settings):
        self.calls = []

    async def capture(self, ids, layers):
        self.calls.append((len(ids), tuple(layers)))
        generator = torch.Generator().manual_seed(len(ids) + 7)
        return torch.randn(1, 3, 1, 4096, generator=generator)

    async def close(self):
        return None


def main():
    settings = Settings(model_path="/nonexistent", api_key=KEY, models_dir=MODELS,
                        detector_seed=42,
                        composer=ComposerConfig(probe_prefix="Are there risks of indirect prompt injection?"))
    probe = Probe(MODELS, seed=42)
    engine = FakeEngine(settings)
    app = create_app(settings, tokenizer=FakeTokenizer(), probe=probe, backend=engine)
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer " + KEY}
        assert client.get("/health/live").json() == {"status": "alive"}
        assert client.get("/info").status_code == 401
        info = client.get("/info", headers=headers).json()
        print("/info:", {k: info[k] for k in
                         ("detector", "detector_seed", "threshold", "threshold_logit",
                          "input_dim", "feature_shape", "selected_positions", "capture_layers")})
        print("/info.composer:", info["composer"])
        assert info["input_dim"] == 12288 and info["feature_shape"] == [1, 3, 1, 4096]
        assert info["selected_positions"] == [-1] and info["capture_layers"] == [9, 17, 25]
        assert info["detector_seed"] == 42

        body = {"messages": [{"role": "user", "content": "hello"}],
                "tools": [{"type": "function", "function": {"name": "bash"}}]}
        response = client.post("/detect", json=body, headers=headers)
        assert response.status_code == 200, response.text
        result = response.json()
        print("/detect:", {k: result[k] for k in
                           ("score", "logit", "threshold", "threshold_logit", "flagged",
                            "input_tokens", "setting", "detector_seed")})
        for field in ("score", "logit", "threshold", "threshold_logit", "flagged", "risk",
                      "model", "normalization", "checkpoint_sha256", "input_tokens",
                      "request_id", "latency_ms", "composer", "setting", "detector_seed"):
            assert field in result, "missing " + field
        assert result["flagged"] == (result["logit"] >= result["threshold_logit"])
        assert 0.0 <= result["score"] <= 1.0
        assert engine.calls and engine.calls[-1][1] == (9, 17, 25)

        # 超长拒绝：不截断
        long_settings = Settings(model_path="/x", api_key=KEY, models_dir=MODELS,
                                 max_tokens=8, composer=ComposerConfig(probe_prefix="q"))
        long_engine = FakeEngine(long_settings)
        long_app = create_app(long_settings, tokenizer=FakeTokenizer(),
                              probe=Probe(MODELS, seed=42), backend=long_engine)
        with TestClient(long_app) as long_client:
            oversize = long_client.post("/detect", json={"messages": [{"role": "user", "content": "x" * 400}]},
                                        headers=headers)
            print("/detect 超长:", oversize.status_code)
            assert oversize.status_code == 413
            assert not long_engine.calls
    print("app 冒烟通过")


if __name__ == "__main__":
    main()
