---
okf_version: "0.3"
title: Sample Retail Finance Knowledge Bundle
description: 小売・EC 事業向けの認識売上・粗利・承認ポリシーと承認済み計算 (Attested Computation) を収めた OKF v0.3 サンプルバンドル。財務数値や基準ポリシーの質問に使用する。
license: Apache-2.0
x-sample-owner: team:finance-engineering
---

# Metrics

* [損益サマリ指標 (年度別)](metrics/income_statement.md) - 認識売上と粗利の全体定義と承認済み計算へのリンク。

# Computations

* [年度別 認識売上 (Attested Computation)](computations/recognized_revenue.md) - 財務基準に基づく年度別認識売上の承認済み SQL 計算。
* [セグメント別 粗利 (Attested Computation)](computations/gross_profit.md) - セグメント別の年度粗利を算出する承認済み SQL 計算 (鮮度期限超過サンプル)。

# Policies

* [収益認識ポリシー](policies/revenue_recognition.md) - 売上計上タイミングと返品控除の現行基準。
* [値引承認ポリシー](policies/discount_approval.md) - 大口案件の値引承認基準 (人間レビュー後にエージェント更新が入り未再検証のサンプル)。
* [旧マージン算定基準 (廃止)](policies/legacy_margin_policy.md) - 現行の収益認識ポリシーへ統合済みの廃止ドキュメント。
