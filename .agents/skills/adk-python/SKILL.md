---
name: adk-python
description: |
  Google Agent Development Kit (ADK) Python を使ったエージェント実装のスキル。
  LlmAgent、SequentialAgent、ParallelAgent、LoopAgent などのエージェントタイプ、
  ツール定義、セッション管理、Runner の使い方まで網羅する。
  AI エージェントのデザインパターン実装を担当するエージェントは必ずこのスキルを参照すること。
---

# Google ADK Python スキル

## 概要

**ADK (Agent Development Kit)** は Google が提供するオープンソースの Python フレームワーク。
Gemini モデルを使ったエージェントの定義・オーケストレーション・デプロイを体系化する。

- **バージョン**: ADK Python 2.0 GA (2026 年現在最新)
- **PyPI**: `google-adk`
- **GitHub**: https://github.com/google/adk-python
- **公式ドキュメント**: https://adk.dev / https://google.github.io/adk-docs/

---

## インストール & セットアップ

```bash
# uv を使う場合（推奨）
uv add google-adk
uv add google-cloud-aiplatform  # Vertex AI 使用時

# pip を使う場合
pip install google-adk
```

### 環境変数

```bash
# Vertex AI (ADC / Service Account 使用 - 推奨)
export GOOGLE_CLOUD_PROJECT="your-project-id"
export GOOGLE_CLOUD_LOCATION="us-central1"
export GOOGLE_GENAI_USE_VERTEXAI="True"

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
    model="gemini-2.0-flash",          # モデル名
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
| `generate_content_config` | GenerateContentConfig | モデル設定（temperature など） |

---

### 2. SequentialAgent（順次実行）

複数のサブエージェントを順番に実行する。前のエージェントの出力が次のエージェントの入力になる。

```python
from google.adk.agents import SequentialAgent, LlmAgent

# 各エージェントは output_key でセッション状態に結果を保存
step1 = LlmAgent(
    name="Extractor",
    model="gemini-2.0-flash",
    instruction="与えられたデータから重要な情報を抽出してください。",
    output_key="extracted_data"        # state["extracted_data"] に保存
)

step2 = LlmAgent(
    name="Cleaner",
    model="gemini-2.0-flash",
    instruction="""
    以下のデータをクリーニングしてください:
    {extracted_data}                   # state から参照
    """,
    output_key="clean_data"
)

step3 = LlmAgent(
    name="Loader",
    model="gemini-2.0-flash",
    instruction="クリーニング済みデータ: {clean_data} を適切な形式で保存してください。",
)

pipeline = SequentialAgent(
    name="ETLPipeline",
    description="データ抽出・クリーニング・ロードのパイプライン",
    sub_agents=[step1, step2, step3]
)
```

**特徴:**
- LLM によるオーケストレーション不要（低コスト・低レイテンシ）
- 固定された線形フロー
- `output_key` と instruction の `{key}` でデータ受け渡し

---

### 3. ParallelAgent（並列実行）

複数のサブエージェントを同時並行で実行する。

```python
from google.adk.agents import ParallelAgent, LlmAgent, SequentialAgent

# 独立した調査エージェント群（並列実行）
market_agent = LlmAgent(
    name="MarketResearcher",
    model="gemini-2.0-flash",
    instruction="市場トレンドを調査してください。",
    output_key="market_data"
)

competitor_agent = LlmAgent(
    name="CompetitorAnalyzer",
    model="gemini-2.0-flash",
    instruction="競合他社の動向を分析してください。",
    output_key="competitor_data"
)

customer_agent = LlmAgent(
    name="CustomerInsight",
    model="gemini-2.0-flash",
    instruction="顧客フィードバックを分析してください。",
    output_key="customer_data"
)

# 集約エージェント
synthesizer = LlmAgent(
    name="Synthesizer",
    model="gemini-2.0-flash",
    instruction="""
    以下の調査結果を統合して包括的なレポートを作成してください:
    - 市場データ: {market_data}
    - 競合データ: {competitor_data}
    - 顧客データ: {customer_data}
    """,
)

# 並列実行 → 集約のパイプライン
research_system = SequentialAgent(
    name="ResearchSystem",
    sub_agents=[
        ParallelAgent(
            name="ParallelResearcher",
            sub_agents=[market_agent, competitor_agent, customer_agent]
        ),
        synthesizer
    ]
)
```

**特徴:**
- 独立したタスクを同時実行でレイテンシ削減
- 各サブエージェントは異なる `output_key` を使う必要がある
- gather（集約）ステップには SequentialAgent を組み合わせる

---

### 4. LoopAgent（ループ実行）

終了条件を満たすまで、サブエージェントのシーケンスを繰り返す。

```python
from google.adk.agents import LoopAgent, LlmAgent

writer = LlmAgent(
    name="Writer",
    model="gemini-2.0-flash",
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
    model="gemini-2.0-flash",
    instruction="""
    以下のドラフトを評価してください: {draft}
    
    改善点を指摘してください。品質が十分な場合は "[APPROVED]" と記載してください。
    """,
    output_key="feedback"
)

# max_iterations で無限ループを防止（必須！）
refinement_loop = LoopAgent(
    name="WriterRoom",
    description="ドラフト生成と批評のループ",
    sub_agents=[writer, critic],
    max_iterations=5                   # 最大反復回数（必ず設定）
)
```

**⚠️ 重要: 終了条件の設計**
```python
# カスタム終了条件を使うパターン
from google.adk.agents.callback_context import CallbackContext

def check_approval_callback(callback_context: CallbackContext):
    """[APPROVED] が含まれたら早期終了"""
    state = callback_context.state
    feedback = state.get("feedback", "")
    if "[APPROVED]" in feedback:
        callback_context.actions.escalate = True  # ループを終了
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
    model="gemini-2.0-flash",
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
    model="gemini-2.0-flash",
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
    model="gemini-2.0-flash",
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
    model="gemini-2.0-flash",
    description="注文状況の確認を担当します。注文番号に関する質問に答えます。",
    instruction="注文番号を確認して状況を報告してください。",
    tools=[check_order_status]
)

refund_agent = LlmAgent(
    name="RefundAgent",
    model="gemini-2.0-flash",
    description="返金処理を担当します。返金リクエストを処理します。",
    instruction="返金条件を確認して処理してください。",
    tools=[process_refund]
)

# Coordinator（LLM が自動ルーティング）
coordinator = LlmAgent(
    name="CustomerServiceCoordinator",
    model="gemini-2.0-flash",
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
    model="gemini-2.0-flash",
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
3. **max_iterations**: LoopAgent には必ず設定する
4. **output_key**: SequentialAgent/ParallelAgent でのデータ受け渡しに使う
5. **@lru_cache**: 設定オブジェクトとクライアント初期化に使う
6. **非同期**: `run_async` を使い、同期版は避ける
7. **description**: サブエージェントには必ず説明を書く（LLM のルーティングに使われる）

### DON'T ❌
1. **モノリシックプロンプト**: 1つのエージェントに多くの責務を持たせない
2. **無限ループ**: LoopAgent に max_iterations を忘れない
3. **状態共有の競合**: ParallelAgent で同じ output_key を使わない
4. **本番での InMemorySessionService**: スケール時に状態が失われる

---

## よくあるパターン別クイックリファレンス

```python
# パターン1: Single Agent
agent = LlmAgent(name="Agent", model="gemini-2.0-flash", instruction="...", tools=[...])

# パターン2: Sequential (A → B → C)
SequentialAgent(name="Pipeline", sub_agents=[a, b, c])

# パターン3: Parallel (A || B || C) → D
SequentialAgent(sub_agents=[ParallelAgent(sub_agents=[a, b, c]), d])

# パターン4: Loop (A → B まで繰り返し)
LoopAgent(sub_agents=[a, b], max_iterations=5)

# パターン5: Coordinator (LLM がルーティング)
LlmAgent(instruction="...", sub_agents=[specialist_a, specialist_b])

# パターン6: Hierarchical (root → coordinator → workers)
root = LlmAgent(sub_agents=[coordinator])
coordinator = LlmAgent(sub_agents=[worker_a, worker_b])
```
