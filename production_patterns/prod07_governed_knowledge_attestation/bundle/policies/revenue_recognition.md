---
type: Policy
title: 収益認識ポリシー
description: 売上計上タイミング、返品引当控除、および粗利算定の現行社内基準。
tags: [finance, policy, revenue]
status: stable
generated: { by: "human:finance-controller", at: "2026-10-01T09:00:00Z" }
verified: { by: "human:finance-controller", at: "2026-10-01T09:00:00Z" }
stale_after: "2028-12-31T00:00:00Z"
sources:
  - id: accounting-std
    resource: https://example.com/finance/revenue-standard-2026
    title: 2026年度 収益認識会計基準ガイド
    author: "team:accounting-policy"
    last_modified: "2026-09-15T00:00:00Z"
---

# ルール

1. 売上は商品の顧客引渡し完了時点で認識し、見積返品額を控除した純額で計上します[^accounting-std]。
2. 旧マージン算定基準の個別例外条項は廃止され、本ポリシーおよび [認識売上計算](../computations/recognized_revenue.md) に一本化されました。

[^accounting-std]: 2026年度 収益認識会計基準ガイド
