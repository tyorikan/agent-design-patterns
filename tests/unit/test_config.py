"""Lv.1 ユニットテスト: 設定・環境変数の検証。

LLM を呼び出さない決定的テスト。ミリ秒で完了する。
"""

import os
from pathlib import Path

import pytest


ROOT = Path(__file__).parent.parent.parent


class TestEnvExample:
    """`.env.example` ファイルの整合性テスト。"""

    def test_env_example_exists(self):
        """`.env.example` が存在することを確認。"""
        env_example = ROOT / ".env.example"
        assert env_example.exists(), ".env.example が見つかりません"

    def test_env_example_has_required_keys(self):
        """`.env.example` に必要な環境変数が定義されているか確認。"""
        env_example = ROOT / ".env.example"
        content = env_example.read_text()
        required_keys = [
            "GOOGLE_CLOUD_PROJECT",
            "GOOGLE_CLOUD_LOCATION",
            "GOOGLE_GENAI_USE_VERTEXAI",
        ]
        for key in required_keys:
            assert key in content, f".env.example に {key} が定義されていません"


class TestSettings:
    """`shared/config.py` の Settings 検証。"""

    def test_get_settings_returns_settings_instance(self):
        """get_settings() が Settings インスタンスを返すことを確認。"""
        from shared.config import get_settings

        settings = get_settings()
        assert settings is not None
        assert hasattr(settings, "google_cloud_project")
        assert hasattr(settings, "default_model")

    def test_settings_has_valid_model(self):
        """default_model が gemini モデル名を含むことを確認。"""
        from shared.config import get_settings

        settings = get_settings()
        assert "gemini" in settings.default_model, (
            f"default_model が gemini を含んでいません: {settings.default_model}"
        )

    def test_env_vars_synced_to_os_environ(self):
        """Settings の値が os.environ に反映されていることを確認。"""
        from shared.config import get_settings

        get_settings()
        # GOOGLE_GENAI_USE_VERTEXAI が os.environ に設定されているか
        assert "GOOGLE_GENAI_USE_VERTEXAI" in os.environ, (
            "GOOGLE_GENAI_USE_VERTEXAI が os.environ に設定されていません"
        )
