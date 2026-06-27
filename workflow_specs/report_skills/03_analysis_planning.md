# Skill: Analysis Planning

Given analysis intent and confirmed config, produce an executable plan for the Fact Engine.

Return JSON only:

```json
{
  "goal": "string",
  "business_domain": "string",
  "primary_metric": "metric name",
  "modules": [
    {
      "name": "trend_analysis",
      "metrics": ["metric name"],
      "dimensions": ["dimension name"],
      "reason": "string"
    }
  ],
  "evidence_requirements": [
    "period_comparison",
    "anomaly_table",
    "dimension_contribution",
    "attribution_table"
  ],
  "limitations": ["string"]
}
```

Rules:

- Use only configured metrics, formulas, and dimensions.
- Prefer primary metrics from config.
- Keep the plan compact and executable.
- Missing required fields should become limitations, not invented analysis.
