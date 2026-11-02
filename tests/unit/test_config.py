"""Lv.1 ユニットテスト: 設定・環境変数の検証。

LLM を呼び出さない決定的テスト。ミリ秒で完了する。
"""

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).parent.parent.parent


class TestEnvExample:
    """`.env.example` ファイルの整合性テスト。"""

    def test_env_example_exists(self) -> None:
        """`.env.example` が存在することを確認。"""
        env_example = ROOT / ".env.example"
        assert env_example.exists(), ".env.example が見つかりません"

    def test_env_example_has_required_keys(self) -> None:
        """`.env.example` に必要な環境変数と最新モデル設定が定義されているか確認。"""
        env_example = ROOT / ".env.example"
        content = env_example.read_text(encoding="utf-8")
        required_keys = [
            "GOOGLE_CLOUD_PROJECT",
            "GOOGLE_CLOUD_LOCATION=global",
            "GOOGLE_GENAI_USE_VERTEXAI=True",
            "DEFAULT_MODEL=gemini-3.8-flash",
            "FAST_MODEL=gemini-3.5-flash-lite",
            "ADK_MAX_LLM_CALLS=500",
        ]
        for key in required_keys:
            assert key in content, f".env.example に {key} が定義されていません"


class TestSettings:
    """`shared/config.py` の Settings 検証。"""

    def test_get_settings_returns_settings_instance(self) -> None:
        """get_settings() が Settings インスタンスを返し、最新デフォルト値を持つことを確認。"""
        from shared.config import get_settings

        get_settings.cache_clear()
        settings = get_settings()
        assert settings is not None
        assert settings.google_cloud_location == "global"
        assert settings.default_model == "gemini-3.8-flash"
        assert settings.fast_model == "gemini-3.5-flash-lite"
        assert settings.thinking_level == "MEDIUM"
        assert settings.adk_max_llm_calls == 500

    def test_settings_has_valid_model(self) -> None:
        """default_model が gemini モデル名を含むことを確認。"""
        from shared.config import get_settings

        settings = get_settings()
        assert "gemini" in settings.default_model, (
            f"default_model が gemini を含んでいません: {settings.default_model}"
        )

    def test_rejects_minimal_thinking_on_gemini_3_8_flash(self) -> None:
        """gemini-3.8-flash で非対応の thinking_level='MINIMAL' が事前拒否されることを確認。"""
        from shared.config import Settings

        with pytest.raises(ValidationError, match="MINIMAL"):
            Settings(
                google_cloud_project="unit-test-project",
                default_model="gemini-3.8-flash",
                thinking_level="MINIMAL",
            )

    def test_allows_minimal_thinking_on_flash_lite(self) -> None:
        """gemini-3.5-flash-lite 等では thinking_level='MINIMAL' が許容されることを確認。"""
        from shared.config import Settings

        s = Settings(
            google_cloud_project="unit-test-project",
            default_model="gemini-3.5-flash-lite",
            thinking_level="minimal",
        )
        assert s.thinking_level == "MINIMAL"

    def test_env_vars_synced_to_os_environ(self) -> None:
        """Settings の値が os.environ に反映されていることを確認。"""
        from shared.config import get_settings

        get_settings.cache_clear()
        get_settings()
        assert "GOOGLE_GENAI_USE_ENTERPRISE" in os.environ
        assert "GOOGLE_GENAI_USE_VERTEXAI" in os.environ
        assert "ADK_MAX_LLM_CALLS" in os.environ
