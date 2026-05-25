# Lv.5 Loop Pattern

## 概念

**Loop Pattern** は、終了条件を満たすまでサブエージェントのシーケンスを **繰り返し実行** するパターン。

```
Input
  │
  ▼
┌─────────────────────────────────────┐
│             LoopAgent               │
│  ┌─────────────────────────────┐   │
│  │  [Agent A] → [Agent B]      │   │  ← 1回目
│  └─────────────────────────────┘   │
│         ↓ 条件チェック              │
│  ┌─────────────────────────────┐   │
│  │  [Agent A] → [Agent B]      │   │  ← 2回目
│  └─────────────────────────────┘   │
│         ↓ 条件満たした！            │
└─────────────────────────────────────┘
  │
  ▼
Output
```

## 前のパターンとの違い

| 観点 | Sequential (Lv.3) | Loop (Lv.5) |
|---|---|---|
| 実行回数 | 固定（1回） | 動的（条件まで繰り返し） |
| 終了条件 | なし（常に全ステップ実行） | 品質基準・最大反復数 |
| 用途 | 固定パイプライン | 品質保証・反復改善 |

## このデモのユースケース

**コード生成 & テスト自動修正ループ**

```
User Request: "XXX を行う Python 関数を作って"
     │
     ▼
[Code Generator]  ← コードを生成
     │ output_key="generated_code"
     ▼
[Code Tester]     ← コードをテスト実行・評価
     │ output_key="test_result"
     │
     ├── テスト失敗 → ループ継続（Generator に戻る）
     └── テスト成功 → ループ終了

最大 5 回まで繰り返す（無限ループ防止）
```

## ⚠️ 重要: 終了条件の設計

LoopAgent には **必ず `max_iterations`** を設定すること！
エージェント自身は「終了すべき」という判断を出力テキスト内のシグナルで行う。

```python
LoopAgent(
    sub_agents=[generator, tester],
    max_iterations=5  # 必須！
)
```

## トレードオフ

| 観点 | 評価 |
|---|---|
| 品質 | 🟢 高（反復で品質向上） |
| コスト | 🟡 変動（反復回数に比例） |
| レイテンシ | 🟡 高（反復分だけ時間がかかる） |
| リスク | 🔴 収束しないと max_iterations まで実行 |

## 実行方法

```bash
# デモ実行
PYTHONPATH=. python3 patterns/05_loop/demo.py

# テスト（プロジェクトルートから）
pytest tests/unit/test_agent_structure.py::TestLoopStructure -v
pytest tests/integration/test_patterns.py::TestLoop -v
```

## 学習ポイント

1. `LoopAgent` の `max_iterations` の重要性
2. ループ終了の方法（出力テキストのシグナル vs カスタムコールバック）
3. セッション状態 (`output_key`) を使ったループ間のデータ引き継ぎ
4. ループが収束しない場合のリスクと対策

## 次のステップ

→ **[Lv.6 Review & Critique Pattern](../06_review_critique/)**: Generator と Critic を組み合わせた品質保証
