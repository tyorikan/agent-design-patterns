# AI Agent Design Patterns - システム詳細設計書

## アーキテクチャ概要

```
agent-design-patterns/
├── .agents/skills/                  # スキル定義（AI 駆動開発の知識ベース）
│   ├── adk-python/SKILL.md          # ADK Python 実装スキル
│   ├── agent-design-patterns/SKILL.md  # デザインパターン選択ガイド
│   ├── a2a-protocol/SKILL.md        # A2A プロトコルスキル
│   ├── vertex-ai-adk-setup/SKILL.md # セットアップスキル
│   ├── adk-testing-debugging/SKILL.md  # テスト・デバッグスキル
│   ├── agentic-pipeline/SKILL.md    # PGE 自律コード生成パイプラインスキル
│   └── ai-agent-testing-strategy/SKILL.md  # AI エージェントテスト戦略スキル
│
├── shared/                          # 共通ライブラリ
│   ├── __init__.py
│   ├── config.py                    # Settings + @lru_cache
│   ├── calculator.py                # 単純演算ユーティリティ
│   └── demo_runner.py               # デモ実行共通ユーティリティ
│
├── patterns/                        # デザインパターン実装
│   ├── p01_single_agent/
│   │   ├── README.md                # 概念説明・アーキテクチャ図・実行方法
│   │   ├── agent.py                 # エージェント定義（root_agent を export）
│   │   └── demo.py                  # デモシナリオ（自動実行）
│   ├── p02_react_pattern/
│   ├── ...
│   ├── p11_human_in_the_loop/
│   ├── agentic_pipeline/            # PGE 自律コード生成パイプライン
│   │   ├── agent.py                 # BaseAgent ベースの PGE オーケストレータ
│   │   ├── tools.py                 # Antigravity Agent ラッパーツール群
│   │   ├── prompts.py               # Planner/Generator/Evaluator プロンプト
│   │   ├── schemas.py               # EvalResult 等の Pydantic スキーマ
│   │   └── demo.py                  # デモシナリオ
│   └── capstone/                    # 全パターン統合の最終形態
│
├── tests/                           # テストピラミッド
│   ├── README.md                    # テスト戦略ドキュメント
│   ├── unit/                        # Lv.1: 決定的テスト（LLM なし、約1秒）
│   │   ├── test_config.py           # 設定・環境変数の検証
│   │   └── test_agent_structure.py   # 全12パターンのエージェント構成検証
│   └── integration/                 # Lv.2: 統合テスト（実 LLM、約13分）
│       └── test_patterns.py         # プロパティベース + トラジェクトリ検証
│
├── docs/                            # プロジェクトドキュメント
│   └── v1-to-v2-migration-guide.md  # ADK v1→v2 移行ガイド
│
├── CONTRIBUTING.md                  # コントリビューションガイド
├── Dockerfile                       # コンテナイメージ
├── docker-compose.yml               # ADK Web UI 起動設定
├── pyproject.toml                   # パッケージ設定
├── conftest.py                      # テスト共通ヘルパー
└── .env.example                     # 環境変数テンプレート
```

## 共通設計パターン

### 設定管理 (shared/config.py)

```python
import os
from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).parent.parent

class Settings(BaseSettings):
    google_cloud_project: str
    google_cloud_location: str = "us-central1"
    google_genai_use_vertexai: bool = True
    default_model: str = "gemini-3.5-flash"
    max_loop_iterations: int = 5
    agent_temperature: float = 0.1

    # PGE ループ設定
    approval_threshold: int = 80   # Evaluator スコア閾値（0-100）
    min_improvement: int = 5       # 改善停滞と判定する最低改善幅

    # Antigravity SDK 設定
    gemini_api_key: str | None = None

    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

def _sync_env_vars(settings: Settings) -> None:
    """ADK が os.environ から直接参照する変数を同期する。"""
    env_mapping = {
        "GOOGLE_CLOUD_PROJECT": settings.google_cloud_project,
        "GOOGLE_CLOUD_LOCATION": settings.google_cloud_location,
        "GOOGLE_GENAI_USE_VERTEXAI": str(settings.google_genai_use_vertexai),
        "GEMINI_API_KEY": settings.gemini_api_key,
    }
    for key, value in env_mapping.items():
        if key not in os.environ and value is not None:
            os.environ[key] = value

@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    _sync_env_vars(settings)
    return settings
```

### 各パターンディレクトリの構成

```
XX_pattern_name/
├── README.md       # 概念説明・アーキテクチャ図・トレードオフ・学習ポイント
├── agent.py        # エージェント定義（root_agent を export）
└── demo.py         # デモシナリオ（自動実行）
```

テストは `tests/unit/` と `tests/integration/` に集約（`tests/README.md` 参照）。

### テスト共通パターン (conftest.py)

```python
# conftest.py に定義された共通ヘルパー

def load_pattern_agent(pattern_dir: str) -> ModuleType:
    """パターンの agent.py を importlib.util で安全にロード。"""
    ...

async def run_agent_final_response(agent, app_name, query) -> str:
    """is_final_response() のテキストを取得。LlmAgent 単体用。"""
    ...

async def run_agent_all_text(agent, app_name, query) -> str:
    """全イベントからテキスト収集。Workflow 系用。"""
    ...

async def run_agent_trajectory(agent, app_name, query) -> tuple[str, list[str]]:
    """テキスト + 発言エージェント一覧を取得。トラジェクトリ検証用。"""
    ...
```

## 技術スタック

| 層 | 技術 |
|---|---|
| 言語 | Python 3.12+ |
| パッケージ管理 | pip (pyproject.toml) + uv (Docker) |
| エージェントフレームワーク | Google ADK Python 2.1+ (Workflow API) |
| 自律エージェント SDK | Antigravity SDK (google-antigravity) |
| LLM | Vertex AI Gemini 3.5 Flash |
| エージェント間通信 | A2A Protocol（スキル定義のみ） |
| セッション管理 | ADK InMemorySessionService |
| UI | ADK Web UI (`adk web`) |
| コンテナ | Docker + docker-compose |
| テスト | pytest + pytest-asyncio |
| リント | ruff |
| 型チェック | mypy |
