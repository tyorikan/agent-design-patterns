# Lv.9 Hierarchical Task Decomposition Pattern

## 概念

**Hierarchical Task Decomposition** は、複数レベルのエージェント階層で
タスクを段階的に分解・実行するパターン。Coordinator（Lv.8）の**多段階版**であり、
大規模で複雑なタスクを「分割統治」で処理する。

```
          ┌─────────────────┐
          │   Root Agent     │  Layer 1: 統括
          │   (Director)     │
          └─────┬───────┬────┘
                │       │
       ┌────────┘       └────────┐
       ▼                         ▼
┌──────────────┐          ┌──────────────┐
│  Research    │ Layer 2   │  Analysis    │  Layer 2
│  Coordinator │ 中間管理  │  Coordinator │  中間管理
└──┬────────┬──┘          └──┬────────┬──┘
   │        │                │        │
   ▼        ▼                ▼        ▼
[Web]    [News]          [Finance] [Tech]   Layer 3: 実行
Researcher Researcher   Analyst   Analyst
```

## いつ使うか

✅ **適している場合:**
- タスクが複数のサブドメインに自然に分解できる
- 各サブドメインに専門的な分析・処理が必要
- 中間管理者による調整・統合が有効
- 大規模なレポート生成、総合的な調査・分析

❌ **限界:**
- エージェント数が多く、LLM 呼び出しコストが高い
- 3 層以上になると管理・デバッグの難易度が上がる
- シンプルなタスクにはオーバーエンジニアリング（→ Lv.8 Coordinator で十分）
- `{変数名}` の依存関係管理が複雑になる

## Coordinator (Lv.8) との違い

| 観点 | Coordinator (Lv.8) | Hierarchical (Lv.9) |
|---|---|---|
| 階層数 | 2 層（Root → Specialists） | 3 層以上（Root → Coordinators → Workers） |
| タスク分解 | 単一レベルの振り分け | 段階的な分解と統合 |
| 中間管理者 | なし | あり（チームのマネージャー） |
| 適用規模 | 🟢 小〜中規模 | 🟡 中〜大規模 |
| コスト | 🟢 低〜中 | 🔴 高（多数の LLM 呼び出し） |
| データフロー | 🟢 シンプル | 🟡 `output_key` で階層間を連携 |

## このデモのユースケース

**競合分析レポート自動生成**

企業名を入力すると、3 層のエージェント階層が
調査 → 分析 → レポート作成を段階的に実行し、
SWOT 分析を含むエグゼクティブレポートを自動生成する。

## アーキテクチャ

```
User: "Google の競合分析をしてください"
  │
  ▼
┌──────────────────────────────────────────────────────┐
│  Layer 1: Root Agent (competitive_analysis_root)     │
│  役割: 統括ディレクター                               │
│  ① research_coordinator に基礎調査を指示             │
│  ② analysis_coordinator に詳細分析を指示             │
│  ③ report_coordinator に最終レポート作成を指示       │
├──────────────────────────────────────────────────────┤
│                                                      │
│  Layer 2-A: research_coordinator                     │
│  ┌────────────────────┐ ┌────────────────────┐       │
│  │ web_researcher      │ │ news_researcher    │       │
│  │ → web_research_data │ │ → news_research    │       │
│  │   (output_key)      │ │   _data            │       │
│  │ ※ ユーザーメッセージ│ │ ※ {web_research    │       │
│  │   から直接読み取り  │ │    _data} を参照   │       │
│  └────────────────────┘ └────────────────────┘       │
│                                                      │
│  Layer 2-B: analysis_coordinator                     │
│  ┌────────────────────┐ ┌────────────────────┐       │
│  │ financial_analyst   │ │ tech_analyst       │       │
│  │ → financial_        │ │ → tech_analysis    │       │
│  │   analysis          │ │ ※ {web_research   │       │
│  │ ※ {web_research    │ │    _data} +        │       │
│  │    _data} を参照    │ │   {news_research   │       │
│  └────────────────────┘ │    _data} を参照   │       │
│                          └────────────────────┘       │
│                                                      │
│  Layer 2-C: report_coordinator                       │
│  全 output_key を統合してエグゼクティブレポート作成   │
└──────────────────────────────────────────────────────┘
```

### データフロー（`output_key` の連鎖）

```
web_researcher ──→ web_research_data ──┬→ news_researcher
                                       ├→ financial_analyst
                                       ├→ tech_analyst
                                       └→ report_coordinator

news_researcher ─→ news_research_data ─┬→ tech_analyst
                                       └→ report_coordinator

financial_analyst → financial_analysis ──→ report_coordinator
tech_analyst ─────→ tech_analysis ───────→ report_coordinator
```

## トレードオフ

| 観点 | 評価 |
|---|---|
| コスト | 🔴 高（7 エージェント × LLM 呼び出し） |
| レイテンシ | 🔴 高（3 層の逐次実行） |
| 複雑性 | 🟡 中〜高（`output_key` の依存関係管理） |
| 品質 | 🟢 高（専門家の分業と統合） |
| 柔軟性 | 🟢 高（層・エージェントの追加が容易） |
| スケーラビリティ | 🟢 高（新しいチームを追加可能） |

## 実行方法

```bash
PYTHONPATH=../.. python3 demo.py
```

## 学習ポイント

1. **3 層アーキテクチャの設計** — Root（統括）→ Coordinator（中間管理）→ Worker（実行）の責務分離
2. **`output_key` によるデータフロー** — 各 Worker の出力を `output_key` でセッション状態に保存し、後段のエージェントが `{変数名}` で参照する
3. **ADK の `{変数名}` の制約** — セッション状態に存在しないキーを `{変数名}` で参照するとエラー。最初に実行される `web_researcher` はユーザーメッセージから直接読み取る設計にする
4. **Coordinator エージェントの役割** — 自身では処理せず、チームメンバーへの指示と結果の統合に専念する「マネージャー」パターン
5. **レポート統合の設計** — `report_coordinator` が全 `output_key` を instruction 内で `{変数名}` として参照し、1 つのドキュメントに統合する

## 次のステップ

→ **[Lv.10 Swarm Pattern](../p10_swarm/)**: 分散型コンセンサス
