# テスト戦略

このドキュメントでは、AI エージェントデザインパターンプロジェクトのテスト戦略と、それにより保証される挙動を説明する。

## なぜ LLM エージェントのテストは難しいのか

従来のソフトウェアテストは **決定的** — 同じ入力に対して同じ出力が期待される。
しかし LLM エージェントは **非決定的** — 同じプロンプトでも毎回異なるテキストを返す。

```
❌ 従来のアプローチ（不安定）
assert "スコア" in response  # LLM の揺らぎ次第で PASS/FAIL が変わる

✅ このプロジェクトのアプローチ（安定）
1. Lv.1 決定的テスト: エージェント構成検証 + ScriptedLlm(BaseLlm) によるインプロセス Runner 分岐検証
2. Lv.2 統合テスト:   実モデル呼び出しに対するプロパティ検証（長さ・構造）+ トラジェクトリ検証（行動経路）
```

## テストピラミッド

```
        ▲ コスト・時間（高）
       / \
      / Lv.2 \      統合テスト（実 LLM、プロパティ + トラジェクトリ）
     /─────────\
    /   Lv.1    \   ユニットテスト（外部通信ゼロ、構成 + ScriptedLlm 全分岐検証）
   /─────────────\
        ▼ 速度・信頼性（高）
```

| レベル | ディレクトリ | 外部 LLM 呼出 | 実行時間 | テスト数 |
|--------|-------------|--------------|---------|---------|
| **Lv.1** | `tests/unit/` | ❌ なし（`ScriptedLlm` インプロセス実行を含む） | **約 4 秒** | 98 |
| **Lv.2** | `tests/integration/` | ✅ あり（Gemini Enterprise Agent Platform / Vertex AI） | **約 25 分** | 29 |

---

## Lv.1 ユニットテスト（決定的・高速）

**外部 LLM API を一切呼び出さない。** エージェントのグラフ構成、ツール入出力契約、および決定論的 `ScriptedLlm(BaseLlm)` ダブルを用いた ADK `Runner` の全分岐を検証する。

### 実行方法

```bash
.venv/bin/pytest tests/unit/ -v
```

### テストファイル一覧

| ファイル | 対象トラック | 検証内容 |
|---|---|---|
| `test_config.py` | `shared/` | `.env.example` 整合性、`gemini-3.8-flash` + `global` 既定値、`GOOGLE_GENAI_USE_ENTERPRISE` 同期、思考レベル互換チェック |
| `test_agent_structure.py` | `patterns/` | 全 13 パターン（Lv.1〜11 + Capstone + Agentic Pipeline）の ADK 2.x `Workflow` グラフ構造・サイクル・サブエージェント構成 |
| `test_agents_cli_patterns.py` | `agents_cli_patterns/` | CLI-01〜CLI-04 の `agent.yaml` / `eval_config.json` 整合性、ツール単体検証、A2A Agent Card 配信、CI 評価ゲート終了コード |
| `test_production_patterns.py` | `production_patterns/` | PROD-01〜PROD-06 の `ScriptedLlm` インプロセス実行（事前拒否、リトライ、冪等性台帳、HITL 一時停止/再開、検疫、Rogan–Gladen 補正、`pass^k`、`ArtifactService` 退避、同期予算遮断） |

---

## Lv.2 統合テスト（実 LLM・プロパティ + トラジェクトリ）

**実際に Gemini モデルを呼び出して** 全 3 トラックのエージェント動作を検証する。

### 実行方法

```bash
# GOOGLE_CLOUD_PROJECT 設定・ADC 認証済みの環境で実行
.venv/bin/pytest tests/integration/ -v
```

### 2 つの検証アプローチ

1. **プロパティベーステスト**: 具体的な文言ではなく、出力長・構造・機密文字列の非露出などの性質を検証する。
2. **トラジェクトリ検証**: `run_agent_trajectory()` で実際に発火したノード・サブエージェントの経路を検証する。

---

## 共通ヘルパー（`conftest.py`）

| 関数 | 用途 |
|------|------|
| `load_pattern_agent(dir)` | `patterns/<dir>/agent.py` をロード |
| `load_cli_pattern_agent(dir)` | `agents_cli_patterns/<dir>/app/agent.py` をロード |
| `load_production_pattern_agent(dir)` | `production_patterns/<dir>/agent.py` をロード |
| `run_agent_final_response()` | `LlmAgent` / `App` の最終応答テキストを取得（`initial_state` 注入・`ArtifactService` 対応） |
| `run_agent_all_text()` | `Workflow` を含む全イベント・ノード出力を収集 |
| `run_agent_trajectory()` | 応答テキストと発言ノード/エージェント一覧（順序付き）を取得 |

---

## テスト実行コマンド

```bash
# Lv.1 のみ（高速、CI の必須ステップ）
.venv/bin/pytest tests/unit/ -v

# Lv.2 のみ（実 LLM 統合テスト）
.venv/bin/pytest tests/integration/ -v

# 収集確認（テストを実行せずに全件ロードを検証）
.venv/bin/pytest tests/ --co
```
