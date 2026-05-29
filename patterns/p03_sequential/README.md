# Lv.3 Sequential Pattern

## 概念

**Sequential Pattern** は、複数のエージェントを **固定した順序で** 順次実行するパターン。
`Workflow` のチェーンタプル構文で、エージェントを直列に並べるだけでパイプラインを構築できる。

```
Input → [Agent A] → [Agent B] → [Agent C] → Output
```

```python
from google.adk.workflow import Workflow

pipeline = Workflow(
    name='sequential_pipeline',
    edges=[('START', agent_a, agent_b, agent_c)]
)
```

## Single Agent との違い

| 観点 | Single Agent | Sequential Pattern |
|---|---|---|
| エージェント数 | 1つ | 複数（固定順序） |
| オーケストレーション | LLM が判断 | 決定論的（コード制御） |
| 責務 | 1エージェントが全担当 | 各エージェントが専門に特化 |
| コスト | 低 | 低（LLM ルーティング不要） |

## このデモのユースケース

**ETL データパイプライン**

```
Raw Data
   │
   ▼
[Extractor Agent]  ← データを抽出・パース
   │ output_key="extracted_data"
   ▼
[Validator Agent]  ← データの品質チェック
   │ output_key="validated_data"
   ▼
[Transformer Agent] ← データ変換・整形
   │ output_key="transformed_data"
   ▼
[Summary Agent]    ← 処理結果サマリー作成
   │
   ▼
Final Report
```

## トレードオフ

| 観点 | 評価 |
|---|---|
| コスト | 🟢 低（LLM によるルーティング不要） |
| レイテンシ | 🟢 低（各エージェントが専門に集中） |
| 複雑性 | 🟢 シンプル（固定フロー） |
| 柔軟性 | 🔴 低（フローを動的に変更できない） |
| スキップ | 🔴 不要なステップをスキップできない |

## 実行方法

```bash
# デモ実行
PYTHONPATH=. python3 patterns/p03_sequential/demo.py

# テスト（プロジェクトルートから）
pytest tests/unit/test_agent_structure.py::TestSequentialStructure -v
pytest tests/integration/test_patterns.py::TestSequential -v
```

## 学習ポイント

1. `Workflow` のチェーンタプル構文（`edges=[('START', a, b, c)]`）
2. `output_key` でエージェント間のデータを受け渡す方法
3. instruction 内の `{key}` プレースホルダーでセッション状態を参照する方法
4. 決定論的なフロー（LLM オーケストレーション不要）のメリット

## 次のステップ

→ **[Lv.4 Parallel Pattern](../p04_parallel/)**: 独立したタスクを並列実行してレイテンシを削減
