# 训练入口

训练脚本在 `../probe/src/`，训练/验证文本在 `data/<risk>/`，测试集在 `../evaluation/dataset/benchmark/`。详见 `data/README.md` 的标签版本与数据缺失说明。

从仓库根目录运行（需要原训练环境的 torch、transformers 等依赖及 GPU）：

```bash
python probe/src/extract_qwen3_activations.py --model-path /path/to/Qwen3-8B --dataset train/data/prompt_leakage --output .runtime/new-leakage-features
python probe/src/train_qwen3_probe.py --task prompt_leakage --features .runtime/new-leakage-features --dataset train/data/prompt_leakage --output .runtime/new-leakage-probe
```

激活提取支持可选 `--evaluation-dataset evaluation/dataset/benchmark/prompt_leakage/probe_holdout/test.jsonl`，测试特征独立写入 `heldout_test`，不参与主训练特征。历史准备脚本仍能复现旧数据；`DATA_PREPARATION_LEGACY.md` 为历史说明，不是当前目录入口。训练产物经独立评估后再决定部署；目录整理不自动替换线上 probe。
