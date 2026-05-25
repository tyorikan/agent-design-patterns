# Lv.2 ReAct Pattern

## 概念

**ReAct (Reasoning + Acting)** は、エージェントが **思考 (Thought) → 行動 (Action) → 観察 (Observation)** を繰り返しながら問題を解くパターン。

ADK の `LlmAgent` はデフォルトでこのパターンを実装しているが、ここでは **ループを明示的に可視化** することで、エージェントの内部思考プロセスを理解することが目的。

```
Input
  │
  ▼
[Thought]  ← LLM が「何をすべきか」を思考
  │
  ▼
[Action]   ← ツールを実行
  │
  ▼
[Observation] ← ツールの結果を観察
  │
  ├──→ まだ必要？ → [Thought] へ戻る
  │
  └──→ 完了 → Output
```

## Single Agent との違い

| 観点 | Single Agent (Lv.1) | ReAct Pattern (Lv.2) |
|---|---|---|
| 思考プロセス | 内部で自動 | 明示的なイベントで可視化 |
| デバッグ | 困難 | 各ステップを追跡可能 |
| 用途 | シンプルなタスク | 複雑な推論が必要なタスク |

## このデモのユースケース

**技術調査エージェント**

複数の情報ソースを検索しながら、段階的に問題を分析するエージェント。
Thought/Action/Observation の各ステップをログで確認できる。

## アーキテクチャ

```
Query
  │
  ▼
┌──────────────────────────────────────────┐
│         Research Agent (ReAct)           │
│                                          │
│  Loop:                                   │
│    Thought: 何を調べるべきか考える       │
│    Action:  google_search を実行         │
│    Obs:     検索結果を確認               │
│    Thought: 次に何が必要か考える         │
│    Action:  calculate or search ...      │
│    Obs:     ...                          │
│    → 十分な情報が揃ったら回答           │
└──────────────────────────────────────────┘
  │
  ▼
Detailed Report
```

## トレードオフ

| 観点 | 評価 |
|---|---|
| コスト | 🟡 中（複数ラウンドのモデル呼び出し） |
| レイテンシ | 🟡 中〜高（思考ループの分だけ時間がかかる） |
| 精度 | 🟢 高（段階的な推論で複雑な問題を解ける） |
| デバッグ | 🟢 容易（各ステップが可視化される） |

## 実行方法

```bash
# デモ実行（思考ループが表示される）
PYTHONPATH=. python3 patterns/02_react_pattern/demo.py

# テスト（プロジェクトルートから）
pytest tests/unit/test_agent_structure.py::TestReActStructure -v
pytest tests/integration/test_patterns.py::TestReAct -v
```

## 学習ポイント

1. ADK の `runner.run_async()` が返すイベントストリームの構造
2. `function_call` イベントと `function_response` イベントの関係
3. Thought → Action → Observation ループを追跡してデバッグする方法
4. ReAct が有効な場面（多段階推論、不確実性の高いタスク）

## 次のステップ

→ **[Lv.3 Sequential Pattern](../03_sequential/)**: 固定した順序で複数エージェントを実行する
