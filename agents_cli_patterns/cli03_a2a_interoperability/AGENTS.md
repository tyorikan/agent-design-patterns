# AGENTS.md — A2A 相互運用エージェント開発規約 (`cli03-a2a-interoperability`)

1. `root_agent` の `description` と各ツールの docstring は、`AgentCardBuilder` によって外部公開用の `AgentCard`（スキル一覧）へ自動変換されるため、社内用語や曖昧な略語を使わず自己説明的に記述すること。
2. ADK Web ルートと A2A JSON-RPC ルートでセッション不整合を起こさないよう、必ず `app/app_utils/services.py` の `shared://session` を共有すること。
3. 本番公開時は無認証公開（`--allow-unauthenticated`）を避け、Cloud Run IAM または Agent Gateway で呼び出し元サービスアカウントを制限すること。
