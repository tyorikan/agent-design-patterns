---
name: agents-cli-deploy-runtime
description: >
  agents-cli を使った Agent Runtime (旧 Agent Engine) へのデプロイと、
  Cloud Run → Agent Runtime の連携パターンのスキル。
metadata:
  author: Yori
  version: 1.0.0
  source: https://github.com/google/agents-cli
  requires:
    bins:
      - agents-cli
    install: "uv tool install google-agents-cli"
---

# agents-cli Deploy to Agent Runtime

> **前提:** `agents-cli` v1.12+ がインストール済みであること。
> インストール: `uv tool install "google-agents-cli>=1.12.0"`

## 1. agents-cli のプロジェクト構造（必須要件）

Agent Runtime にデプロイするには、`agents-cli` が期待するプロジェクト構造に合わせる必要がある。

### 必須ファイル

```
project-root/
├── .agents-cli-spec.md           # Spec-Driven Agent 仕様書（推奨）
├── AGENTS.md                     # AI エージェント向けコーディング規約
├── app/                          # agents-cli が認識するエントリーポイント
│   ├── __init__.py               # `app` (ADK App インスタンス) をエクスポート
│   ├── agent.py                  # `root_agent` と `app = App(root_agent=..., name="app")`
│   └── fast_api_app.py           # FastAPI エントリーポイント（uvicorn が起動するファイル）
├── agents-cli-manifest.yaml      # agents-cli 1.12+ プロジェクト設定ファイル
├── pyproject.toml
├── Dockerfile                    # コンテナビルド用
└── .env                          # 環境変数（Git 管理対象外）
```

### agents-cli-manifest.yaml（agents-cli 1.12+ 準拠）

```yaml
name: my-agent
acli_version: "1.12.0"
agent_directory: app
region: us-central1
base_template: adk_python
language: python
framework: google-adk
create_params:
  root_agent_name: root_agent
  deployment_target: agent_runtime
  session_type: in_memory
  cicd_runner: google_cloud_build
  is_a2a: false
  agent_gateway: false
  agent_guidance_filename: AGENTS.md
  agent_runtime:
    identity_default: service_account
```

### app/__init__.py

```python
"""App entrypoint. agents-cli は `app/__init__.py` から ADK `App` を参照する。"""
from app.agent import app

__all__ = ["app"]
```

### app/fast_api_app.py

Agent Runtime はコンテナ内で `uvicorn app.fast_api_app:app` を実行する。
ADK の `get_fast_api_app()` を使うか、自前の FastAPI app を定義する。

```python
from google.adk.cli.fast_api import get_fast_api_app

# agents_dir は agent 定義の親ディレクトリを指定
# (例: agents_dir="agent" → ./agent/agent.py を読む)
app = get_fast_api_app(agents_dir="agent", web=True)
```

**カスタム FastAPI app の場合:**

```python
from google.adk.cli.fast_api import get_fast_api_app

# ADK のエンドポイントを含む FastAPI app（68+ ルートが自動生成される）
app = get_fast_api_app(agents_dir="agent", web=True)

# カスタムエンドポイントを追加
@app.get("/health")
async def health():
    return {"status": "healthy"}
```

## 2. デプロイコマンド

### Agent Runtime へのデプロイ

```bash
# 基本デプロイ
agents-cli deploy \
  --project your-project-id \
  --region us-central1 \
  --deployment-target agent_runtime \
  --no-confirm-project

# 環境変数付きデプロイ
agents-cli deploy \
  --project your-project-id \
  --region us-central1 \
  --deployment-target agent_runtime \
  --update-env-vars "KEY1=value1,GOOGLE_CLOUD_PROJECT=your-project-id" \
  --service-name "my-agent" \
  --memory 4Gi \
  --cpu 2 \
  --no-confirm-project

# デプロイ状況確認（タイムアウトした場合）
agents-cli deploy --status

# 既存デプロイ一覧
agents-cli deploy --list

# ドライラン（実行内容の確認のみ）
agents-cli deploy --dry-run
```

### 重要なフラグ

| Flag | 説明 | デフォルト |
|------|------|-----------|
| `--project` | GCP プロジェクト ID | gcloud 設定 |
| `--region` | GCP リージョン | us-central1 |
| `--deployment-target` | `agent_runtime` / `cloud_run` / `gke` | manifest.yaml |
| `--service-name` | Agent Runtime の表示名 | プロジェクト名 |
| `--service-account` | SA メールアドレス | — |
| `--update-env-vars` | 環境変数 (`KEY=VALUE,...`) | — |
| `--secrets` | シークレット (`ENV=SECRET,...`) | — |
| `--memory` | メモリ上限 | 4Gi |
| `--cpu` | CPU 上限 | 1 |
| `--min-instances` | 最小インスタンス | 0 |
| `--max-instances` | 最大インスタンス | 10 |
| `--concurrency` | コンテナ当たりの同時リクエスト数 | 8 |
| `--no-confirm-project` | プロジェクト確認プロンプトをスキップ | — |
| `--no-wait` | デプロイ開始後即座にリターン | — |

### タイムアウト対策

Agent Runtime のデプロイは 5-10 分かかることがある。タイムアウトしてもサーバー側でデプロイは継続する。

```bash
# デプロイ開始（バックグラウンド）
agents-cli deploy --no-wait

# 60秒ごとにステータス確認
agents-cli deploy --status
```

## 3. Agent Runtime の HTTP パススルー

Agent Runtime にデプロイされたコンテナの HTTP ルートは、以下の URL パターンでアクセスできる：

```
https://{location}-aiplatform.googleapis.com/reasoningEngines/v1/{resource}/api/{container_path}
```

- `{resource}`: `projects/{project}/locations/{location}/reasoningEngines/{id}`
- `{container_path}`: コンテナ内の任意の HTTP パス

### Cloud Run → Agent Runtime の連携

Cloud Run (Event Handler) から Agent Runtime にデプロイされた Agent を呼び出す方法：

#### 方法 1: `agents-cli run` で直接テスト

```bash
# ADK モードで Agent Runtime にクエリ
agents-cli run \
  --url https://LOCATION-aiplatform.googleapis.com/v1/projects/PROJECT/locations/LOCATION/reasoningEngines/ID \
  --mode adk \
  "Hello, what can you do?"
```

#### 方法 2: Python (google-genai SDK) でリモート呼び出し

```python
from google import genai

client = genai.Client(
    vertexai=True,
    project="your-project-id",
    location="us-central1",
)

# Agent Runtime のリソース名を指定してクエリ
# リソース名は `agents-cli deploy` の出力から取得
response = client.models.generate_content(
    model="projects/{project}/locations/{location}/reasoningEngines/{id}",
    contents="Hello, what can you do?",
)
```

#### 方法 3: REST API (curl / requests) で直接呼び出し

```bash
# トークン取得
TOKEN=$(gcloud auth print-access-token)

# Agent Runtime の /api パススルーで ADK エンドポイントにアクセス
curl -X POST \
  "https://LOCATION-aiplatform.googleapis.com/reasoningEngines/v1/projects/PROJECT/locations/LOCATION/reasoningEngines/ID/api/run_sse" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "app_name": "my-agent",
    "user_id": "user-001",
    "session_id": "test-session",
    "new_message": {
      "role": "user",
      "parts": [{"text": "Hello, what can you do?"}]
    }
  }'
```

## 4. Cloud Run Event Handler → Agent Runtime の実装パターン

```python
"""Agent Runtime (Agent Engine) へのリモートクライアント。"""

import google.auth
import google.auth.transport.requests
import requests

AGENT_RUNTIME_ENDPOINT = (
    "https://{location}-aiplatform.googleapis.com"
    "/reasoningEngines/v1/{resource}/api/run_sse"
)

def call_agent_runtime(
    resource_name: str,
    location: str,
    app_name: str,
    user_id: str,
    session_id: str,
    message: str,
) -> str:
    """Agent Runtime にデプロイされた Agent を呼び出す。"""
    credentials, _ = google.auth.default()
    credentials.refresh(google.auth.transport.requests.Request())

    url = AGENT_RUNTIME_ENDPOINT.format(
        location=location,
        resource=resource_name,
    )

    payload = {
        "app_name": app_name,
        "user_id": user_id,
        "session_id": session_id,
        "new_message": {
            "role": "user",
            "parts": [{"text": message}],
        },
    }

    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {credentials.token}",
            "Content-Type": "application/json",
        },
        json=payload,
        stream=True,
    )
    response.raise_for_status()

    # SSE レスポンスを処理
    result = ""
    for line in response.iter_lines():
        if line:
            decoded = line.decode("utf-8")
            if decoded.startswith("data:"):
                # JSON パース + テキスト抽出
                import json
                data = json.loads(decoded[5:])
                if "content" in data and "parts" in data["content"]:
                    for part in data["content"]["parts"]:
                        if "text" in part:
                            result += part["text"]
    return result
```

## 5. デプロイ検証

```bash
# 1. デプロイ完了確認
agents-cli deploy --status

# 2. Agent Runtime のテスト
agents-cli run \
  --url "AGENT_RUNTIME_URL" \
  --mode adk \
  "Hello, what can you do?"

# 3. ヘルスチェック（カスタムエンドポイント）
curl -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  "AGENT_RUNTIME_URL/api/health"
```

## 6. トラブルシューティング

| 症状 | 原因 | 対策 |
|------|------|------|
| デプロイがタイムアウト | Agent Runtime は 5-10 分かかる | `agents-cli deploy --status` で確認 |
| `agents-cli-manifest.yaml` がない | プロジェクト初期化未実施 | 手動作成するか `agents-cli scaffold enhance . --deployment-target agent_runtime` |
| 認証エラー | SA に権限がない | `roles/aiplatform.user`, `roles/bigquery.dataViewer` 等を付与 |
| `app.fast_api_app` が見つからない | プロジェクト構造が不正 | `app/fast_api_app.py` に FastAPI `app` をエクスポート |
| コンテナビルド失敗 | Dockerfile が不正 | `agents-cli deploy --dry-run` でコマンド確認 |
