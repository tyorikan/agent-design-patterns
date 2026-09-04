---
name: adk-python
description: |
  Google Agent Development Kit (ADK) Python を使ったエージェント実装のスキル。
  LlmAgent と Workflow（Sequential / Parallel / Loop）によるオーケストレーション、
  ツール定義、セッション管理、Runner の使い方まで網羅する。
  AI エージェントのデザインパターン実装を担当するエージェントは必ずこのスキルを参照すること。
---

# Google ADK Python スキル

## 概要

**ADK (Agent Development Kit)** は Google が提供するオープンソースの Python フレームワーク。
Gemini モデルを使ったエージェントの定義・オーケストレーション・デプロイを体系化する。

- **バージョン**: ADK Python 2.8.0 (2026-08-25 リリース)
- **PyPI**: `google-adk`
- **GitHub**: https://github.com/google/adk-python
- **公式ドキュメント**: https://adk.dev / https://google.github.io/adk-docs/

---

## インストール & セットアップ

```bash
# uv を使う場合（推奨）
uv add "google-adk>=2.8.0"
uv add "google-genai>=2.22.0"  # Vertex AI / Google AI Studio 共通 SDK

# pip を使う場合
pip install "google-adk>=2.8.0"
```

### 環境変数

```bash
# Vertex AI (ADC / Service Account 使用 - 推奨)
export GOOGLE_CLOUD_PROJECT="your-project-id"
export GOOGLE_CLOUD_LOCATION="global"       # グローバルエンドポイント（推奨）
export GOOGLE_GENAI_USE_VERTEXAI="True"

# LLM 呼び出し上限（v2.8.0 で追加。デフォルト 500）
export ADK_MAX_LLM_CALLS="500"

# Google AI Studio (API Key 使用)
export GOOGLE_API_KEY="your-api-key"
```

### ADK プロジェクト構造（最小構成）

```
my_agent/
├── __init__.py
├── agent.py          # root_agent 変数が必須
└── .env              # 環境変数
```

---

## エージェントタイプ

### 1. LlmAgent（基本・最重要）

LLM が自律的に思考・ツール選択・行動を行うエージェント。

```python
from google.adk.agents import LlmAgent
from google.adk.tools import google_search

root_agent = LlmAgent(
    name="my_agent",
    model="gemini-3.8-flash",          # モデル名
    description="エージェントの説明（他エージェントからの参照に使われる）",
    instruction="""
    あなたは役立つアシスタントです。
    ユーザーの質問に対して、必要であれば検索ツールを使って回答してください。
    """,
    tools=[google_search],             # ツールリスト
    output_key="result",               # セッション状態に保存するキー
)
```

**重要パラメータ:**
| パラメータ | 型 | 説明 |
|---|---|---|
| `name` | str | エージェントの一意な識別子 |
| `model` | str | 使用する Gemini モデル名 |
| `description` | str | 他エージェントが参照する能力の説明 |
| `instruction` | str | システムプロンプト |
| `tools` | list | 使用可能なツールのリスト |
| `output_key` | str | セッション状態への保存キー |
| `sub_agents` | list | 委譲先サブエージェント |
| `generate_content_config` | GenerateContentConfig | モデル設定（temperature, thinking_config など） |

---

### Thinking Level の設定

Gemini 3.x 系モデルでは **Thinking Level** を指定して推論の深さを制御できる。
複雑なタスク（コード分析、数学的推論、多段階計画）では `HIGH` を推奨。

```python
from google.adk.agents import LlmAgent
from google.genai.types import GenerateContentConfig, ThinkingConfig

# Thinking Level = HIGH で深い推論を有効化
agent = LlmAgent(
    name="DeepReasoningAgent",
    model="gemini-3.8-flash",
    instruction="複雑な問題を段階的に分析し、論理的に回答してください。",
    generate_content_config=GenerateContentConfig(
        thinking_config=ThinkingConfig(
            thinking_level="HIGH"       # LOW / MEDIUM / HIGH
        ),
        temperature=0.1,
        max_output_tokens=8192,
    ),
    tools=[...],
)
```

**Thinking Level 一覧:**
| レベル | 用途 | トレードオフ |
|---|---|---|
| `LOW` | 高速応答優先。シンプルなタスク | 低レイテンシ・低コスト |
| `MEDIUM` | バランス型（デフォルト相当） | 中程度 |
| `HIGH` | 深い推論。コード分析・数学・複雑計画 | 高精度だがレイテンシ・Thinking Token 増加 |

> **⚠️ 注意:** Thinking Level を使う場合、`google-genai` パッケージが v1.51.0 以上であることを確認。
> ADK v2.8.0 以降では `generate_content_config` に `ThinkingConfig` を直接渡せる。

---

### 2. Workflow — Sequential（順次実行）

複数のエージェントをチェーンタプルで順番に実行する。前のエージェントの出力が次のエージェントの入力になる。

```python
from google.adk.agents import LlmAgent
from google.adk.workflow import Workflow

# 各エージェントは output_key でセッション状態に結果を保存
step1 = LlmAgent(
    name="Extractor",
    model="gemini-3.8-flash",
    instruction="与えられたデータから重要な情報を抽出してください。",
    output_key="extracted_data"        # state["extracted_data"] に保存
)

step2 = LlmAgent(
    name="Cleaner",
    model="gemini-3.8-flash",
    instruction="""
    以下のデータをクリーニングしてください:
    {extracted_data}                   # state から参照
    """,
    output_key="clean_data"
)

step3 = LlmAgent(
    name="Loader",
    model="gemini-3.8-flash",
    instruction="クリーニング済みデータ: {clean_data} を適切な形式で保存してください。",
)

# チェーンタプル: START → step1 → step2 → step3
pipeline = Workflow(
    name="ETLPipeline",
    edges=[('START', step1, step2, step3)]
)
```

**特徴:**
- LLM によるオーケストレーション不要（低コスト・低レイテンシ）
- 固定された線形フロー
- `output_key` と instruction の `{key}` でデータ受け渡し
- Workflow は `BaseNode` のサブクラス（`sub_agents` には入れられない）

---

### 3. Workflow — Parallel（並列実行）

複数のエージェントをネストタプルで fan-out / fan-in する。

```python
from google.adk.agents import LlmAgent
from google.adk.workflow import Workflow

# 独立した調査エージェント群（並列実行）
market_agent = LlmAgent(
    name="MarketResearcher",
    model="gemini-3.8-flash",
    instruction="市場トレンドを調査してください。",
    output_key="market_data"
)

competitor_agent = LlmAgent(
    name="CompetitorAnalyzer",
    model="gemini-3.8-flash",
    instruction="競合他社の動向を分析してください。",
    output_key="competitor_data"
)

customer_agent = LlmAgent(
    name="CustomerInsight",
    model="gemini-3.8-flash",
    instruction="顧客フィードバックを分析してください。",
    output_key="customer_data"
)

# 集約エージェント
synthesizer = LlmAgent(
    name="Synthesizer",
    model="gemini-3.8-flash",
    instruction="""
    以下の調査結果を統合して包括的なレポートを作成してください:
    - 市場データ: {market_data}
    - 競合データ: {competitor_data}
    - 顧客データ: {customer_data}
    """,
)

# ネストタプルで fan-out → fan-in
research_system = Workflow(
    name="ResearchSystem",
    edges=[
        ('START', (market_agent, competitor_agent, customer_agent), synthesizer)
    ]
)
```

**特徴:**
- 独立したタスクを同時実行でレイテンシ削減
- 各エージェントは異なる `output_key` を使う必要がある
- ネストタプル `(a, b, c)` で並列実行、次のノードが集約ステップになる

---

### 4. Workflow — Loop（条件付きサイクル）

条件付きエッジ（`dict`）を使い、条件を満たすまでサイクルする。
v2 では **無条件サイクルは禁止** — 必ず `dict` による条件付きエッジが必要。

```python
from google.adk.agents import LlmAgent
from google.adk.workflow import Workflow

writer = LlmAgent(
    name="Writer",
    model="gemini-3.8-flash",
    instruction="""
    以下のトピックについてドラフトを書いてください: {topic}
    
    前回のフィードバックがある場合は考慮してください: {feedback}
    改善されたドラフトを output_key に保存してください。
    品質が十分であれば、レスポンスの最後に "[APPROVED]" を追加してください。
    """,
    output_key="draft"
)

critic = LlmAgent(
    name="Critic",
    model="gemini-3.8-flash",
    instruction="""
    以下のドラフトを評価してください: {draft}
    
    改善点がある場合は "REVISE" を、品質が十分な場合は "APPROVED" と記載してください。
    """,
    output_key="feedback"
)

# 条件付きサイクル: critic の結果が "REVISE" なら writer に戻る
refinement_loop = Workflow(
    name="WriterRoom",
    edges=[
        ('START', writer, critic, {'REVISE': writer})  # 条件付きエッジ
    ]
)
```

**⚠️ 重要: 条件付きエッジの設計**
- `dict` のキーはエージェントの出力テキストに含まれるキーワード
- キーワードにマッチしない場合はサイクルを終了（次のエッジまたは END へ進む）
- 無条件サイクル（`dict` なし）は v2 では禁止

```python
# 複数条件を持つパターン
workflow = Workflow(
    name="MultiConditionLoop",
    edges=[
        ('START', processor, validator, {
            'RETRY': processor,   # バリデーション失敗 → 再処理
            'ESCALATE': escalation_agent  # エスカレーション
        })  # どちらにもマッチしない → 正常終了
    ]
)
```

---

## ツール定義

### 1. 関数ツール (FunctionTool) - 最も基本的

```python
from google.adk.tools import FunctionTool

def get_weather(city: str) -> dict:
    """指定した都市の天気を取得します。
    
    Args:
        city: 天気を取得する都市名
        
    Returns:
        天気情報を含む辞書
    """
    # 実際の実装
    return {"city": city, "temperature": 25, "condition": "晴れ"}

# 関数を直接 tools リストに渡す（自動で FunctionTool に変換）
agent = LlmAgent(
    name="WeatherAgent",
    model="gemini-3.8-flash",
    instruction="天気情報を取得して報告してください。",
    tools=[get_weather]               # 関数を直接渡す
)
```

**型アノテーションとdocstringは必須！** ADK は型情報とdocstringからツールスキーマを自動生成する。

### 2. セッション状態にアクセスするツール

```python
from google.adk.tools import ToolContext

def save_to_session(data: str, tool_context: ToolContext) -> str:
    """データをセッション状態に保存します。
    
    Args:
        data: 保存するデータ
        tool_context: ADK が自動的に注入するコンテキスト（引数リストに含めない）
    """
    tool_context.state["saved_data"] = data
    return f"データを保存しました: {data}"
```

### 3. 組み込みツール

```python
from google.adk.tools import google_search, code_execution

agent = LlmAgent(
    name="ResearchAgent",
    model="gemini-3.8-flash",
    instruction="調査と計算を行います。",
    tools=[
        google_search,           # Google 検索
        code_execution,          # Python コード実行
    ]
)
```

### 4. MCP ツール

```python
from google.adk.tools.mcp_tool import MCPToolset, SseServerParams, StdioServerParams

# SSE 接続の MCP サーバー
mcp_tools = MCPToolset(
    connection_params=SseServerParams(uri="http://localhost:8001/sse")
)

# stdio 接続の MCP サーバー
mcp_tools = MCPToolset(
    connection_params=StdioServerParams(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    )
)

agent = LlmAgent(
    name="Agent",
    model="gemini-3.8-flash",
    instruction="MCP ツールを使って作業してください。",
    tools=[mcp_tools]
)
```

---

## Runner とセッション管理

### ローカル開発（InMemorySessionService）

```python
import asyncio
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

async def run_agent():
    # セッションサービスの初期化
    session_service = InMemorySessionService()
    
    # セッションの作成
    session = await session_service.create_session(
        app_name="my_agent",
        user_id="user_001",
        session_id="session_001"
    )
    
    # Runner の初期化
    runner = Runner(
        agent=root_agent,
        app_name="my_agent",
        session_service=session_service
    )
    
    # エージェントの実行
    async for event in runner.run_async(
        user_id="user_001",
        session_id="session_001",
        new_message=types.Content(
            role="user",
            parts=[types.Part(text="こんにちは！")]
        )
    ):
        if event.is_final_response():
            print(event.content.parts[0].text)

asyncio.run(run_agent())
```

### 本番環境（VertexAiSessionService）

```python
from google.adk.sessions import VertexAiSessionService

session_service = VertexAiSessionService(
    project=GOOGLE_CLOUD_PROJECT,
    location=GOOGLE_CLOUD_LOCATION
)
```

### セッション状態のスコープ

| プレフィックス | スコープ | 例 |
|---|---|---|
| (なし) | 現在のセッション | `state["draft"]` |
| `user:` | ユーザー全セッション共通 | `state["user:preferences"]` |
| `app:` | アプリ全体共通 | `state["app:config"]` |
| `temp:` | 現在のターンのみ | `state["temp:working"]` |

---

## マルチエージェント（Coordinator パターン）

LLM がダイナミックにルーティングを行うパターン。

```python
from google.adk.agents import LlmAgent

# 専門エージェント
order_agent = LlmAgent(
    name="OrderAgent",
    model="gemini-3.8-flash",
    description="注文状況の確認を担当します。注文番号に関する質問に答えます。",
    instruction="注文番号を確認して状況を報告してください。",
    tools=[check_order_status]
)

refund_agent = LlmAgent(
    name="RefundAgent",
    model="gemini-3.8-flash",
    description="返金処理を担当します。返金リクエストを処理します。",
    instruction="返金条件を確認して処理してください。",
    tools=[process_refund]
)

# Coordinator（LLM が自動ルーティング）
coordinator = LlmAgent(
    name="CustomerServiceCoordinator",
    model="gemini-3.8-flash",
    description="カスタマーサービスのコーディネーター",
    instruction="""
    ユーザーのリクエストを分析し、適切な専門エージェントに委譲してください。
    - 注文確認 → OrderAgent
    - 返金 → RefundAgent
    直接対応できない場合のみ回答してください。
    """,
    sub_agents=[order_agent, refund_agent]    # サブエージェントとして登録
)
```

---

## コールバック（Callback）

```python
from google.adk.agents.callback_context import CallbackContext
from google.genai import types

def before_model_callback(callback_context: CallbackContext) -> types.Content | None:
    """モデル呼び出し前のフック。None を返すと通常通り続行。"""
    # 入力の検証や変換
    return None

def after_tool_callback(
    tool, 
    tool_args: dict, 
    tool_context: ToolContext,
    tool_response: dict
) -> dict | None:
    """ツール実行後のフック。None を返すと元のレスポンスを使用。"""
    # ツール結果の加工や記録
    return None

agent = LlmAgent(
    name="SafeAgent",
    model="gemini-3.8-flash",
    instruction="...",
    before_model_callback=before_model_callback,
    after_tool_callback=after_tool_callback,
)
```

---

## ローカル開発コマンド

```bash
# Web UI で対話的にテスト
adk web

# CLI で実行
adk run my_agent

# API サーバーを起動
adk api_server

# 評価
adk eval my_agent eval_data.json
```

---

## デプロイ

### Cloud Run へのデプロイ

```bash
# agent ディレクトリ構造:
# my_agent/
# ├── __init__.py     # root_agent を expose
# ├── agent.py
# └── requirements.txt

adk deploy cloud_run \
  --project=$GOOGLE_CLOUD_PROJECT \
  --region=us-central1 \
  --service-name=my-agent \
  my_agent/
```

### Vertex AI Agent Engine へのデプロイ

```bash
adk deploy agent_engine \
  --project=$GOOGLE_CLOUD_PROJECT \
  --region=us-central1 \
  my_agent/
```

---

## ベストプラクティス

### DO ✅
1. **単一責任**: 各エージェントは1つの役割のみ持つ
2. **型アノテーション**: ツール関数には必ず型ヒントとdocstringを書く
3. **条件付きエッジ**: Workflow の Loop には必ず `dict` による条件付きエッジを使う
4. **output_key**: Workflow でのデータ受け渡しに使う
5. **@lru_cache**: 設定オブジェクトとクライアント初期化に使う
6. **非同期**: `run_async` を使い、同期版は避ける
7. **description**: サブエージェントには必ず説明を書く（LLM のルーティングに使われる）
8. **Thinking Level**: 複雑なタスクには `ThinkingConfig(thinking_level="HIGH")` を設定する
9. **ADK_MAX_LLM_CALLS**: 本番環境では LLM 呼び出し上限を設定して暴走を防ぐ
10. **location=global**: Vertex AI では `GOOGLE_CLOUD_LOCATION=global` でグローバルエンドポイントを使う

### DON'T ❌
1. **モノリシックプロンプト**: 1つのエージェントに多くの責務を持たせない
2. **無条件サイクル**: Workflow の Loop で `dict` を省略しない（v2 では禁止）
3. **状態共有の競合**: Parallel Workflow で同じ output_key を使わない
4. **本番での InMemorySessionService**: スケール時に状態が失われる
5. **sub_agents に Workflow を入れない**: Workflow は `BaseNode` であり `BaseAgent` ではない
6. **Thinking Level を無条件に HIGH にしない**: リアルタイム応答が必要な場面では LOW/MEDIUM を使う

---

## よくあるパターン別クイックリファレンス

```python
from google.adk.agents import LlmAgent
from google.adk.workflow import Workflow

# パターン1: Single Agent
agent = LlmAgent(name="Agent", model="gemini-3.8-flash", instruction="...", tools=[...])

# パターン2: Sequential (A → B → C)  ※チェーンタプル
Workflow(name="Pipeline", edges=[('START', a, b, c)])

# パターン3: Parallel (A || B || C) → D  ※ネストタプル fan-out/fan-in
Workflow(name="FanOutIn", edges=[('START', (a, b, c), d)])

# パターン4: Loop (A → B → 条件付きサイクル)  ※dict による条件付きエッジ
Workflow(name="Loop", edges=[('START', a, b, {'REVISE': a})])

# パターン5: Coordinator (LLM がルーティング)
LlmAgent(instruction="...", sub_agents=[specialist_a, specialist_b])

# パターン6: Hierarchical (root → coordinator → workers)
root = LlmAgent(sub_agents=[coordinator])
coordinator = LlmAgent(sub_agents=[worker_a, worker_b])
```
