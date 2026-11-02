# AGENTS.md — Grounded RAG & 本番デプロイ規約 (`cli04-grounded-rag-deploy`)

1. 回答に含まれる技術基準には必ず `search_architecture_policies` が返した `[DOC-xxx]` 形式の出典 ID を付記させること。
2. 検索結果が 0 件の場合に一般知識で補完して断定回答することを禁じる（ハルシネーション防止）。
3. `gemini-3.8-flash` 用の `GOOGLE_CLOUD_LOCATION=global` と、Agent Runtime / セッション管理用のリージョン環境変数 `GOOGLE_CLOUD_AGENT_ENGINE_LOCATION` を混同しないこと（`global-aiplatform.googleapis.com` という不正 URL 生成の防止）。
