"""text-modality-only 的 Qwen3.5 加载入口（经 SGLANG_EXTERNAL_MODEL_PACKAGE 标准机制注册）。

Qwen3.5 开源 checkpoint 是多模态包装（架构名 Qwen3_5ForConditionalGeneration），权重键前缀为
model.language_model.* / model.visual.* / mtp.*。本包以同名类**顶替** sglang 注册表中该架构的
VL 包装器实现（registry.register(external_pkg, overwrite=True) 是官方语义），类本身子类化 sglang
文本 LM，仅改 load_weights：剥 model.language_model. 前缀、丢弃 visual/mtp 键。
效果：Engine 正常按 checkpoint 架构名加载，但得到的是纯文本模型（零视觉塔、零 VL 前向路径）。
注意：本目录必须是包（registry 用 pkgutil 扫描子模块收集 EntryClass）。
"""
from sglang.srt.models.qwen3_5_text import Qwen3_5ForCausalLM as _Qwen3_5TextLM


class Qwen3_5ForConditionalGeneration(_Qwen3_5TextLM):
    def load_weights(self, weights):
        def _remap(weights):
            for name, w in weights:
                if name.startswith(("model.visual.", "mtp.")):
                    continue
                if name.startswith("model.language_model."):
                    name = "model." + name[len("model.language_model."):]
                yield name, w

        return super().load_weights(_remap(weights))


EntryClass = [Qwen3_5ForConditionalGeneration]
