---
type: Attested Computation
title: 年度別 認識売上
description: 財務基準に基づく指定年度の認識売上合計 (USD) を算出する承認済み SQL 計算。
tags: [finance, revenue, attested]
status: stable
runtime: sqlite
parameters:
  - { name: year, type: integer, required: true }
executor:
  resource: /references/executors/sqlite_executor.md
  receipt: [job_id, executed_sql, bound_parameters, result_sha256, rows]
attester:
  resource: /references/attesters/sql_equality.md
generated: { by: "reference_agent/gemini-4-hydrogen", at: "2026-10-01T10:00:00Z" }
verified: { by: "human:finance-controller", at: "2026-10-05T09:30:00Z" }
stale_after: "2028-12-31T00:00:00Z"
sources:
  - id: rev-policy
    resource: /policies/revenue_recognition.md
    title: 収益認識ポリシー
    author: "team:finance-fpa"
    last_modified: "2026-10-01T00:00:00Z"
  - id: exec-rev-dash
    resource: https://example.com/bi/executive-revenue
    title: 経営向け売上ダッシュボード
    author: "team:finance-fpa"
    usage_count: 4200
    last_modified: "2026-10-04T00:00:00Z"
usage_window: { from: "2026-09-01T00:00:00Z", to: "2026-09-30T00:00:00Z" }
---

# Computation

```sql
SELECT fiscal_year, SUM(amount_usd) AS total_recognized_revenue_usd
FROM recognized_revenue
WHERE fiscal_year = :year
GROUP BY fiscal_year
```

指定年度の全セグメント合算の認識売上を算出します。収益認識ポリシーに準拠し[^rev-policy]、
経営向け売上ダッシュボードの集計ロジックと照合済みです[^exec-rev-dash]。

[^rev-policy]: 収益認識ポリシー
[^exec-rev-dash]: 経営向け売上ダッシュボード
