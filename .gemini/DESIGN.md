# AI Agent Design Patterns - システム詳細設計書

## アーキテクチャ概要

```
agent-design-patterns/
├── .agents/skills/                  # スキル定義（AI 駆動開発の知識ベース）
│   ├── adk-python/SKILL.md          # ADK Python 実装スキル
│   ├── agent-design-patterns/SKILL.md  # デザインパターン選択ガイド
│   ├── a2a-protocol/SKILL.md        # A2A プロトコルスキル
│   ├── vertex-ai-adk-setup/SKILL.md # セットアップスキル
│   └── adk-testing-debugging/SKILL.md  # テスト・デバッグスキル
│
├── shared/                          # 共通ライブラリ
│   ├── __init__.py
│   ├── config.py                    # Settings + @lru_cache
│   └── demo_runner.py               # デモ実行共通ユーティリティ
│
├── patterns/                        # デザインパターン実装
│   ├── 01_single_agent/
│   │   ├── README.md                # 概念説明・アーキテクチャ図・実行方法
│   │   ├── agent.py                 # エージェント定義（root_agent を export）
│   │   └── demo.py                  # デモシナリオ（自動実行）
│   ├── 02_react_pattern/
│   ├── ...
│   ├── 11_human_in_the_loop/
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
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    google_cloud_project: str
    google_cloud_location: str = "us-central1"
    google_genai_use_vertexai: bool = True
    default_model: str = "gemini-3.5-flash"
    max_loop_iterations: int = 5
    agent_temperature: float = 0.1

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

@lru_cache
def get_settings() -> Settings:
    return Settings()
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
| LLM | Vertex AI Gemini 3.5 Flash |
| エージェント間通信 | A2A Protocol（スキル定義のみ） |
| セッション管理 | ADK InMemorySessionService |
| UI | ADK Web UI (`adk web`) |
| コンテナ | Docker + docker-compose |
| テスト | pytest + pytest-asyncio |
| リント | ruff |
| 型チェック | mypy |
