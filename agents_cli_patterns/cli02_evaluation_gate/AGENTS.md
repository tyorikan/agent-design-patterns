# AGENTS.md — 継続的評価ゲート（Evaluation Gate）規約 (`cli02-evaluation-gate`)

1. プロンプトやツールを変更した際は、必ず `agents-cli eval run`（または `eval grade`）を実行し、`scripts/ci_eval_gate.py` が終了コード `0` を返すことを確認すること。
2. 新しい障害・誤回答パターンを発見した場合は、修正前に `tests/eval/datasets/basic-dataset.json` に再現ケースを追加すること。
3. LLM-as-a-Judge（`tests/eval/response_quality.py`）のモデル名は退役済みモデルをハードコードせず、現行 GA モデル（`gemini-4-hydrogen`）または環境変数 `EVAL_JUDGE_MODEL` を使用すること。
