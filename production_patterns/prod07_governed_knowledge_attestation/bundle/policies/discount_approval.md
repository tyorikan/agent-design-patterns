---
type: Policy
title: 値引承認ポリシー
description: 営業案件の値引率に応じた承認エスカレーション基準。
tags: [finance, policy, discount]
status: stable
generated: { by: "reference_agent/gemini-4-hydrogen", at: "2026-11-10T10:00:00Z" }
verified:
  - { by: "human:finance-lead", at: "2026-10-01T09:00:00Z" }
stale_after: "2028-12-31T00:00:00Z"
sources:
  - id: sales-ops-memo
    resource: https://example.com/sales/discount-memo-q4
    title: Q4 営業値引運用メモ
    author: "team:sales-ops"
    last_modified: "2026-11-08T00:00:00Z"
---

# 承認基準

- 値引率 10% 以下は営業マネージャー承認、10% 超 20% 以下は財務責任者承認が必要です[^sales-ops-memo]。
- 20% を超える値引は役員会での事前承認が必要です。

(※ 2026年11月10日にエージェントが文言を改訂したため、10月1日時点の人間承認は `generated.at` より古くなり、OKF v0.3 ルールで自動的に `unverified` 扱いとなります。)

[^sales-ops-memo]: Q4 営業値引運用メモ
