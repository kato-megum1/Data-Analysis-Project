# Skill: Analysis Intent Selection

Given dataset profile, user background, and optional user request, infer the analysis goal.

Return JSON only:

```json
{
  "analysis_goal": "string",
  "business_domain": "sales_retail|finance|growth|general",
  "primary_methods": ["trend_analysis"],
  "focus_metrics": ["metric name"],
  "focus_dimensions": ["dimension name"],
  "comparison": "latest_vs_previous|overall_baseline|none",
  "reason": "string",
  "confidence": 0.0
}
```

Rules:

- Select only methods supported by the available columns.
- If a date field exists and numeric metrics exist, include `trend_analysis`.
- If metrics and enough periods exist, include `anomaly_detection`.
- If categorical dimensions and metrics exist, include `dimension_drilldown`.
- If formulas or related drivers exist, include `attribution_analysis`.
- Retail or sales data should usually include `cross_analysis` and `rule_check`.
