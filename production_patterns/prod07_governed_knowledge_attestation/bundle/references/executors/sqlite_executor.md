# SQLite Computation Executor 仕様

`production_patterns/prod07_governed_knowledge_attestation/attestation.py` の
`SqliteComputationExecutor` が提供する承認済み SQL 実行契約です。

- 宣言済みパラメータを SQLite 名前付きプレースホルダ (`:name`) で安全に束縛して実行します。
- 実行ごとに一意の `job_id` と結果行の SHA-256 ダイジェストを権威ジョブログへ記録します。
- 本番環境では `ComputationExecutor` Protocol を実装した BigQuery / dbt 実行器へ差し替えます。
