---
type: Attested Computation
title: セグメント別 粗利
description: 指定年度・セグメントの粗利額 (USD) と粗利率 (%) を算出する承認済み SQL 計算。
tags: [finance, profit, attested]
status: stable
runtime: sqlite
parameters:
  - { name: year, type: integer, required: true }
  - { name: segment, type: string, required: true }
executor:
  resource: /references/executors/sqlite_executor.md
  receipt: [job_id, executed_sql, bound_parameters, result_sha256, rows]
attester:
  resource: /references/attesters/sql_equality.md
generated: { by: "reference_agent/gemini-4-hydrogen", at: "2026-06-01T14:00:00Z" }
verified: { by: "process:finance-nightly", at: "2026-06-02T02:00:00Z" }
stale_after: "2026-06-15T00:00:00Z"
sources:
  - id: cost-alloc
    resource: https://example.com/finance/cost-allocation-standard
    title: 原価配賦標準マニュアル
    author: "team:finance-fpa"
    last_modified: "2026-05-20T00:00:00Z"
---

# Computation

```sql
SELECT fiscal_year, segment, gross_profit_usd, margin_pct
FROM gross_profit_summary
WHERE fiscal_year = :year
  AND segment = :segment
```

原価配賦標準マニュアルに基づき[^cost-alloc]、セグメント別の粗利額および粗利率を取得します。
`segment` には `retail`・`online`・`enterprise` のいずれかを指定してください。

[^cost-alloc]: 原価配賦標準マニュアル
