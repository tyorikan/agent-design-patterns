# Bonus: Human-in-the-Loop Pattern

## 概念

**Human-in-the-Loop** は、エージェントのワークフロー中に**人間の判断・承認**を
組み込むパターン。AI が処理を一時停止し、人間のレビューを待ってから次のステップに進む。
高リスクな操作や主観的な判断が必要な場面で、AI と人間の**協調**を実現する。

```
┌──────────────┐    ┌──────────────────┐    ┌──────────┐
│   Content    │    │   Compliance     │    │  🧑 Human │
│   Creator    │───→│   Checker        │───→│  Review   │
│  (AI 生成)   │    │  (AI リスク評価) │    │  (承認?)  │
└──────────────┘    └──────────────────┘    └────┬─────┘
                                                 │
                                       ┌─────────┴─────────┐
                                       │                    │
                                    ✅ 承認              ❌ 否認
                                       │                    │
                                       ▼                    ▼
                                ┌──────────────┐    ワークフロー終了
                                │    Final     │
                                │   Publisher  │
                                │  (公開処理)  │
                                └──────────────┘
```

## いつ使うか

✅ **Human-in-the-Loop が必要な場面:**
- 法的リスクのあるコンテンツの公開（景品表示法、薬機法）
- 大きな財務的意思決定（投資、発注）
- 患者データや個人情報の処理
- AI が確信を持てない曖昧なケース
- ブランドイメージに影響する公開コンテンツ

❌ **完全自動化でよい場面:**
- リスクが低く、AI の判断精度が十分なタスク
- リアルタイム性が重要で人間のレビューを待てない場合
- 大量の定型処理（→ Lv.7 Iterative Refinement で品質保証）

## Swarm (Lv.10) との違い

| 観点 | Swarm (Lv.10) | Human-in-the-Loop (Lv.11) |
|---|---|---|
| 意思決定者 | AI エージェント同士 | AI + 人間 |
| 承認プロセス | AI が自動で合意判定 | 人間が最終承認 |
| リスク管理 | 🟡 AI の判断に依存 | 🟢 人間がゲートキーパー |
| レイテンシ | 🔴 高（複数ラウンド） | 🔴 最高（人間の応答待ち） |
| 自律性 | 🟢 高（完全自動） | 🟡 中（人間の介入あり） |

## このデモのユースケース

**マーケティングコンテンツ承認ワークフロー**

Vertex AI のプロモーションコンテンツを生成し、コンプライアンスチェックを経て、
人間（あなた）がコンソールで承認/否認を判断する。承認された場合のみ最終公開される。

## アーキテクチャ

```
Workflow: content_approval_workflow
edges=[('START', content_creator, compliance_checker,
        final_publisher)]
※ final_publisher の before_agent_callback で人間レビューを実行

Step 1: コンテンツ生成
┌───────────────────────────────────────────────┐
│  LlmAgent: content_creator                    │
│  見出し / リード文 / 本文 / CTA を生成        │
│  output_key: generated_content                │
└───────────────────────────┬───────────────────┘
                            ▼
Step 2: コンプライアンスチェック
┌───────────────────────────────────────────────┐
│  LlmAgent: compliance_checker                 │
│  5 項目を審査（法的リスク / 誇大表現 / ...）  │
│  スコア判定:                                  │
│    85+ → [AUTO_APPROVED]                      │
│    70-84 → [HUMAN_REVIEW_REQUIRED]            │
│    <70 → [REJECTED]                           │
│  output_key: compliance_result                │
└───────────────────────────┬───────────────────┘
                            ▼
Step 3: 🧑 Human Review (before_agent_callback)
┌───────────────────────────────────────────────┐
│  final_publisher の before_agent_callback      │
│  → コンソールで人間が承認/否認                │
│  否認 → skip_agent() でワークフロー終了       │
└────────────┬──────────────────┬────────────────┘
             │                  │
          ✅ 承認            ❌ 否認
             ▼                  ▼
Step 4: 最終公開           skip_agent() で終了
┌──────────────────────┐
│  LlmAgent:           │
│  final_publisher     │
│  公開メタデータ付き  │
│  最終コンテンツ出力  │
└──────────────────────┘
```

### 実装のポイント: Workflow チェーンタプル + before_agent_callback

```python
from google.adk.workflow import Workflow

# before_agent_callback で人間レビューを挿入
async def human_review_callback(callback_context):
    """final_publisher 実行前に人間の承認を求める"""
    approved = Confirm.ask("承認しますか？")
    if not approved:
        callback_context.state["human_review"] = "rejected"
        callback_context.skip_agent()  # エージェントをスキップ
        return
    callback_context.state["human_review"] = "approved"

final_publisher.before_agent_callback = human_review_callback

# Workflow のチェーンタプルで順次実行を定義
workflow = Workflow(
    name="content_approval_workflow",
    edges=[('START', content_creator, compliance_checker,
            final_publisher)],
)
```

## トレードオフ

| 観点 | 評価 |
|---|---|
| コスト | 🟡 中（3 エージェントの LLM 呼び出し） |
| レイテンシ | 🔴 最高（人間の応答待ち時間が支配的） |
| 複雑性 | 🟡 中（Workflow チェーンタプル + callback） |
| リスク管理 | 🟢 最高（人間がゲートキーパー） |
| スケーラビリティ | 🔴 低（人間がボトルネック） |
| 信頼性 | 🟢 高（AI + 人間のダブルチェック） |

## 実行方法

```bash
PYTHONPATH=../.. python3 demo.py
# → コンソールで承認/否認を入力するインタラクティブデモ
```

## 学習ポイント

1. **Workflow チェーンタプル** — `Workflow(edges=[('START', a, b, c)])` で順次実行を宣言的に定義。v1 の手動段階実行が不要になった
2. **`before_agent_callback` による人間レビュー** — `final_publisher` の実行前に callback で人間の承認を挟み、否認なら `skip_agent()` でスキップする設計
3. **セッション状態を介したデータ受け渡し** — `output_key` で各ステップの結果をセッション状態に保存し、次のエージェントの `{変数名}` で参照
4. **コンプライアンスチェックの自動化と人間レビューの分離** — AI が定型的なリスク評価を自動化し、人間は AI のレポートを見て最終判断に集中する役割分担
5. **完全自動化 vs 人間監視のトレードオフ** — スケーラビリティは下がるが、高リスクなタスクではコンプライアンスと信頼性を担保できる
