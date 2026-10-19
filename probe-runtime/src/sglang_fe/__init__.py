"""sglang_fe：基于 sglang 标准组件的 ad-hoc 高吞吐特征提取后端。

设计约束（用户指定）：
- 不改动 .venv-sglang 中的 sglang 0.5.19（零源码修改）；
- 复用 sglang 标准组件：Engine 调度器、ModelRunner、flashinfer 注意力后端、TP 通信、
  官方 forward_hooks 插桩协议（ServerArgs.forward_hooks + hook_manager.register_forward_hooks）；
- 捕获语义与 HF transformers 参考实现（featurize.py）逐层对齐：
  HF hidden_states[k]（k>=1）= 第 k-1 个 decoder layer 的输出；k=0 = embedding 输出。
  因此 hook 挂 model.embed_tokens（k=0）与 model.layers.j（k=j+1）。

组件：
- hooks.py：运行于 scheduler 子进程内的 hook 工厂（root 层绑定 ForwardBatch 元数据，
  层 hook 缓存目标层输出；rank0 落盘 spool 分片）
- extractor.py：主进程驱动（Engine 启动、按 rid 拼装特征、写出 features.npz）
"""
