"""共通設定モジュール。

Vertex AI ADC を使った認証設定と、全エージェントで共有する設定値を提供する。
@lru_cache を使って遅延初期化し、テスト時にオーバーライド可能な設計。

NOTE: pydantic_settings は .env → Settings オブジェクトに読み込むだけで
os.environ には反映しない。ADK (google.genai.Client) は os.environ を
直接参照するため、get_settings() で環境変数の同期も行う。
"""

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# プロジェクトルート（shared/ の親ディレクトリ）
_PROJECT_ROOT = Path(__file__).parent.parent


class Settings(BaseSettings):
    """アプリケーション設定。環境変数から自動的に読み込む。

    必須: GOOGLE_CLOUD_PROJECT
    認証: GOOGLE_GENAI_USE_VERTEXAI=True (ADK 側で自動的に Vertex AI を使用)
    """

    # Google Cloud 設定（必須）
    google_cloud_project: str
    google_cloud_location: str = "us-central1"

    # Vertex AI 認証フラグ（True = ADC 使用、False = API Key 使用）
    google_genai_use_vertexai: bool = True

    # モデル設定
    default_model: str = "gemini-3.5-flash"

    # エージェント設定
    max_loop_iterations: int = 5
    agent_temperature: float = 0.1  # 一貫性重視

    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


def _sync_env_vars(settings: Settings) -> None:
    """ADK が os.environ から直接参照する環境変数を同期する。

    pydantic_settings は .env → Settings に読み込むだけで os.environ には
    反映しないため、ADK が必要とする変数を明示的にセットする。
    既に os.environ に値がある場合は上書きしない（明示的な export を優先）。
    """
    env_mapping = {
        "GOOGLE_CLOUD_PROJECT": settings.google_cloud_project,
        "GOOGLE_CLOUD_LOCATION": settings.google_cloud_location,
        "GOOGLE_GENAI_USE_VERTEXAI": str(settings.google_genai_use_vertexai),
    }
    for key, value in env_mapping.items():
        if key not in os.environ:
            os.environ[key] = value


@lru_cache
def get_settings() -> Settings:
    """設定のシングルトンを取得する。

    テスト時は lru_cache をクリアして上書き可能:
        get_settings.cache_clear()
    """
    settings = Settings()
    _sync_env_vars(settings)
    return settings

