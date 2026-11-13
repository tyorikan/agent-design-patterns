# AGENTS.md — 開発・保守ガイドライン (`cli01-spec-driven-agent`)

このプロジェクトは Spec-Driven Agent パターンに従っています。コードを変更する前に必ず `.agents-cli-spec.md` を確認し、仕様と実装の乖離を防いでください。

## 厳守事項
1. **仕様ファースト**: ツールの入出力や対象スコープを変更する場合は、先に `.agents-cli-spec.md` を更新してから `app/agent.py` を編集すること。
2. **暗算の禁止**: エラーバジェットや割合の計算をプロンプト内推論で行わせず、必ず `calculate_error_budget` ツールを通すこと。
3. **モデル・ロケーション規約**: `gemini-4-hydrogen` は `GOOGLE_CLOUD_LOCATION=global`（または `us` / `eu`）で実行すること。`thinking_level` は `LOW` / `MEDIUM` / `HIGH` / `XHIGH` を使用し、`MINIMAL` は指定しないこと。
4. **`App` エクスポート規約**: `agents-cli` 互換性を維持するため、`app/__init__.py` から `app`（`google.adk.apps.App` インスタンス）をエクスポートし続けること。
