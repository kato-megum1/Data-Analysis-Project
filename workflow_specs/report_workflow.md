# Data Analysis Report Workflow

Use this workflow when generating an analysis report from configured one-table data.

## Architecture

The application is split into three logical lines:

1. **A0 Dataset Profiler**: inspect columns, samples, types, row count, candidate dimensions, candidate metrics, and time fields.
2. **B Analysis Intent Agent**: infer the user analysis goal and select analysis methods such as trend, anomaly, cross analysis, attribution, rule check, and dimension drill-down.
3. **A1/C Analysis Config + Planner**: use the user intent and confirmed config to create an executable analysis plan, then compute facts and generate the report.

## Report Principles

- Do not dump raw JSON in the report body.
- The report must be conclusion-first.
- Every key conclusion must cite one or more evidence tables, such as `[Data A1]`.
- Every number in conclusions must come from facts or evidence tables.
- If the data cannot prove causality, use cautious language such as "初步判断" or "需要补充数据验证".
- Use tables as evidence and appendix, not as a substitute for business interpretation.
- Mention data limitations when important fields are missing.

## Required Report Structure

1. Cover and scope
2. One-page conclusions
3. Key finding branches
4. Trend and anomaly evidence
5. Attribution and drill-down
6. Action recommendations
7. Appendix evidence tables

## Analysis Methods

- `baseline_comparison`: compare latest period with previous period or overall baseline.
- `trend_analysis`: analyze metric direction and recent change.
- `anomaly_detection`: find abnormal spikes, drops, or threshold violations.
- `cross_analysis`: compare related metrics for divergence or reinforcing movement.
- `dimension_drilldown`: locate abnormal or high-contribution segments.
- `attribution_analysis`: explain change using available drivers.
- `rule_check`: check fences, business thresholds, and metric health.

## Grounding Rules

- Use `fact_id` values when planning evidence.
- Evidence tables must have stable IDs: `A1`, `A2`, `A3`, etc.
- Every finding should include `evidence_ids`.
- Reporter output should be structured JSON, then rendered by deterministic Python.
- HTML rendering must escape text and never render raw Python/JSON objects with `<pre>`.
