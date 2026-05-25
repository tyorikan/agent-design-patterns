# Capstone: Enterprise Research Agent

## 🏆 全デザインパターン統合

このエージェントは、学習した **全デザインパターン** を組み合わせた最終形態。
実際のエンタープライズ環境で使えるレベルの品質レポートを自動生成する。

## アーキテクチャ

```
User: "企業 X を分析して"
        │
        ▼
[Coordinator]                ← Lv.8: 意図を解釈・委譲
        │
        ▼
Workflow: enterprise_research_pipeline
edges=[('START',
        (web_researcher,       ← Lv.4: 並列データ収集
         tech_researcher,        (fan-out タプル)
         finance_researcher),
        analysis_agent,        ← SWOT 分析・スコアリング
        report_writer,         ← Lv.5/6: 品質改善サイクル
        report_critic,
        {'REVISE': report_writer})]  ← 条件付きサイクル
```

## 各パターンの役割

| パターン | Workflow での表現 | 役割 |
|---------|------------------|------|
| Coordinator (Lv.8) | `enterprise_research_coordinator`（Workflow の呼び出し元） | ユーザー意図の解釈と委譲 |
| Sequential (Lv.3) | チェーンタプル `('START', ..., analysis, writer, critic)` | 順次パイプライン |
| Parallel (Lv.4) | fan-out タプル `(web, tech, finance)` | 3ソースの同時並行収集 |
| Loop (Lv.5) | 条件付きサイクル `{'REVISE': report_writer}` | 品質改善のサイクル |
| Review/Critique (Lv.6) | `report_critic`（サイクル内ノード） | レポートの品質評価 |

## 出力サンプル

```
# 企業技術戦略評価レポート: Salesforce

## エグゼクティブサマリー
...（主要な発見と推奨事項）

## 企業概要
...（事業内容・規模）

## 技術戦略の評価
...（Agentforce、Einstein AI 等の評価）

## SWOT 分析
...

## 総合評価
- 総合スコア: 82/100
- 投資魅力度: ★★★★☆
```

## 実行方法

```bash
cd patterns/capstone
PYTHONPATH=../.. python3 demo.py
```

## 学習ポイント

このエージェントを通じて理解できること:

1. **Workflow 1 つで全パターンを統合**: チェーンタプル（Sequential）、fan-out タプル（Parallel）、条件付きサイクル dict（Loop）を 1 つの `edges` に宣言
2. **セッション状態の受け渡し**: `output_key` でエージェント間データを連携
3. **品質保証の仕組み**: 条件付きサイクル `{'REVISE': report_writer}` + Critic でレポート品質を自動担保
4. **コーディネーション**: Coordinator が意図を理解して Workflow を呼び出す構成（Workflow は BaseNode のサブクラスなので sub_agents には入れず、Coordinator から直接実行）
5. **エンタープライズグレードの設計**: 実務で使えるレポート生成システム

## 前提知識

このパターンを理解するには、以下の Lv. を先に学習してください:
- Lv.3 Sequential → Lv.4 Parallel → Lv.5 Loop → Lv.6 Review/Critique → Lv.8 Coordinator → **Capstone**
- v2 では上記すべてが `Workflow` の `edges` 構文に統合されています
