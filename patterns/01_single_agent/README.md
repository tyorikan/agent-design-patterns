# Lv.1 Single Agent パターン

## 概念

**Single Agent** は最も基本的なエージェントパターン。
1 つの LLM エージェントが、ツールセットを使って自律的にタスクを完了する。

```
User → [LlmAgent + Tools] → Response
         ↑    ↓
      Thought/Action/Observation ループ（内部）
```

## いつ使うか

✅ **適している場合:**
- 外部データへのアクセスが必要なマルチステップタスク
- プロトタイプや PoC の最初のステップ
- ツール数が少なく、タスクが比較的シンプル

❌ **限界:**
- ツール数が増えると精度が低下
- タスクが複雑すぎると失敗しやすい
- → 複数エージェントのパターンへ移行を検討

## このデモのユースケース

**Google Cloud ドキュメント Q&A エージェント**

ユーザーが Google Cloud のサービスについて質問すると、
エージェントが Web 検索を使って最新の情報を調べて回答する。

## アーキテクチャ

```
User Question
     │
     ▼
┌─────────────────────────────────────┐
│         GCP Docs Agent              │
│  model: gemini-3.5-flash            │
│                                     │
│  Tools:                             │
│  - google_search: Web 検索          │
│  - get_current_time: 現在時刻取得   │
│                                     │
│  instruction: GCP 専門家として回答  │
└─────────────────────────────────────┘
     │
     ▼
   Answer
```

## トレードオフ

| 観点 | 評価 |
|---|---|
| コスト | 🟢 低（単一エージェント） |
| レイテンシ | 🟢 低〜中 |
| 複雑性 | 🟢 シンプル |
| 柔軟性 | 🟡 中（ツール追加で拡張可能） |
| スケーラビリティ | 🔴 ツール数が増えると限界 |

## 実行方法

```bash
# デモ実行（事前に .env 設定が必要）
PYTHONPATH=. python3 patterns/01_single_agent/demo.py

# テスト（プロジェクトルートから）
pytest tests/unit/test_agent_structure.py::TestSingleAgentStructure -v
pytest tests/integration/test_patterns.py::TestSingleAgent -v
```

## 学習ポイント

1. `LlmAgent` の基本構造（name, model, instruction, tools）
2. ツール定義の方法（型アノテーションと docstring が必須）
3. `Runner` と `InMemorySessionService` の使い方
4. エージェントが「どのツールをいつ使うか」を自律的に判断する仕組み

## 次のステップ

→ **[Lv.2 ReAct Pattern](../02_react_pattern/)**: Thought/Action/Observation ループを明示的に理解する
