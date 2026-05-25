---
name: a2a-protocol
description: |
  Agent-to-Agent (A2A) プロトコルを使った異エージェント間通信の実装スキル。
  A2A サーバー/クライアントの構築、Agent Card の設計、タスクライフサイクル管理、
  Google ADK との統合パターンを網羅する。
  クロスフレームワーク・クロスベンダーのマルチエージェント通信が必要な場合に参照すること。
---

# A2A Protocol スキル

## 概要

**A2A (Agent-to-Agent)** は Google が 2025 年 4 月に提案し、Linux Foundation に寄贈したオープン標準プロトコル。
異なるフレームワーク・ベンダー間の AI エージェントが安全に協調動作するための「共通言語」として機能する。

- **仕様**: https://a2a-protocol.org / https://github.com/google/A2A
- **役割**: MCP がエージェントとツールを繋ぐのに対し、**A2A はエージェントとエージェントを繋ぐ**
- **ADK との関係**: Google ADK は A2A をネイティブサポート

```
┌─────────────────────────────────────────────────────────┐
│                    エージェントエコシステム               │
│                                                         │
│  Agent A (ADK)  ←──── A2A ────→  Agent B (LangGraph)  │
│       │                                  │             │
│       └──── MCP ────→ Tool / DB / API ←──┘             │
└─────────────────────────────────────────────────────────┘
```

---

## プロトコル仕様

### 通信方式

| 要素 | 仕様 |
|---|---|
| **ペイロード** | JSON-RPC 2.0 |
| **トランスポート** | HTTP/HTTPS (同期) + Server-Sent Events (ストリーミング) |
| **認証** | OAuth 2.0 / API Keys / mTLS |
| **アーキテクチャ** | クライアント・サーバーモデル |

### アーキテクチャ構成

```
┌──────────────────┐              ┌──────────────────┐
│   A2A Client     │              │   A2A Server     │
│ (Orchestrator)   │              │ (Remote Agent)   │
│                  │  JSON-RPC    │                  │
│  - タスク作成    │──────────→  │  - Agent Card    │
│  - 状態監視      │←──────────  │  - /run エンドポイント│
│  - 結果取得      │  SSE Stream │  - タスク処理    │
└──────────────────┘              └──────────────────┘
```

---

## Agent Card

エージェントの「名刺」。エージェントの能力・エンドポイント・認証方式を記述する JSON ファイル。

```json
{
  "name": "Research Agent",
  "description": "Web 検索と情報収集を専門とするエージェント",
  "version": "1.0.0",
  "url": "https://my-agent.example.com",
  "defaultInputModes": ["text"],
  "defaultOutputModes": ["text"],
  "capabilities": {
    "streaming": true,
    "pushNotifications": false,
    "stateTransitionHistory": true
  },
  "skills": [
    {
      "id": "web_search",
      "name": "Web 検索",
      "description": "インターネットから情報を検索します",
      "inputModes": ["text"],
      "outputModes": ["text"]
    }
  ],
  "authentication": {
    "schemes": ["ApiKey"]
  }
}
```

Agent Card は通常 `/.well-known/agent.json` エンドポイントで公開する。

---

## タスクライフサイクル

```
submitted → working → {completed | failed | canceled}
                ↕
           input-required (Human-in-the-Loop 時)
```

| 状態 | 説明 |
|---|---|
| `submitted` | タスク受付済み |
| `working` | 処理中 |
| `input-required` | ユーザー入力待ち（Human-in-the-Loop） |
| `completed` | 正常完了 |
| `failed` | エラー終了 |
| `canceled` | キャンセル |

---

## ADK での A2A 実装

### A2A Server（エージェントを外部公開）

```python
# agent.py
from google.adk.agents import LlmAgent
from google.adk.tools import google_search

# ADK エージェントを定義
research_agent = LlmAgent(
    name="ResearchAgent",
    model="gemini-2.0-flash",
    description="Web 検索と情報収集を担当する専門エージェント",
    instruction="""
    ユーザーのリクエストに基づいて Web 検索を行い、
    正確で包括的な情報を提供してください。
    """,
    tools=[google_search],
)

# A2A Server として公開
# server.py
from google.adk.a2a.utils.agent_to_a2a import to_a2a

# ADK エージェントを A2A 準拠の FastAPI アプリに変換
app = to_a2a(research_agent)

# uvicorn server:app --host 0.0.0.0 --port 8001 で起動
```

### A2A Client（他エージェントを呼び出す）

```python
import httpx
import json

async def call_remote_agent(
    agent_url: str,
    task_description: str
) -> str:
    """A2A プロトコルでリモートエージェントを呼び出す"""
    
    payload = {
        "jsonrpc": "2.0",
        "method": "tasks/send",
        "id": "task_001",
        "params": {
            "message": {
                "role": "user",
                "parts": [{"text": task_description}]
            }
        }
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{agent_url}/run",
            json=payload,
            headers={"Authorization": f"Bearer {API_KEY}"}
        )
        result = response.json()
        return result["result"]["artifacts"][0]["parts"][0]["text"]
```

### ADK エージェントからリモートエージェントをツールとして呼び出す

```python
from google.adk.agents import LlmAgent
from google.adk.tools.agent_tool import AgentTool

# リモートの A2A エージェントをツールとして定義
remote_research_tool = AgentTool(
    agent_card_url="https://research-agent.example.com/.well-known/agent.json"
)

# オーケストレーターエージェント
orchestrator = LlmAgent(
    name="Orchestrator",
    model="gemini-2.0-flash",
    instruction="""
    複雑なタスクを受け取り、適切な専門エージェントに委譲してください。
    調査タスクは Research Agent に委譲してください。
    """,
    tools=[remote_research_tool]
)
```

---

## Python SDK を使った完全な A2A サーバー実装

```python
# a2a_server.py
from typing import AsyncIterable
import uvicorn
from fastapi import FastAPI
from google.adk.a2a.models import (
    AgentCard,
    AgentCapabilities,
    AgentSkill,
    Task,
    TaskState,
    Message,
    Part,
)

# Agent Card の定義
AGENT_CARD = AgentCard(
    name="DataAnalysisAgent",
    description="データ分析と可視化を専門とするエージェント",
    version="1.0.0",
    url="https://data-agent.example.com",
    capabilities=AgentCapabilities(
        streaming=True,
        push_notifications=False,
    ),
    skills=[
        AgentSkill(
            id="analyze_data",
            name="データ分析",
            description="CSV/JSON データを分析してインサイトを提供します",
            input_modes=["text", "data"],
            output_modes=["text", "data"],
        )
    ]
)

app = FastAPI()

@app.get("/.well-known/agent.json")
async def get_agent_card():
    """Agent Card を公開するエンドポイント"""
    return AGENT_CARD

@app.post("/run")
async def run_task(request: dict):
    """タスクを受け取って処理するエンドポイント"""
    task_id = request.get("id")
    message = request["params"]["message"]
    user_text = message["parts"][0]["text"]
    
    # エージェントの処理
    result = await process_with_agent(user_text)
    
    return {
        "jsonrpc": "2.0",
        "id": task_id,
        "result": {
            "id": task_id,
            "status": {"state": TaskState.COMPLETED},
            "artifacts": [
                {
                    "parts": [{"text": result}]
                }
            ]
        }
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
```

---

## ADK + A2A の統合アーキテクチャ（Cloud Run）

```
┌──────────────────────────────────────────────────────┐
│                   Cloud Run                          │
│  ┌────────────────────────────────────────────────┐  │
│  │      Orchestrator Agent (ADK + A2A Client)     │  │
│  │                                                │  │
│  │  root_agent = LlmAgent(                       │  │
│  │      sub_agents=[                             │  │
│  │          AgentTool(research_agent_url),        │  │
│  │          AgentTool(analysis_agent_url),        │  │
│  │      ]                                        │  │
│  │  )                                            │  │
│  └────────────────┬───────────────────────────────┘  │
└───────────────────│──────────────────────────────────┘
                    │ A2A (HTTP/SSE)
        ┌───────────┴───────────┐
        ▼                       ▼
┌──────────────┐      ┌──────────────────┐
│ Cloud Run    │      │  Cloud Run       │
│ Research     │      │  Analysis        │
│ Agent (A2A)  │      │  Agent (A2A)     │
└──────────────┘      └──────────────────┘
```

---

## セキュリティ考慮事項

```python
# API Key 認証の実装
from fastapi import HTTPException, Header

async def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != EXPECTED_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

# OAuth 2.0 の場合はAgent Card に記載
AGENT_CARD_WITH_AUTH = AgentCard(
    ...
    authentication={
        "schemes": ["Bearer"],
        "credentials": {
            "type": "oauth2",
            "authorizationUrl": "https://accounts.google.com/o/oauth2/auth",
            "tokenUrl": "https://oauth2.googleapis.com/token",
            "scopes": {"https://www.googleapis.com/auth/cloud-platform": "Cloud Platform"}
        }
    }
)
```

---

## ベストプラクティス

### DO ✅
1. **Agent Card を常に最新に保つ**: 能力変更時は必ず更新
2. **タイムアウトの設定**: 長時間タスクには適切なタイムアウトを設定
3. **エラーハンドリング**: タスク失敗時の理由を明確に返す
4. **認証**: 本番環境では必ず認証を実装
5. **ヘルスチェック**: `/health` エンドポイントを用意
6. **冪等性**: 同じタスク ID で再送された場合の処理を考慮

### DON'T ❌
1. **平文通信**: 本番では必ず HTTPS
2. **認証なし公開**: ローカル以外では認証必須
3. **同期的な長時間処理**: ストリーミングまたは非同期で応答
4. **不明確な Agent Card**: 曖昧な capability 記述は避ける

---

## ADK vs A2A の使い分け

| シナリオ | 推奨 |
|---|---|
| 単一プロセス内の複数エージェント | ADK の `sub_agents` |
| 異なるサービス間の連携 | A2A |
| 異なるフレームワーク間の連携 | A2A |
| 既存の外部エージェントの利用 | A2A |
| シンプルなマイクロサービス連携 | A2A |
