---
name: vertex-ai-adk-setup
description: |
  Vertex AI を使った Google ADK エージェントのセットアップ・認証・モデル設定のスキル。
  Google Cloud プロジェクト設定、ADC 認証、Vertex AI API の有効化、
  Cloud Run へのデプロイまでの環境構築手順を提供する。
  ADK プロジェクトの初期セットアップ時に必ず参照すること。
---

# Vertex AI + ADK セットアップスキル

## 概要

Google ADK を Vertex AI と組み合わせて使うための環境構築手順。
Vertex AI を使うことで、エンタープライズグレードのセキュリティ・スケーラビリティ・観測可能性が得られる。

---

## 前提条件

- Google Cloud プロジェクト（請求有効）
- Python 3.10+
- gcloud CLI
- uv（推奨）または pip

---

## Step 1: Google Cloud 設定

```bash
# プロジェクト設定
export PROJECT_ID="your-project-id"
export REGION="global"  # グローバルエンドポイント（推奨。データ残留要件がある場合は us-central1 等を指定）

gcloud config set project $PROJECT_ID
gcloud config set compute/region $REGION

# 必要な API を有効化
gcloud services enable \
  aiplatform.googleapis.com \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com
```

## Step 2: 認証（ADC）

```bash
# ローカル開発: Application Default Credentials を設定
gcloud auth application-default login

# または Service Account を使う場合
gcloud iam service-accounts create adk-agent-sa \
  --display-name="ADK Agent Service Account"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:adk-agent-sa@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"

# キーをダウンロード（本番では Secret Manager を使う）
gcloud iam service-accounts keys create key.json \
  --iam-account="adk-agent-sa@${PROJECT_ID}.iam.gserviceaccount.com"

export GOOGLE_APPLICATION_CREDENTIALS="./key.json"
```

## Step 3: Python プロジェクト初期化（uv）

```bash
# uv でプロジェクト作成
uv init my-agent
cd my-agent

# 依存関係を追加
uv add "google-adk>=2.8.0"
uv add "google-genai>=2.22.0"

# 開発用
uv add --dev pytest pytest-asyncio ruff mypy
```

## Step 4: 環境変数設定

```bash
# .env ファイルに記載（.gitignore に追加必須！）
cat > .env << EOF
GOOGLE_CLOUD_PROJECT=${PROJECT_ID}
GOOGLE_CLOUD_LOCATION=global
GOOGLE_GENAI_USE_VERTEXAI=True
ADK_MAX_LLM_CALLS=500
EOF
```

## Step 5: 設定管理（config.py）

```python
# shared/config.py
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """アプリケーション設定。環境変数から読み込む。"""
    
    google_cloud_project: str
    google_cloud_location: str = "global"
    google_genai_use_vertexai: bool = True
    
    # モデル設定
    default_model: str = "gemini-3.8-flash"
    
    # Thinking Level (LOW / MEDIUM / HIGH)
    thinking_level: str = "MEDIUM"
    
    # LLM 呼び出し上限 (ADK v2.8.0+)
    adk_max_llm_calls: int = 500
    
    # エージェント設定
    max_loop_iterations: int = 5
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    """設定のシングルトン取得（テスト時は lru_cache をクリアして上書き可能）"""
    return Settings()
```

## Step 6: 動作確認

```bash
# ADK Web UI でテスト
uv run adk web

# または CLI でテスト
uv run adk run my_agent

# 型チェック
uv run mypy .

# リント
uv run ruff check .
```

---

## 利用可能なモデル

| モデル | 用途 | コスト |
|---|---|---|
| `gemini-3.8-flash` | 高速・高精度（最新推奨） | 低 |
| `gemini-3.8-flash` + `thinking_level=HIGH` | 深い推論が必要な複雑タスク | 中 |
| `gemini-3.5-flash` | フォールバック用 | 低 |

> **Note:** gemini-3.8-flash は `location=global` で利用可能。
> Thinking Level は旧 `-thinking` モデル名の代わりに `ThinkingConfig` で制御する。

```python
from google.genai.types import GenerateContentConfig, ThinkingConfig

# 標準設定（高速応答）
agent = LlmAgent(
    model="gemini-3.8-flash",
    generate_content_config=GenerateContentConfig(
        temperature=0.1,
        max_output_tokens=8192,
        top_p=0.95,
    )
)

# 深い推論が必要なタスク（Thinking Level = HIGH）
deep_agent = LlmAgent(
    model="gemini-3.8-flash",
    generate_content_config=GenerateContentConfig(
        thinking_config=ThinkingConfig(
            thinking_level="HIGH"  # LOW / MEDIUM / HIGH
        ),
        temperature=0.1,
        max_output_tokens=8192,
    )
)
```

---

## Cloud Run へのデプロイ

```bash
# agent/ ディレクトリ構造
# agent/
# ├── __init__.py   → root_agent を expose
# ├── agent.py
# └── requirements.txt

# ADK コマンドでデプロイ（推奨）
adk deploy cloud_run \
  --project=$PROJECT_ID \
  --region=$REGION \
  --service-name=my-agent \
  agent/

# または手動でデプロイ
gcloud run deploy my-agent \
  --source . \
  --region $REGION \
  --set-env-vars GOOGLE_CLOUD_PROJECT=$PROJECT_ID \
  --set-env-vars GOOGLE_CLOUD_LOCATION=$REGION \
  --set-env-vars GOOGLE_GENAI_USE_VERTEXAI=True \
  --allow-unauthenticated
```

---

## トラブルシューティング

```bash
# 認証エラー
gcloud auth application-default login --scopes=https://www.googleapis.com/auth/cloud-platform

# API 有効化確認
gcloud services list --enabled | grep aiplatform

# 権限確認
gcloud projects get-iam-policy $PROJECT_ID \
  --flatten="bindings[].members" \
  --filter="bindings.members:user:$(gcloud config get account)"
```
