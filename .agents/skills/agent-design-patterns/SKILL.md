---
name: agent-design-patterns
description: |
  AI エージェントのデザインパターンを選択・実装するためのスキル。
  Google Cloud のアーキテクチャガイドに基づき、10 のデザインパターン（Single Agent から Swarm まで）の
  特徴・適用条件・トレードオフを整理し、実装時の判断基準を提供する。
  エージェント実装のアーキテクチャ決定時に必ず参照すること。
---

# AI エージェント デザインパターン スキル

## 概要

エージェントデザインパターンは、エージェントシステムを構築するための一般的なアーキテクチャアプローチ。
パターンを選択する際は以下の4要素でワークロードを評価する：

| 評価軸 | 質問 |
|---|---|
| **タスク特性** | 事前定義ワークフローで解決可能か？それともオープンエンドか？ |
| **レイテンシ** | 高速応答とスループット、どちらが優先か？ |
| **コスト** | 複数モデル呼び出しのコストを許容できるか？ |
| **人間の関与** | 重要な判断に人間のレビューが必要か？ |

---

## パターン一覧と選択ガイド

### 決定論的ワークフロー（Deterministic Workflows）

予測可能・順序固定・事前定義のフロー。モデルオーケストレーション不要。

#### Pattern 1: Single Agent
```
User → [LlmAgent + Tools] → Response
```
**いつ使う:**
- 外部データへのアクセスが必要なマルチステップタスク
- プロトタイプ・PoC の初期実装
- ツール数が少なく、タスクが比較的シンプル

**ADK 実装:**
```python
agent = LlmAgent(
    name="SingleAgent",
    model="gemini-3.8-flash",
    instruction="...",
    tools=[tool1, tool2]
)
```

**⚠️ 限界:** ツール数・タスク複雑度が増すと精度低下・レイテンシ増大

---

#### Pattern 2: Sequential Pattern
```
Input → [Agent A] → [Agent B] → [Agent C] → Output
```
**いつ使う:**
- ETL パイプライン
- 固定された順序の多段階処理
- モデル不要のオーケストレーション（低コスト）

**ADK 実装:**
```python
from google.adk.workflow import Workflow

pipeline = Workflow(
    name="Pipeline",
    edges=[('START', agent_a, agent_b, agent_c)]
)
# agent_a は output_key="result_a" で状態に保存
# agent_b は instruction で {result_a} を参照
```

**トレードオフ:**
- ✅ 低コスト・低レイテンシ（LLM オーケストレーション不要）
- ❌ 柔軟性なし、不要ステップをスキップできない

---

#### Pattern 3: Parallel Pattern
```
         ┌→ [Agent A] →┐
Input → [Dispatcher] →  ├→ [Agent B] →├→ [Aggregator] → Output
         └→ [Agent C] →┘
```
**いつ使う:**
- 独立した複数タスクの同時実行（市場調査、多言語翻訳）
- レイテンシ削減が最優先
- 複数ソースからのデータ収集

**ADK 実装:**
```python
from google.adk.workflow import Workflow

research = Workflow(
    name="ParallelGatherer",
    edges=[
        ('START', (market_agent, competitor_agent, news_agent), aggregator)
    ]
    # 各エージェントは別々の output_key を使う！
)
```

**トレードオフ:**
- ✅ 全体レイテンシの削減
- ❌ リソース消費増・集約ロジックの複雑さ

---

### 反復ワークフロー（Iterative Workflows）

#### Pattern 4: Loop Pattern
```
Input → [Agent A → Agent B] → condition? → [repeat] or [exit]
```
**いつ使う:**
- 品質基準達成まで繰り返す処理
- データ検証の繰り返し
- 収束するまで実行するアルゴリズム

**ADK 実装:**
```python
from google.adk.workflow import Workflow

loop = Workflow(
    name="Loop",
    edges=[
        ('START', processor, validator, {'RETRY': processor})
    ]
)
```

**⚠️ 必須: `dict` による条件付きエッジが必要（無条件サイクルは v2 で禁止）**

---

#### Pattern 5: Review & Critique Pattern (Loop の特殊形)
```
Input → [Generator] → [Critic] → approved? → Output
                         ↑____________↓ (rejected)
```
**いつ使う:**
- 高精度な出力が必要（コード生成、文書作成）
- セキュリティ/コンプライアンスチェック
- 品質保証が必要なコンテンツ生成

**ADK 実装:**
```python
from google.adk.workflow import Workflow

generator = LlmAgent(name="Generator", output_key="draft", ...)
critic = LlmAgent(
    name="Critic", output_key="feedback",
    instruction="ドラフト: {draft} を評価。改善が必要なら REVISE、承認なら APPROVED を記載"
)

refinement = Workflow(
    name="GenerateCritiqueLoop",
    edges=[
        ('START', generator, critic, {'REVISE': generator})
    ]
)
```

---

#### Pattern 6: Iterative Refinement Pattern (Loop の特殊形)
```
Input → [Agent] → quality_score ≥ threshold? → Output
           ↑__________________________________↓ (not reached)
```
**いつ使う:**
- 段階的に品質を高める複雑な生成タスク
- コード作成とデバッグのサイクル
- 長文ドキュメントの改善

**特徴:** Review & Critique と似ているが、単一エージェントが自己評価しながら改善する点が異なる。

---

### 動的オーケストレーション（Dynamic Orchestration）

#### Pattern 7: ReAct Pattern
```
Input → [Thought] → [Action/Tool] → [Observation] → [Thought] → ... → Output
```
**いつ使う:**
- 動的な計画と適応が必要な複雑タスク
- ロボット制御、動的環境への適応
- 試行錯誤が必要なタスク

**ADK 実装:**
```python
# LlmAgent のデフォルト動作が ReAct パターン
# tools を与えると自動的に Thought→Action→Observation ループ
react_agent = LlmAgent(
    name="ReActAgent",
    model="gemini-3.8-flash",
    instruction="段階的に考えながら行動してください。",
    tools=[search_tool, calculator, database_tool]
)
```

---

#### Pattern 8: Coordinator Pattern
```
                    ┌→ [Specialist A] →┐
User → [Coordinator (LLM)] →           → Response
                    └→ [Specialist B] →┘
```
**いつ使う:**
- 多様な入力タイプのルーティング（カスタマーサポート）
- 適応的なルーティングが必要な構造化ビジネスプロセス
- 専門性の高い異なるタスクの振り分け

**ADK 実装:**
```python
coordinator = LlmAgent(
    name="Coordinator",
    model="gemini-3.8-flash",
    instruction="ユーザーのリクエストを分析し適切な専門エージェントに委譲。",
    sub_agents=[specialist_a, specialist_b, specialist_c]
)
```

**トレードオフ:**
- ✅ 柔軟な動的ルーティング
- ❌ モデル呼び出し増加（コスト・レイテンシ）

---

#### Pattern 9: Hierarchical Task Decomposition Pattern
```
[Root Agent]
    ├── [Coordinator A]
    │       ├── [Worker A1]
    │       └── [Worker A2]
    └── [Coordinator B]
            ├── [Worker B1]
            └── [Worker B2]
```
**いつ使う:**
- 多段階の計画が必要な曖昧でオープンエンドな問題
- 大規模調査・分析・レポート生成
- タスクが複数の段階と専門スキルを必要とする場合

**ADK 実装:**
```python
worker_a = LlmAgent(name="WebResearcher", ...)
worker_b = LlmAgent(name="NewsAnalyzer", ...)
research_coordinator = LlmAgent(
    name="ResearchCoordinator",
    sub_agents=[worker_a, worker_b]
)
report_coordinator = LlmAgent(name="ReportCoordinator", ...)
root = LlmAgent(
    name="Root",
    sub_agents=[research_coordinator, report_coordinator]
)
```

**⚠️ 注意:** 最もコスト・レイテンシが高いパターン。本当に必要な場合のみ使用。

---

#### Pattern 10: Swarm Pattern
```
Dispatcher → [Agent A ↔ Agent B ↔ Agent C] → Consensus
              (all-to-all communication)
```
**いつ使う:**
- 複数視点からのディベートと反復改善
- 創造的な問題解決
- 高品質が最優先でコスト許容

**特徴:**
- 中央コーディネーターなし（分散型）
- エージェント同士が直接通信・議論
- 終了条件: 合意形成またはmax_iterations

**トレードオフ:**
- ✅ 最高品質・創造的解決策
- ❌ 最も複雑・高コスト、収束失敗リスク

---

### 特殊パターン

#### Pattern 11: Human-in-the-Loop Pattern
```
Agent → [Checkpoint] → Human Review → Agent (continue)
```
**いつ使う:**
- 高リスクな意思決定（大規模金融取引）
- 法規制・コンプライアンスが必要
- 主観的判断が必要なクリエイティブ承認

**ADK 実装:**
```python
# ToolContext.actions で Human に委譲
def request_human_approval(data: str, tool_context: ToolContext) -> str:
    # Pub/Sub などで通知
    tool_context.actions.pause_execution = True
    tool_context.state["pending_approval"] = data
    return "承認待ち中..."
```

---

## パターン比較マトリックス

| パターン | コスト | レイテンシ | 複雑性 | 柔軟性 | ADK クラス |
|---|---|---|---|---|---|
| Single Agent | 低 | 低 | 低 | 中 | `LlmAgent` |
| Sequential | 低 | 低 | 低 | 低 | `Workflow`（チェーンタプル） |
| Parallel | 中 | 低 | 中 | 低 | `Workflow`（ネストタプル） |
| Loop | 可変 | 高 | 中 | 中 | `Workflow`（条件付きサイクル） |
| Review/Critique | 中 | 高 | 中 | 中 | `Workflow`（条件付きサイクル） |
| Iterative Refinement | 中 | 高 | 中 | 中 | `Workflow`（条件付きサイクル） |
| ReAct | 中 | 高 | 低 | 高 | `LlmAgent` |
| Coordinator | 高 | 高 | 中 | 高 | `LlmAgent` |
| Hierarchical | 最高 | 最高 | 最高 | 最高 | `LlmAgent` 多層 |
| Swarm | 最高 | 最高 | 最高 | 最高 | `LlmAgent` + A2A |
| Human-in-Loop | 可変 | 最高 | 高 | 中 | カスタム |

---

## パターン選択フローチャート

```
START
  │
  ├─ タスクが単純・単一ステップ？
  │     → Non-agentic (RAG/Prompt のみ)
  │
  ├─ フローが固定されている？
  │   ├─ 線形: Sequential Pattern
  │   ├─ 並列可能: Parallel Pattern  
  │   └─ 繰り返し必要: Loop Pattern
  │
  ├─ 動的なルーティングが必要？
  │   ├─ シンプル + ツール: Single Agent / ReAct
  │   ├─ 複数専門家 + 明確なルール: Coordinator
  │   └─ 多層分解 + 複雑な計画: Hierarchical
  │
  ├─ 品質向上のための反復が必要？
  │   ├─ Generator + Critic: Review & Critique
  │   └─ 自己改善: Iterative Refinement
  │
  ├─ 複数視点でのコンセンサスが必要？
  │     → Swarm Pattern
  │
  └─ 人間の承認が必要？
        → Human-in-the-Loop (他パターンとの組み合わせ)
```

---

## 組み合わせパターン（Custom Logic）

実際の実装では複数パターンを組み合わせることが多い。

```python
from google.adk.workflow import Workflow

# 例: Parallel → Review/Critique → Coordinator の組み合わせ
final_coordinator = LlmAgent(
    name="FinalCoordinator",
    sub_agents=[report_agent, alert_agent, archive_agent]
)

system = Workflow(
    name="EnterpriseSystem",
    edges=[
        # Step 1: 並列データ収集 → Step 2: 品質チェックサイクル → Step 3: ルーティング
        ('START',
         (source_a, source_b, source_c),   # fan-out→fan-in
         synthesizer,
         quality_checker,
         {'REVISE': synthesizer},           # 条件付きサイクル
         final_coordinator                  # Coordinator に委譲
        )
    ]
)
```

---

## 実装における共通ベストプラクティス

```python
# 1. コンテキストエンジニアリング: 各エージェントに必要な情報だけを渡す
agent = LlmAgent(
    instruction="""
    あなたは {agent_role} の専門家です。
    現在のタスク: {current_task}
    前ステップの結果: {previous_output}
    
    制約: {constraints}
    """,
)

# 2. ガードレールを必ず実装
def safety_check_callback(callback_context):
    """全エージェントに共通のセーフティチェック"""
    # 入力検証、PII チェックなど
    pass

# 3. 観測可能性の確保
import logging
logger = logging.getLogger(__name__)

def log_tool_execution(tool, args, context, response):
    logger.info(f"Tool: {tool.name}, Args: {args}, Response: {response}")
    return None  # 元のレスポンスを使用

# 4. 失敗時のフォールバック
agent = LlmAgent(
    instruction="""
    ツールが失敗した場合は、利用可能な情報で最善の回答をしてください。
    失敗した場合は明示的に「[ツール失敗]」と記載してください。
    """,
)
```
