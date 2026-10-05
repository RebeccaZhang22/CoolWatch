# 场景数据

这里只保留运行时场景：`financial_agent/`（金融知识问答、RAG、工具、演示 query）和 `ipi_replay/`（间接注入回放）。场景内 `evaluation/` 的 protected_assets 等属于运行时防护配置。

训练文本见 `../train/data/`；离线测试见 `../evaluation/dataset/`；judge 脚本见 `../evaluation/src/`；审计结果见 `../evaluation/results/`。历史停用场景保存在 `../aborted/data/`。
