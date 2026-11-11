"""共通設定モジュール。

Gemini Enterprise Agent Platform（旧 Vertex AI）の ADC（Application Default Credentials）を
使った認証設定と、全エージェントパターンで共有する設定値を提供する。
`@lru_cache` を使って遅延初期化し、テスト時にキャッシュクリアで上書き可能な設計としている。

NOTE: `pydantic_settings` は `.env` から `Settings` オブジェクトへ値を読み込むだけで、
`os.environ` 自体は書き換えない。一方、`google-adk` / `google-genai` は `os.environ` を
直接参照するため、`get_settings()` 内で必要な環境変数の同期（`_sync_env_vars`）を行う。
"""

import os
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# プロジェクトルート（shared/ の親ディレクトリ）
_PROJECT_ROOT = Path(__file__).parent.parent

_VALID_THINKING_LEVELS = {"MINIMAL", "LOW", "MEDIUM", "HIGH"}


class Settings(BaseSettings):
    """アプリケーション共通設定。環境変数または `.env` から読み込む。

    必須:
        GOOGLE_CLOUD_PROJECT: Google Cloud プロジェクト ID
    認証:
        GOOGLE_GENAI_USE_ENTERPRISE=True（デフォルト: ADC を使用して Gemini Enterprise Agent Platform 経由で呼び出す）
    エンドポイント:
        GOOGLE_CLOUD_LOCATION=global（`gemini-3.8-flash` / `gemini-4-argon` は `global` / `us` / `eu` で提供）
    """

    # Google Cloud 設定（必須）
    google_cloud_project: str
    google_cloud_location: str = "global"

    # Gemini Enterprise Agent Platform（旧 Vertex AI）認証フラグ（True = ADC 使用、False = API Key 使用）
    # 既存のローカル .env に旧 GOOGLE_GENAI_USE_VERTEXAI のみ設定されている場合もフォールバックで読み取る
    google_genai_use_enterprise: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "google_genai_use_enterprise",
            "google_genai_use_vertexai",
        ),
    )

    # モデル設定（公開 GA モデル ID: Flash 系=3.8-flash / 軽量系=3.5-flash-lite / 最上位推論=4-argon）
    default_model: str = "gemini-3.8-flash"
    fast_model: str = "gemini-3.5-flash-lite"
    escalation_model: str = "gemini-4-argon"

    # 推論深さ（gemini-3.8-flash / gemini-4-argon は LOW / MEDIUM / HIGH のみ対応。MINIMAL は非対応）
    thinking_level: str = "MEDIUM"

    # エージェント実行ガードレール
    adk_max_llm_calls: int = 500
    max_loop_iterations: int = 5
    agent_temperature: float = 0.1  # 一貫性・再現性を重視

    # PGE ループ設定（agentic_pipeline パターン用）
    approval_threshold: int = 80  # Evaluator 承認スコア閾値（0-100）
    min_improvement: int = 5  # 改善停滞と判定する最低スコア改善幅

    # Antigravity SDK 設定（agentic_pipeline パターン用: 未設定時は Vertex AI ADC を使用）
    gemini_api_key: str | None = None

    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("thinking_level")
    @classmethod
    def _normalize_thinking_level(cls, value: str) -> str:
        """thinking_level を大文字に正規化し、許容値かを検証する。"""
        normalized = value.strip().upper()
        if normalized not in _VALID_THINKING_LEVELS:
            raise ValueError(
                f"thinking_level は {sorted(_VALID_THINKING_LEVELS)} のいずれかを指定してください: {value!r}"
            )
        return normalized

    @model_validator(mode="after")
    def _validate_model_thinking_compatibility(self) -> "Settings":
        """gemini-3.8-flash / gemini-4-argon で非対応の thinking_level='MINIMAL' を事前に検出する。"""
        if (
            self.default_model.startswith(("gemini-3.8-flash", "gemini-4-argon"))
            and self.thinking_level == "MINIMAL"
        ):
            raise ValueError(
                f"{self.default_model} は thinking_level='MINIMAL' に対応していません。"
                " 'LOW' / 'MEDIUM' / 'HIGH' のいずれかを指定してください。"
            )
        return self


def _sync_env_vars(settings: Settings) -> None:
    """ADK および GenAI SDK が `os.environ` から直接参照する環境変数を同期する。

    既に `os.environ` に明示的な値がある場合は上書きしない（シェルでの export を優先）。
    """
    env_mapping: dict[str, str | None] = {
        "GOOGLE_CLOUD_PROJECT": settings.google_cloud_project,
        "GOOGLE_CLOUD_LOCATION": settings.google_cloud_location,
        "GOOGLE_GENAI_USE_ENTERPRISE": str(settings.google_genai_use_enterprise),
        "ADK_MAX_LLM_CALLS": str(settings.adk_max_llm_calls),
        "GEMINI_API_KEY": settings.gemini_api_key,
    }
    for key, value in env_mapping.items():
        if key not in os.environ and value is not None:
            os.environ[key] = value


@lru_cache
def get_settings() -> Settings:
    """設定のシングルトンを取得する。

    テスト時は `get_settings.cache_clear()` でキャッシュを破棄して再読み込みできる。
    """
    settings = Settings()  # type: ignore[call-arg]
    _sync_env_vars(settings)
    return settings
