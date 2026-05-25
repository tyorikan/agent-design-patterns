# Capstone: Enterprise Research Agent

## 🏆 全デザインパターン統合

このエージェントは、学習した **全デザインパターン** を組み合わせた最終形態。
実際のエンタープライズ環境で使えるレベルの品質レポートを自動生成する。

## アーキテクチャ

```
User: "企業 X を分析して"
        │
        ▼
[Coordinator]           ← Lv.8: 意図を解釈・委譲
        │
        ▼
[SequentialAgent]       ← Lv.3: 順次パイプライン
  │
  ├─ [ParallelAgent]    ← Lv.4: 並列データ収集
  │    ├─ Web Researcher    → web_data
  │    ├─ Tech Researcher   → tech_data
  │    └─ Finance Researcher → financial_data
  │
  ├─ [Analysis Agent]   ← SWOT 分析・スコアリング
  │    (uses: web_data, tech_data, financial_data)
  │
  └─ [LoopAgent]        ← Lv.5/6: 品質改善ループ (max 3回)
       ├─ Report Writer  → report_draft
       └─ Report Critic  → critic_feedback
```

## 各パターンの役割

| パターン | エージェント | 役割 |
|---------|------------|------|
| Coordinator (Lv.8) | `enterprise_research_coordinator` | ユーザー意図の解釈と委譲 |
| Sequential (Lv.3) | `enterprise_research_pipeline` | 3ステップの順次処理 |
| Parallel (Lv.4) | `data_collection_parallel` | 3ソースの同時並行収集 |
| Loop (Lv.5) | `report_refinement_loop` | 品質改善のループ |
| Review/Critique (Lv.6) | `report_critic` | レポートの品質評価 |

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

1. **パターンの組み合わせ方**: Sequential の中に Parallel と Loop を内包
2. **セッション状態の受け渡し**: `output_key` でエージェント間データを連携
3. **品質保証の仕組み**: Loop + Critic でレポート品質を自動担保
4. **コーディネーション**: LLM が意図を理解して適切なサブシステムに委譲
5. **エンタープライズグレードの設計**: 実務で使えるレポート生成システム

## 前提知識

このパターンを理解するには、以下の Lv. を先に学習してください:
- Lv.3 Sequential → Lv.4 Parallel → Lv.5 Loop → Lv.6 Review/Critique → Lv.8 Coordinator → **Capstone**
