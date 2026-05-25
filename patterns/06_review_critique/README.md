# Lv.6 Review & Critique Pattern

## 概念

Generator（生成）と Critic（批評）の **2エージェントがループ** して、コンテンツ品質を保証するパターン。
Loop Pattern (Lv.5) の特殊形で、明確な役割分担が特徴。

```
Input
  │
  ▼
[Generator] ← コンテンツを生成・改善
  │ output_key="article_draft"
  ▼
[Critic]    ← 品質を評価・フィードバック
  │ output_key="critic_feedback"
  │
  ├── [NEEDS_REVISION] → Generator に戻る（フィードバックを反映）
  └── [APPROVED]       → ループ終了
```

## いつ使うか

✅ **適している場合:**
- 高品質なコンテンツ生成が必要（ブログ記事、マーケティング文書）
- 「生成」と「評価」で異なる観点が必要
- 品質基準が明確に定義できる（スコアリング可能）
- セキュリティ/コンプライアンスチェックが必要

❌ **限界:**
- Generator と Critic の見解が対立して収束しないリスク
- 反復回数が増えるとコスト増大（反復 × 2 のモデル呼び出し）
- → 自己評価で十分なら Lv.7 Iterative Refinement を検討

## Loop Pattern (Lv.5) との違い

| 観点 | Loop (Lv.5) | Review & Critique (Lv.6) |
|---|---|---|
| 役割分担 | 同一タスクの繰り返し | Generator と Critic の明確な分離 |
| フィードバック | テスターの評価 | Critic の詳細な批評（スコア+改善点） |
| 視点の多様性 | 単一視点 | 生成者 ≠ 評価者で多角的 |
| 用途 | 反復改善全般 | コンテンツ品質保証 |

## このデモのユースケース

**技術ブログ記事の品質保証**

```
User: "Cloud Run のブログ記事を書いて"
     │
     ▼
┌─────────────────────────────────────────┐
│           LoopAgent (max=4)             │
│                                         │
│  [blog_generator]                       │
│    model: gemini-3.5-flash              │
│    ├── 600〜800文字の技術ブログ記事     │
│    └── output_key="article_draft"       │
│         │                               │
│         ▼                               │
│  [blog_critic]                          │
│    ├── 5つの評価基準（各20点）          │
│    ├── 総合スコア XX/100                │
│    ├── 改善が必要な点（3点以内）        │
│    └── output_key="critic_feedback"     │
│         │                               │
│         ├── 80点未満 [NEEDS_REVISION]   │
│         │   → Generator に戻る          │
│         └── 80点以上 [APPROVED]         │
│             → ループ終了                │
└─────────────────────────────────────────┘
```

## トレードオフ

| 観点 | 評価 |
|---|---|
| 品質 | 🟢 高（Critic が厳格に評価し、具体的な改善指示） |
| コスト | 🟡 中（反復回数 × 2 のモデル呼び出し） |
| レイテンシ | 🟡 中〜高（反復分だけ時間がかかる） |
| 多様性 | 🟢 高（Generator と Critic で異なる視点） |
| 制御性 | 🟢 高（スコアと明確な判定シグナル） |

## 実行方法

```bash
# デモ実行
PYTHONPATH=. python3 patterns/06_review_critique/demo.py

# テスト（プロジェクトルートから）
pytest tests/unit/test_agent_structure.py::TestReviewCritiqueStructure -v
pytest tests/integration/test_patterns.py::TestReviewCritique -v
```

## 学習ポイント

1. **Generator/Critic の役割設計**: 生成者と評価者を分離することで品質が向上する仕組み
2. **`output_key` の循環**: Generator の `article_draft` を Critic が参照し、Critic の `critic_feedback` が次の Generator に影響
3. **品質基準の `instruction` 定義**: スコアリング基準（各20点 × 5項目 = 100点満点）の設計方法
4. **ループ終了シグナル**: `[APPROVED]` / `[NEEDS_REVISION]` という出力テキスト内のシグナルで LoopAgent を制御
5. **`max_iterations` の設定**: 収束しない場合に備えた安全弁（このデモでは4回）

## 次のステップ

→ **[Lv.7 Iterative Refinement](../07_iterative_refinement/)**: 自己評価スコアで品質改善（Generator と Critic を1つに統合）
