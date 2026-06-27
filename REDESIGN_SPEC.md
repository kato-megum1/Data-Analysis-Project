# 数据分析 Agent 集群 —— 重构设计文档 (v2)

> 目标：把"每个 agent 既算又说"的混乱结构，重构为
> **确定性 skill（纯代码）算事实 → 少量 LLM agent 做判断与语言**，
> 并用统一的 `state` 对象 + fact 锚定（grounding）解决幻觉、JSON 解析失败、措辞不一致、慢且贵的问题。

---

## 0. 当前问题（重构动机）

| 问题 | 现状 | 后果 |
|------|------|------|
| 该用代码的用了 LLM | 每个指标的趋势/异动/归因都单独调一次 LLM 解读 | 慢、贵、措辞前后矛盾 |
| LLM 任务过载 | `AnalystAgent` 一个 prompt 同时写报告+出JSON+判断评审 | 输出质量差、JSON 频繁解析失败 |
| 无 grounding | LLM 拿 summary 自由发挥，无"引用哪个数字"约束 | 数字幻觉、对不上 |
| 辩论产出不可用 | data/biz review + rebuttal 三轮自由文本 | 下游无法结构化消费，贵 |
| 参数传递混乱 | `synthesize()` 传 7 个位置参数 | 难维护、难测试 |

---

## 1. 核心原则

1. **能算出唯一正确答案的 → skill（纯代码）**：可验证、可复现、零成本、零幻觉。
2. **需要语言/判断/假设/建议的 → agent（LLM）**：但**只能基于已经算好的数字**。
3. **`facts` 是唯一事实来源**：所有 LLM 步骤都从 `facts` 读，结论必须用 `refs` 指回具体 fact id。
4. **LLM 步骤单一职责 + 结构化输出 + 失败降级**。

---

## 2. 流水线总览

```
[skill] 1. Schema 解析
[skill] 2. ETL 加载/清洗/聚合
[skill] 3. 指标计算（派生/围栏/描述统计）
[skill] 4. 数据画像 Profiler
[skill] 5. 趋势计算
[skill] 6. 异动检测
[skill] 7. 归因分解
          └─── 产出 state.facts（全部可验证数字事实）
[agent] 8. Interpreter   —— 一次调用，把 facts 翻译成结构化 insights
[agent] 9. Critic        —— 一次 grounded 审查，输出结构化修订
[agent] 10. Report       —— 把 facts+insights 写成 Markdown/HTML
[agent] 11. QA           —— 基于 facts 上下文问答（独立于离线流水线）
```

LLM 调用次数：**从"每指标 N 次 + 3 轮辩论"降到固定 3 次**（Interpreter / Critic / Report），QA 按需。

---

## 3. 数据契约：统一 `state` 对象

每一步签名统一为 `def run(state: dict) -> dict`，只读自己需要的键、只写自己负责的键。

```python
state = {
  # ---------- skill 区：确定性产出 ----------
  "schema": {
    "dimensions": [{"name": "地区", "display_name": "地区", "idx": 1}],
    "metrics":    [{"name": "销售额", "display_name": "销售额", "agg": "sum", "idx": 5}],
    "formulas":   [{"name": "利润", "expression": "销售额 - 成本"}],
    "fences":     [{"name": "利润率", "min": 0.1, "max": 0.8}],
    "anomaly_thresholds": {"销售额": {"down": 20, "up": 30}},
    "analysis_metrics": ["销售额", "成本", "利润", "利润率"],
    "drill_order": ["地区", "品类", "渠道"]
  },

  "data": {
    "df": "<内存中的 DataFrame，不进 JSON、不进 LLM>",
    "summary": {"rows": 1200, "columns": 7,
                "date_range": ["2026-01-01", "2026-05-31"],
                "granularity": "day"}
  },

  "facts": {                              # ★ 唯一事实来源，全部可单测
    "metrics": {                          # 描述统计
      "销售额": {"mean": 12000, "median": 11800, "std": 2300,
                "min": 6000, "max": 19000, "latest": 9500}
    },
    "fence_violations": [
      {"id": "f_1", "metric": "利润率", "value": 0.05,
       "bound": "min", "limit": 0.1, "period": "2026-05"}
    ],
    "trends": [
      {"id": "t_销售额", "metric": "销售额",
       "series": [...], "mom": -21.0, "yoy": -8.0,
       "slope": -120.5, "overall_trend": "down",
       "seasonality": "weekly"}
    ],
    "anomalies": [
      {"id": "a_1", "metric": "销售额", "period": "2026-05",
       "z": -2.4, "change_pct": -21.0, "threshold_hit": "down",
       "severity": "high", "value": 9500, "baseline": 12000}
    ],
    "cross_anomalies": [
      {"id": "x_1", "type": "direction_divergence",
       "metrics": ["销售额", "订单量"], "severity": "high",
       "detail": "销售额-21% 与 订单量+5% 背离"}
    ],
    "dimension_anomalies": [
      {"id": "d_1", "dimension": "地区", "slice_value": "华东",
       "metric": "销售额", "z": -2.1, "slice_mean": 6000,
       "overall_mean": 12000}
    ],
    "attributions": [
      {"id": "attr_1", "metric": "利润", "method": "LMDI",
       "expression": "销售额 - 成本",
       "contributions": [{"factor": "成本", "pct": 68},
                         {"factor": "销售额", "pct": 32}]}
    ]
  },

  # ---------- agent 区：LLM 产出 ----------
  "insights": [
    {"id": "ins_1", "refs": ["a_1", "attr_1"],     # ★ grounding：引用 fact id
     "claim": "5月销售额环比下降21%，主因成本端上升挤压利润",
     "hypotheses": ["促销退坡", "华东区缺货"],
     "confidence": "中高",
     "recommendation": "核查华东区库存与5月促销排期"}
  ],

  "review": {                                       # 单次 grounded critic 产出
    "verdicts": [
      {"insight_id": "ins_1", "status": "revise",   # pass | revise | reject
       "issue": "z=-2.4 仅 4 期窗口，置信度宜降为中",
       "suggested_confidence": "中"}
    ],
    "summary": "1 条修订，0 条驳回"
  },

  "report_md": "...",                               # Report 产出（Markdown）
  "errors": []                                      # 各步降级/异常记录
}
```

**关键约束（代码侧强制）**：
- 每条 `insight.refs` 里的 id 必须在 `facts` 中存在，否则该条 insight 被丢弃并记入 `errors`。
- `insight` 中出现的数字应能在所引用 fact 中找到（可做软校验：抽取数字比对，偏差超阈值则标记）。

---

## 4. skill（纯代码步骤）规格

> 全部**不调用 LLM**。每个都应有独立单元测试（给定输入 df → 断言 facts 输出）。

| 步骤 | 模块（建议） | 输入 | 输出键 | 算法要点 |
|------|------|------|--------|----------|
| 1 Schema | `pipeline/schema.py` | config | `state.schema` | 解析维度/指标/公式/围栏/阈值；展开 `analysis_metrics` |
| 2 ETL | `pipeline/etl.py` | file+schema | `state.data` | 读 xlsx/csv → 类型推断 → 缺失处理 → 按维度+时间聚合 |
| 3 指标 | `pipeline/metric.py` | df+schema | `facts.metrics` `facts.fence_violations` | `formula_parser` 算派生指标；围栏越界判断；描述统计 |
| 4 Profiler | `pipeline/profiler.py` | df | `facts.profile` | 缺失率、时间粒度、分布、维度基数 |
| 5 趋势 | `pipeline/trend.py` | df | `facts.trends` | 环比 mom / 同比 yoy / 线性 slope / 季节性判定 |
| 6 异动 | `pipeline/anomaly.py` | df | `facts.anomalies` 等 | z-score(窗口) + 阈值双验证 + 跨指标背离 + 维度切片 |
| 7 归因 | `pipeline/attribution.py` | df | `facts.attributions` | 加法分解 / LMDI 乘法分解 + 维度下钻 |

> 现有 `utils/anomaly_detector.py` `utils/attribution.py` `utils/formula_parser.py` 的**数学逻辑保留**，只是把"调 LLM 解读"那段从 `*_analysis_agent.py` 里**删掉**，纯计算下沉到这里。

---

## 5. agent（LLM 步骤）规格

所有 agent 遵守统一模板：

```python
class BaseLLMAgent:
    """单一职责 + 结构化输出 + grounding 校验 + 失败降级"""
    def run(self, state: dict) -> dict:
        payload = self._build_payload(state)        # 只喂 facts 的精简结构
        try:
            raw = self.llm.structured_call(          # 优先 function calling / json schema
                system=self.SYSTEM, user=payload,
                schema=self.OUTPUT_SCHEMA, temperature=0.2)
            out = self._validate(raw, state)         # schema 校验 + refs 存在性校验
        except Exception as e:
            out = self._fallback(state, e)           # 用 facts 套模板的确定性兜底
            state["errors"].append({"step": self.NAME, "error": str(e)})
        return self._write(state, out)
```

### 5.1 Interpreter Agent（步骤 8）

- **职责**：把全部 `facts` 一次性翻译成结构化 `insights`。**不写长报告**。
- **输入 payload**：`facts`（裁剪后的精简版）+ `schema.business_context` + 字段说明。
- **输出 schema**：
```json
{ "insights": [
  { "refs": ["fact_id", ...],
    "claim": "string ≤ 60字",
    "hypotheses": ["string", ...],
    "confidence": "高|中高|中|中低|低",
    "recommendation": "string ≤ 40字" } ] }
```
- **System prompt 要点**：
  > 你是资深数据分析师。下面是已经算好的、确定无误的数字事实(facts)。
  > 你的唯一任务：为值得关注的 fact 生成结构化洞察。
  > 硬约束：① 每条洞察必须在 refs 中列出它依据的 fact id；
  > ② 不得编造 facts 中不存在的数字；③ 只输出给定 JSON schema，无多余文字。

### 5.2 Critic Agent（步骤 9，单次 grounded 审查）

> 替代原 data_reviewer + biz_reviewer + rebuttal_agent 三轮。

- **职责**：对每条 insight 做一次"数据+业务"双视角校验，输出**结构化裁决**（不是自由文本辩论）。
- **输入**：`facts` + `insights`。
- **输出 schema**：
```json
{ "verdicts": [
  { "insight_id": "ins_1",
    "status": "pass|revise|reject",
    "issue": "string（仅当非 pass）",
    "suggested_confidence": "高|中高|中|中低|低" } ],
  "summary": "string" }
```
- **应用规则（代码侧，非 LLM）**：
  - `pass` → 保留；`revise` → 按 `suggested_confidence` 调整、issue 记入 insight；`reject` → 移除该 insight。
- **System prompt 要点**：
  > 你同时扮演数据科学家与零售业务专家。逐条审查 insights 是否被 facts 支撑、
  > 统计是否成立（如 z-score 的窗口/样本量）、是否把相关误判为因果、是否忽略季节/竞争因素。
  > 只输出结构化裁决，正确的就 pass，不要写解释性长文。

### 5.3 Report Agent（步骤 10）

- **职责**：把 `facts` + 通过审查后的 `insights` 组装成 Markdown 报告（再由现有前端/ECharts 渲染）。
- **输入**：`facts` + `insights`(final) + `schema`。
- **输出**：`report_md`（纯 Markdown 字符串；图表数据由代码从 facts 直接生成，不让 LLM 编数字）。
- **要点**：固定章节（核心摘要 / 趋势 / 异动 / 归因 / 围栏 / 建议）；关键数字一律来自 facts 注入，LLM 只负责行文。

### 5.4 QA Agent（步骤 11，独立）

- **职责**：基于离线产出的 `facts` + `insights` + `report_md` 上下文回答追问。
- 复用 `chat_context.py`，但上下文来源改为 `facts`（结构化）而非报告全文，降低幻觉。

---

## 6. 目录改造建议

```
pipeline/                 # ← 新增：确定性 skill 步骤（无 LLM）
  schema.py  etl.py  metric.py  profiler.py
  trend.py   anomaly.py  attribution.py
  runner.py               # 顺序执行 skill 步骤，产出 state.facts
agents/                   # ← 精简：只剩 LLM agent
  base.py                 # BaseLLMAgent
  interpreter.py
  critic.py
  report.py
  qa.py
utils/                    # 保留数学工具
  anomaly_detector.py  attribution.py  formula_parser.py  llm_client.py
state.py                  # state 结构定义 + 校验函数（refs 存在性等）
```

**删除/合并**：`analyst_agent.py`、`data_reviewer.py`、`biz_reviewer.py`、`rebuttal_agent.py`、`review_orchestrator.py`、`trend/anomaly/attribution_analysis_agent.py` 中的 LLM 部分。

---

## 7. llm_client 调整

- 新增 `structured_call(system, user, schema, temperature)`：优先用 DeepSeek 的 JSON 模式 / function calling，返回已解析 dict；解析失败自动重试一次"修复为合法 JSON"。
- 删除 `analyze_trends` / `analyze_anomaly` / `analyze_attribution` / `data_review` / `biz_review` / `rebuttal_response` 这些逐场景方法（逻辑被 Interpreter/Critic 取代）。
- 保留 `chat` / `stream_chat`（QA 用）。

---

## 8. 验收标准

1. 跑通 `data/test_retail.xlsx`：`state.facts` 全部由代码产出，可被单测断言。
2. 每条 `insight.refs` 都能在 facts 中命中（CI 校验）。
3. 全流程 LLM 调用固定 3 次（Interpreter/Critic/Report），可在日志计数。
4. 断网/LLM 失败时，流水线仍能产出"事实+模板兜底"报告，不崩溃。
5. 报告中的数字与 facts 完全一致（抽样比对）。

---

## 9. 实施顺序（建议）

1. 落地 `state.py` + `pipeline/` 七个 skill 步骤 + `runner.py`，先让 `facts` 跑通（不接 LLM）。
2. 写 skill 单测，锚定 facts 正确性。
3. 接入 `BaseLLMAgent` + Interpreter，端到端跑通到 insights。
4. 加 Critic（单次 grounded）+ 应用规则。
5. 接 Report，替换 `main.py` / `server.py` 编排。
6. 迁移 QA，清理废弃 agent 文件。
```
