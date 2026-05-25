# Lv.4 Parallel Pattern

## 概念

**Parallel Pattern** は、独立した複数のエージェントを **同時並行で** 実行するパターン。
全エージェントの完了後、集約エージェントが結果をまとめる。

```
                    ┌→ [Agent A] → output_key="result_a" →┐
Input → [Dispatch] →├→ [Agent B] → output_key="result_b" →├→ [Aggregator] → Output
                    └→ [Agent C] → output_key="result_c" →┘
```

## Sequential との違い

| 観点 | Sequential (Lv.3) | Parallel (Lv.4) |
|---|---|---|
| 実行順序 | 順番（前の結果を次が使う） | 並列（独立して同時実行） |
| データ依存 | エージェント間に依存あり | 各エージェントは独立 |
| レイテンシ | 合計時間 = 各エージェント時間の和 | 合計時間 = 最も遅いエージェントの時間 |
| 用途 | パイプライン処理 | ファンアウト収集 |

## このデモのユースケース

**マルチソースニュース集約エージェント**

複数のトピックを同時並行で調査し、結果をまとめる。

```
Query: "AI の最新動向を調べて"
          │
          ├→ [Research Agent A: Gemini/Google]   ← 並列実行 ⚡
          ├→ [Research Agent B: OpenAI/ChatGPT]  ← 並列実行 ⚡
          ├→ [Research Agent C: 規制・政策動向]  ← 並列実行 ⚡
          └→ [Research Agent D: 産業応用事例]    ← 並列実行 ⚡
                    │（全員完了を待つ）
                    ▼
          [Synthesis Agent: 統合レポート作成]
```

## トレードオフ

| 観点 | 評価 |
|---|---|
| レイテンシ | 🟢 最も遅いエージェントの時間のみ |
| コスト | 🟡 中（並列=同時に複数モデル呼び出し） |
| 独立性 | 🔴 各エージェントが独立している必要がある |
| output_key | 🔴 各エージェントで別々のキーを使う必要あり |

## ⚠️ 重要: 並列エージェントのルール

ParallelAgent の各サブエージェントは **必ず異なる `output_key`** を使うこと！
同じキーを使うと結果が上書きされる。

## 実行方法

```bash
# デモ実行
PYTHONPATH=. python3 patterns/04_parallel/demo.py

# テスト（プロジェクトルートから）
pytest tests/unit/test_agent_structure.py::TestParallelStructure -v
pytest tests/integration/test_patterns.py::TestParallel -v
```

## 学習ポイント

1. `ParallelAgent` と `SequentialAgent` を組み合わせる方法
2. 並列実行で全体レイテンシを削減する仕組み
3. 集約パターン（Fan-out → Fan-in）の設計
4. 並列実行に適したタスクの見分け方（独立性の確認）

## 次のステップ

→ **[Lv.5 Loop Pattern](../05_loop/)**: 終了条件を満たすまで繰り返すパターン
