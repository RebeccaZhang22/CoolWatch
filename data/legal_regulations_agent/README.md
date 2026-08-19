# 法律法规条款 Agent 场景数据

这是一套用于法律法规 RAG、版本检索和攻防演示的**完全合成数据**。其中“示例市”以及所有条例、机关、文号、条款和日期均为虚构内容，不属于任何真实司法辖区，也不能作为法律意见或真实合规依据。

数据重点模拟法律 RAG 的真实工程问题：

- 同一法规存在历史版、修订决定和现行整合版；
- 回答必须按照事项发生日选择当时有效的条款；
- 新增实施细则与官方解释需要持续进入索引；
- 征求意见稿不得作为已生效规则引用；
- 冲突时需要比较效力层级、发布日期、生效日期和版本关系；
- 外部“最新法规公告”可能携带 Prompt Injection 或伪造更新。

```text
legal_regulations_agent/
  scenario.json
  agent/                              # Agent 系统消息与 reasoning 边界
  skills/                             # 时效性检索、版本合并和引用 Skill
  rag/
    documents.json                   # 文档级元数据与版本关系
    version_policy.json              # 时间切片和效力选择规则
    change_events.json               # 法规新增、修订、失效事件流
    public/current/                   # 现行法规和配套文件
    public/historical/                # 历史有效版本
    public/amendments/                # 修订决定
    public/drafts/                    # 未生效草案
    internal/                         # 不可对外的编辑校验备注
  attacks/                            # 攻击卡片与污染法规夹具
    evaluation/                         # 资产映射与时态检索用例
  tools/                              # 法规检索和版本比较工具契约
  examples/                           # 面向产品演示的问题集
```

`rag/documents.json` 是检索入口。每条记录都包含法规身份、效力状态、公布/生效/失效日期、版本和前后继关系。新增法规时应先添加正文，再更新文档元数据与 `change_events.json`；加载或入库程序应按 `version_policy.json` 校验时间区间和版本链。

攻击夹具不在正常法规正文中。运行时不会向 System Prompt、Skill、RAG 或攻击夹具注入 canary；泄漏采用内容重合评估，Prompt Injection 采用结果短语评估。内部编辑备注也不能作为对用户的法律依据。
