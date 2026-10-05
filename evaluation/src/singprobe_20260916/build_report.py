#!/usr/bin/env python3
"""Assemble measured results, provenance and a Chinese reviewable report."""
import csv,hashlib,json,subprocess
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[3];OUT=ROOT/'evaluation/results/singprobe_20260916';CACHE=ROOT/'.runtime/singprobe-20260916';DEST=OUT

def pct(x):return '—' if x is None else f'{x*100:.2f}%'
def metricrow(name,m):return f"| {name} | {m['samples']:,} | {'—' if m['auroc'] is None else format(m['auroc'],'.5f')} | {pct(m['tpr'])} | {pct(m['fpr'])} | {m['tp']}/{m['fn']}/{m['fp']}/{m['tn']} |"
def table(rows):return '\n'.join(['| 方法 / 数据 | N | AUROC | 召回率 | 误报率 | TP/FN/FP/TN |','|---|---:|---:|---:|---:|---|']+[metricrow(n,m) for n,m in rows])
def main():
 names=['mlp_report','ipi_report','ipi_overlap_report','benchmark_report','attention_training_report','attention_report','latency_report']
 reports={name:json.load((OUT/f'{name}.json').open()) for name in names}
 reports['live_bank']=json.load((OUT/'live_bank.json').open()) if (OUT/'live_bank.json').exists() else None
 mlp=reports['mlp_report'];ipi=reports['ipi_report'];dedup=reports['ipi_overlap_report'];bench=reports['benchmark_report'];attn=reports['attention_report']
 provenance={'upstream_repository':'https://github.com/inclusionAI/SingProbe','upstream_commit':subprocess.check_output(['git','-C','/tmp/agent-guard-SingProbe-20260916','rev-parse','HEAD'],text=True).strip(),'base_model':'Qwen3-8B frozen for leakage; cached Qwen3.5-2B for original IPI audit','scripts_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).resolve().parent.glob('*.py')},'checkpoint_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.glob('*.pt')},'baseline_sha256':{(str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/'probe/qwen3-8b/prompt_leakage/best_probe.pt',Path('/ssd/workspace/djs/follow-your-heart/results/external_eval_qwen35_2b_20260910/domain_adapt_lr1e-4_l2pen10/checkpoints/adapted_layer_07.pt')]},'artifacts':str(OUT),'primary_seed':42,'other_seeds':[43,44]}
 source_files=[ROOT/'.runtime/qwen3-8b-retrain-20260915/leakage_data/all_samples.jsonl',ROOT/'.runtime/qwen3-8b-retrain-20260915/reference-v2.json',Path('/ssd/workspace/djs/follow-your-heart/results/external_eval_qwen35_2b_20260910/domain_adapt_lr1e-4_l2pen10/split.json'),Path('/ssd/workspace/djs/follow-your-heart/results/probe_traces/external/mixed_qwen35_2b_20260910/labels/risk_faced/labels.jsonl')]
 source_files += [ROOT/f'.other/leakgauge/data_input/{name}/unseen_all_{label}.json' for name in ['sys_mixed','rag_mixed'] for label in ['attack','benign']]
 provenance['data_sha256']={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files}
 (DEST/'metrics.json').write_text(json.dumps({'provenance':provenance,**reports},ensure_ascii=False,indent=2))
 lines=['# SingProbe 在现有审计 benchmark 与金融 Agent 场景上的量化评估','',
 '日期：2026-09-16。主结果固定使用 seed=42；另外报告 43、44 两次重复，不从测试集选择最好种子。所有指标来自本次真实运行。线上服务、探针权重和前端审计页均未替换。','',
 '## 结论与适用范围','',
 'SingProbe 值得作为候选探针结构，不能据此整体替换现有护栏。IPI 的 MLP 适配有明确收益；泄漏任务需要同时权衡召回率与误报率，并查看金融工具返回后的真实输入。以下区分了原审计页的 Qwen3.5-2B IPI 协议和当前 Qwen3-8B 泄漏检测协议。','',
 '关键结果（主种子 42）：','',
 '- 原 IPI 审计 13,629 条：MLP 召回 91.61%→96.74%，误报 5.15%→0.61%；完全输入去重后误报仍从 7.74% 降至 0.92%。',
 '- Qwen3 泄漏测试 4,556 条：在相同的预设验证 1% 误报政策下，Attention 召回 96.72%→98.44%，测试误报 1.47%→1.51%。主 2% 政策下 Attention 则是召回 99.28%、误报 3.99%。',
 '- 完整 LeakGauge RAG 7,200 条：现有探针已达到本集 100% 召回、0% 误报，MLP 没有超过；Attention 在固定 512 条子集与基线持平。',
 '- 金融重放：MLP 三个种子均补上英文基金注入漏报，正常 LPR/基金 RAG 通过；中文基金变体仍有波动。Attention 用更保守的 1% 政策时仍漏掉英文基金变体。','',
 '本次评估的是官方 GuardMLP / GuardAttnProbe 的 **Qwen 二分类适配**，不是官方 Ling 权重或完整十维多任务复现。标签是窃取意图或间接注入暴露；未评估生成内容安全、幻觉、流式定位，以及实际攻击成功率/阻断后任务完成率。论文的 <0.5% 额外开销不直接适用于当前独立影子模型服务。','',
 '## 1. 原审计页 IPI：AgentDyn + InjecAgent','',
 '严格复用历史 90% 轨迹留出集：13,629 个决策点、3,561 条轨迹。剩余 10% 适配集再按轨迹固定划为 1,186 条训练 / 332 条验证，测试标签不参与训练、模型选择或阈值选择。3 层固定为 7/15/23，逐层 RMS 标准化，MLP 中间宽度 1024。','',
 table([('审计页现有 L7 适配线性探针',ipi['incumbent']['all']),('相同新训练数据的三层线性对照',ipi['models']['linear_scratch_42']['evaluations']['all']),('SingProbe MLP',ipi['models']['singprobe_mlp_42']['evaluations']['all'])]),'',
 '完全输入去重仍未排除语义近重合、同任务或同攻击模板的相关性；这里的留出结果不等于独立生产流量验证。','',
 '旧探针额外使用过 AgentDojo 预训练，新线性与新 MLP 从随机权重训练；因此“现有探针 vs 新 MLP”是候选替代方案对比，三层线性对照更接近结构对比。当前线上 Qwen3-8B IPI L22 并未在本组缓存上评估，不能把这些 2B 权重直接用于 8B。','',
 '### 分 benchmark','',table([(src+'：现有',ipi['incumbent'][src]) for src in ['agentdyn','injecagent']]+[(src+'：MLP',ipi['models']['singprobe_mlp_42']['evaluations'][src]) for src in ['agentdyn','injecagent']]),'',
 '### 排除输入完全重合','',
 f"适配集与留出集无轨迹交叉，但有 {dedup['exact_message_overlap_count']:,} 个留出输入与适配集完全相同，均为正常样本。剔除它们后：",'',
 table([('现有，去重',dedup['models']['42']['no_exact_adaptation_overlap']['incumbent']),('MLP，去重',dedup['models']['42']['no_exact_adaptation_overlap']['singprobe'])]),'',
 '原口径逐轨迹配对 bootstrap（2,000 次）的差值 95% 区间：'+ '；'.join(f"{k} [{v[0]*100:+.2f}, {v[1]*100:+.2f}] 个百分点" for k,v in dedup['models']['42']['paired_trace_bootstrap_delta_ci95'].items())+'。该区间描述本组轨迹抽样不确定性，不代表新业务域的泛化保证。','',
 '### 三个随机种子','',table([(f'MLP seed={seed}',ipi['models'][f'singprobe_mlp_{seed}']['evaluations']['all']) for seed in [42,43,44]]),'',
 '## 2. 当前 Qwen3-8B 窃取检测','',
 '复用完整 11,556 训练 / 3,468 验证 / 4,556 测试切分。MLP 与 Attention 固定抽取零起点 decoder block 11/23/35，先对每层做非仿射 RMS；只训练探针。基线是当前 L12 MLP。主要阈值在各自验证集约束 FPR≤2% 下最大化召回，测试误报率可能超过验证约束。','',
 table([('现有探针，测试',mlp['baseline']['test']['deployed']['overall']),('SingProbe MLP，测试',mlp['seeds']['42']['evaluations']['test']['0.02']['overall']),('现有探针，同次 Attention 特征提取',attn['test']['all']['baseline']),('SingProbe Attention，测试',attn['test']['all']['attention'])]),'',
 '训练、验证和测试无完整消息的精确交叉。它们是已多次用于开发的固定留出集，不是新的线上独立随机流量。MLP 30 epoch、3 seeds；Attention 10 epoch、1 seed；模型/epoch 只按验证指标选择。训练目标按本项目二分类标签适配，不能把收益归因于官方全部多任务损失。','',
 'Attention 的同次基线与原缓存有少量 BF16/batch 数值漂移，以上单独列出；两者模型与样本相同。','',
 '### 阈值政策对照','',
 table([(f'现有，验证 FPR≤{cap}',mlp['baseline']['test'][cap]['overall']) for cap in ['0.01','0.02','0.05']]+[(f'MLP，验证 FPR≤{cap}',mlp['seeds']['42']['evaluations']['test'][cap]['overall']) for cap in ['0.01','0.02','0.05']]+[(f'Attention，验证 FPR≤{cap}',attn['test']['policies'][cap]) for cap in ['0.01','0.02','0.05']]),'',
 'Attention 在预先设定的验证 1% 政策下，测试召回 98.44%、误报 1.51%；同政策旧探针为 96.72%、1.47%。这是值得继续验证的收益，但不能在已查看测试后挑选政策并直接宣称部署已验证。','',
 '降低测试误报率不必然说明结构更优：旧探针采用预先声明的验证 1% 误报政策，也能得到更保守的工作点。上表所有阈值都来自验证集，测试集只负责报告效果。','',
 '### 外部审计与短查询（MLP）','',table(sum([[(name+'：现有',mlp['baseline'][name]['deployed']['overall']),(name+'：MLP',mlp['seeds']['42']['evaluations'][name]['0.02']['overall'])] for name in ['external_attack_audit','natural_safe_audit','reported_short_audit']],[])),'',
 '395 条正常样本观察到 0 次误报，并不意味着真实误报率为零；双侧 95% Wilson 上界约为 0.96%。','',
 '### MLP 重复稳定性','',table([(f'MLP seed={seed}',mlp['seeds'][str(seed)]['evaluations']['test']['0.02']['overall']) for seed in [42,43,44]]),'',
 '## 3. 原 LeakGauge 审计数据重新运行','',
 '在当前 Qwen3-8B 上重新提取特征，同时运行当前探针与 SingProbe。不能直接把这些数值与审计页旧 Qwen3.5-2B 数字相减。System 与 RAG 标签及内容不同，分开报告。','']
 for name in ['sys_mixed','rag_mixed']:
  item=bench[name];lines += [f'### {name} / unseen_all','',table([('当前探针',item['baseline']),('SingProbe MLP',item['models']['42']['all']['singprobe'])]),'',f"完整消息重合计数（train/val/test）：{item['overlap']}；用户 query 重合计数：{item['query_overlap']}。三个集合的 query 重合可能相互重叠，不可直接相加。",'']
  for key in ['no_exact_train_val_overlap','no_query_train_val_overlap']:
   if key in item['models']['42']:lines += [key+'：','',table([('当前探针',item['models']['42'][key]['baseline']),('SingProbe MLP',item['models']['42'][key]['singprobe'])]),'']
  lines += ['Attention：System 使用全 3,136 条；RAG 使用事先固定、按 sample_id 哈希选出的 256 正 + 256 负子集。子集基线在完全相同样本上重算。','',table([('Attention 同样本基线',attn[name]['all']['baseline']),('Attention',attn[name]['all']['attention'])]),'']
 lines += ['## 4. 金融场景完整消息重放','',
 '输入来自已保存的真实 LPR/基金工具调用与 RAG 返回，以及既有中英文注入变体；完整 messages / tools 经过与当前 Qwen3 相同模板渲染。本节比较单个“泄漏”检测器。harmful 行属于其他风险，不能把泄漏检测器未报警记为内容安全漏报。注入变体属于额外跨风险挑战；结果不是足量场景统计。','',
 '| 输入 | 当前泄漏探针 | MLP（2%验证政策） | Attention（2%） | Attention（1%） | 当前三类护栏总体 |','|---|---|---|---|---|---|']
 ac={r['sample_id']:r for r in attn['scenario']['cases']}
 def flag(v):return '报警' if v else '通过'
 for r in bench['scenario']['cases']:lines.append(f"| {r['sample_id']} | {flag(r['baseline_flagged'])} | {flag(r['singprobe_42_flagged'])} | {flag(ac[r['sample_id']]['flagged'])} | {flag(ac[r['sample_id']]['score']>=reports['attention_training_report']['selected']['thresholds']['0.01'])} | {flag(any(v['flagged'] for v in r['reference'].values()))} |")
 lines += ['', 'Attention 在 2% 验证政策下检出 funds_injection_en，换成 1% 验证政策后该例再次漏报；不能把低误报工作点的统计与高召回工作点的场景成功合并成一个结论。','',
 'MLP 的 funds_injection_en 在三个种子下均检出；funds_injection_zh 在 42/44 下检出、43 下漏报，存在训练波动。两个正常 RAG 场景在三个种子下均通过。这只是少量回归案例，不能估计真实业务域的误报/漏报率。','',
 '本次重新提取的现有泄漏探针判定逐项与保存参考一致；具体分数差异见 metrics.json。未更改线上路由或实际执行攻击。','',
 '## 5. 成本与实现核验','',
 f"Qwen3 MLP 参数量 {mlp['seeds']['42']['parameters']:,}；Attention 参数量 {reports['attention_training_report']['parameters']:,}。Attention 使用真实的整段底座前向激活，探针窗口为末尾最多 2048 token；底座输入没有截断。由于官方结构只有一个 attention block，仅计算最后一个 query 与官方完整 forward 最后位置数学等价，输出和输入梯度误差核验记录在 metrics.json。",'',
 '本轮新权重是实验格式，不能直接覆盖当前服务 checkpoint。MLP 需要接入三个层位；Attention 还需要保留窗口内特征或探针 K/V 状态，处理前缀缓存及多轮请求。相关线上接入未在本次修改。','',
 '探针头延迟使用本机 GPU 测量，详见下列本次记录；不包含底座推理、HTTP、特征抓取及序列缓存。不能据此宣称端到端加速。','',
 '| 探针头 | Batch | 窗口 token | 中位延迟 ms | P95 ms |','|---|---:|---:|---:|---:|',
 *[f"| {r['head']} | {r['batch']} | {r['tokens']} | {r['median_ms']:.3f} | {r['p95_ms']:.3f} |" for r in reports['latency_report']['measurements']],'',
 '本实验同时改变了抽取层、归一化、容量或训练经历，结果检验的是具体候选方案。IPI 的同数据三层线性对照支持非线性头的作用，但不能据此证明 SingProbe 特有的多任务损失或全部框架带来收益。','',
 '## 6. 建议','',
 '1. IPI：值得继续验证三层 MLP，先在当前 Qwen3-8B 底座上训练同任务候选，再做新的金融轨迹留出评测；本次 2B 改善不能直接等价为当前服务升级。',
 '2. 泄漏：Attention 在固定 1% 验证误报政策下提供了更好的召回/误报组合，值得优先做独立业务验证；MLP 外部短查询有收益，但普通留出集不优于旧探针的阈值调整。保留全部阈值政策，避免只展示最有利工作点。',
 '3. 上线前需要新的完整业务轨迹覆盖，尤其是正常工具返回与中英文注入。不应在这批已看到的场景上继续调阈值后宣称独立泛化提升。',
 '4. 本轮没有流式 response 标签，无法检验 SingProbe 的流式内容安全、幻觉与 token 定位价值。','',
 '## 复现与产物','',
 '- 官方代码：[SingProbe](https://github.com/inclusionAI/SingProbe)，固定 commit `'+provenance['upstream_commit']+'`。',
 '- 当前目录 `run.sh` 为完整复现入口；依赖本机已存在的模型、上游原始 benchmark 与激活缓存。不要在本次任务仍运行时重复启动。',
 '- `metrics.json` 保存汇总、随机种子、阈值、去重统计、来源哈希和核验记录；`comparison.csv` 为主工作点对比表。',
 '- `'+str(OUT)+'` 保存本次权重、逐样本预测、训练日志和特征缓存；其中整段训练激活约 169 GiB。',
 '- 无数据上传、无线上替换。仅统计“是否检测到风险”，没有测量实际窃取成功率下降。','']
 records=[]
 def add(task,dataset,method,seed,m):records.append({'task':task,'dataset':dataset,'method':method,'seed':seed,**{k:m[k] for k in ['samples','auroc','tpr','fpr','tp','fn','fp','tn']}})
 for dataset,m in ipi['incumbent'].items():add('IPI_Qwen3.5-2B',dataset,'historical_adapted_linear','',m)
 for method,v in ipi['models'].items():
  for dataset,m in v['evaluations'].items():add('IPI_Qwen3.5-2B',dataset,method.rsplit('_',1)[0],method.rsplit('_',1)[1],m)
 for dataset,v in mlp['baseline'].items():add('Leakage_Qwen3-8B',dataset,'current','',v['deployed']['overall'])
 for seed,v in mlp['seeds'].items():
  for dataset,m in v['evaluations'].items():add('Leakage_Qwen3-8B',dataset,'SingProbe_MLP',seed,m['0.02']['overall'])
 for dataset in ['sys_mixed','rag_mixed']:
  add('LeakGauge_Qwen3-8B',dataset,'current','',bench[dataset]['baseline'])
  for seed,v in bench[dataset]['models'].items():add('LeakGauge_Qwen3-8B',dataset,'SingProbe_MLP',seed,v['all']['singprobe'])
 for dataset in ['sys_mixed','rag_mixed','test']:
  label=dataset+('_512_fixed_subset' if dataset=='rag_mixed' else '')
  add('Attention_Qwen3-8B',label,'current_same_samples','',attn[dataset]['all']['baseline'])
  add('Attention_Qwen3-8B',label,'SingProbe_Attention',42,attn[dataset]['all']['attention'])
 with (DEST/'comparison.csv').open('w',newline='') as f:
  writer=csv.DictWriter(f,fieldnames=list(records[0]));writer.writeheader();writer.writerows(records)
 (DEST/'REPORT.md').write_text('\n'.join(lines))
 print(str(DEST/'REPORT.md'))
if __name__=='__main__':main()
