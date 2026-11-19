# SQL Equality Attester 仕様

`production_patterns/prod07_governed_knowledge_attestation/attestation.py` の
`SqlEqualityAttester` が提供する非 LLM 決定論的検証契約です。

1. `job_id` を用いて実行器側の権威ジョブログを直接参照します。
2. 実行された SQL を正規化し、OKF Concept の `# Computation` と完全一致することを確認します。
3. 束縛パラメータおよび結果行の SHA-256 ダイジェスト一致を検証し、`ok` / `reason` / `receipt_ref` を返します。
