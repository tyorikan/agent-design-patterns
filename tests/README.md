# テスト戦略

このドキュメントでは、AI エージェントデザインパターンプロジェクトのテスト戦略と、それにより保証される挙動を説明する。

## なぜ LLM エージェントのテストは難しいのか

従来のソフトウェアテストは **決定的** — 同じ入力に対して同じ出力が期待される。
しかし LLM エージェントは **非決定的** — 同じプロンプトでも毎回異なるテキストを返す。

```
❌ 従来のアプローチ（不安定）
assert "スコア" in response  # LLM の気分次第で PASS/FAIL が変わる

✅ このプロジェクトのアプローチ（安定）
assert len(response) > 200           # 十分な長さの出力か（プロパティ）
assert "code_generator" in trajectory  # 正しいエージェントが動いたか（トラジェクトリ）
```

## テストピラミッド

```
        ▲ コスト・時間（高）
       / \
      / Lv.2 \      統合テスト（実 LLM、プロパティ + トラジェクトリ）
     /─────────\
    /   Lv.1    \   ユニットテスト（LLM なし、構成の決定的検証）
   /─────────────\
        ▼ 速度・信頼性（高）
```

| レベル | ディレクトリ | LLM 呼出 | 実行時間 | テスト数 |
|--------|-------------|----------|---------|---------|
| **Lv.1** | `tests/unit/` | ❌ なし | **約1秒** | 50 |
| **Lv.2** | `tests/integration/` | ✅ あり | **約20分** | 14 |

---

## Lv.1 ユニットテスト（決定的・高速）

**LLM を一切呼び出さない。** エージェントの「構成」が正しいことを決定的に検証する。

### 実行方法

```bash
pytest tests/unit/ -v
```

### テストファイル

#### `test_config.py` — 設定の検証

| テスト | 保証する挙動 |
|--------|-------------|
| `test_env_example_exists` | `.env.example` が存在する |
| `test_env_example_has_required_keys` | 必要な環境変数（`GOOGLE_CLOUD_PROJECT` 等）が定義されている |
| `test_get_settings_returns_settings_instance` | `get_settings()` が正しいインスタンスを返す |
| `test_settings_has_valid_model` | `default_model` に `gemini` が含まれる |
| `test_env_vars_synced_to_os_environ` | 設定値が `os.environ` に反映される（ADK が参照するため） |

#### `test_agent_structure.py` — 全12パターンのエージェント構成

各パターンのエージェントが **正しい型・名前・サブエージェント構成** で定義されていることを検証する。
構成が変わったら即座にリグレッションを検出できる。

| パターン | 保証する構成 |
|----------|-------------|
| **01 Single Agent** | `LlmAgent`, name=`gcp_docs_agent`, tools あり |
| **02 ReAct** | `LlmAgent`, name=`research_react_agent`, tools あり |
| **03 Sequential** | `SequentialAgent`, sub_agents=4 (extractor→validator→transformer→summarizer の順序), 先頭3つに output_key |
| **04 Parallel** | `SequentialAgent`→`ParallelAgent`(4 researcher, 各固有 output_key)+`Synthesizer` |
| **05 Loop** | `LoopAgent`, sub_agents=2 (code_generator, code_tester), max_iterations 設定済 |
| **06 Review & Critique** | `LoopAgent`, sub_agents=2 (blog_generator, blog_critic), generator に output_key=`article_draft` |
| **07 Iterative Refinement** | `LoopAgent`, sub_agents=1 (doc_refiner) |
| **08 Coordinator** | `LlmAgent`(root) + sub_agents=4 (order/return/refund/product specialist) |
| **09 Hierarchical** | `LlmAgent`(root) + 2つ以上の sub_agents（階層構造） |
| **10 Swarm** | `SequentialAgent`→`LoopAgent` 内に market/engineer/finance expert + consensus_builder |
| **11 Human-in-the-Loop** | `LlmAgent`(content_creator) + compliance_checker, output_key 設定済 |
| **Capstone** | `LlmAgent`(coordinator)→`SequentialAgent`(pipeline)→`ParallelAgent`+`LoopAgent` |
| **Agentic Pipeline** | `BaseAgent`(PGEOrchestrator), name=`agentic_pipeline`, MAX_ITERATIONS≥3, Pydantic スキーマ検証, build_evaluator_system_prompt 検証 |

---

## Lv.2 統合テスト（実 LLM・プロパティ + トラジェクトリ）

**実際に Vertex AI を呼び出して** エージェントの動作を検証する。
非決定的な LLM 出力に対して2つのアプローチで安定性を確保する。

### 実行方法

```bash
# Vertex AI ADC が設定されている環境で実行
pytest tests/integration/ -v
```

### 2つの検証アプローチ

#### 1. プロパティベーステスト

出力の **「性質」** を検証する。具体的な文言ではなく、構造的な特徴を確認する。

```python
# 出力が十分な長さか
assert len(response) > 200

# 構造化されているか
assert response.count("\n") > 5
```

**なぜ安定か**: LLM がどんな文言で返しても、十分な長さのレスポンスがあれば PASS。

#### 2. トラジェクトリ検証

エージェントの **「行動経路」** を検証する。最終出力ではなく、**どのエージェントが発言したか** を確認する。

```python
response, trajectory = await run_agent_trajectory(agent, app_name, query)

# 全専門家が議論に参加したか
assert "market_expert" in trajectory
assert "engineer_expert" in trajectory
assert "consensus_builder" in trajectory
```

**なぜ安定か**: LLM の出力内容に依存せず、エージェントの協調動作が正しく行われたかを検証できる。

### テスト一覧と保証する挙動

| パターン | テスト名 | プロパティ検証 | トラジェクトリ検証 |
|----------|---------|:-------------:|:-----------------:|
| **01 Single Agent** | `test_responds_to_gcp_question` | 10文字以上の回答 | — |
| **02 ReAct** | `test_produces_structured_response` | 50文字以上の回答 | — |
| **03 Sequential** | `test_pipeline_processes_data` | 50文字以上の出力 | extractor→validator→transformer→summarizer が全員発言 |
| **04 Parallel** | `test_aggregation_produces_report` | 100文字以上のレポート | 2つ以上の researcher が発言 |
| **05 Loop** | `test_generates_code_with_loop` | コード含有（def/return/```） | code_generator + code_tester が両方発言 |
| **06 Review & Critique** | `test_generates_and_critiques_article` | 200文字以上の出力 | blog_generator + blog_critic が両方発言 |
| **07 Iterative Refinement** | `test_generates_and_refines_document` | 200文字以上のドキュメント | doc_refiner が発言 |
| **08 Coordinator** | `test_routes_order_query` | 20文字以上の回答 | order_specialist にルーティング |
| **08 Coordinator** | `test_routes_refund_query` | 20文字以上の回答 | refund_specialist にルーティング |
| **09 Hierarchical** | `test_generates_analysis_report` | 100文字以上のレポート | 3つ以上のエージェントが発言 |
| **10 Swarm** | `test_all_experts_participate` | 200文字以上の出力 | market/engineer/finance expert + consensus_builder が全員発言 |
| **Capstone** | `test_generates_enterprise_report` | 200文字以上のレポート | 3つ以上のエージェントが発言 |
| **Agentic Pipeline** | `test_pge_loop_with_abstract_business_request` | 50文字以上の出力、2ファイル以上生成 | `agentic_pipeline` が発言、P→G→E 全フェーズ通過 |
| **Agentic Pipeline** | `test_generator_creates_files_from_vague_request` | 1ファイル以上生成、内容が空でない | — |

---

## 共通ヘルパー（`conftest.py`）

テスト間で共有するヘルパー関数。

| 関数 | 用途 | 使うパターン |
|------|------|-------------|
| `load_pattern_agent(dir)` | `importlib.util` でエージェントを安全にロード | 全テスト |
| `run_agent_final_response()` | `is_final_response()` のテキスト取得 | LlmAgent 単体（01, 02） |
| `run_agent_all_text()` | 全イベントからテキスト収集 | LoopAgent 系（未使用、将来用） |
| `run_agent_trajectory()` | テキスト + 発言エージェント一覧を取得 | Sequential/Parallel/Loop/Swarm |

### なぜ `run_agent_all_text` が必要か

ADK の `LoopAgent` / `SequentialAgent` は `is_final_response()` が `True` にならないケースがある。
`run_agent_trajectory()` は内部的に全イベントを収集するため、この問題を回避できる。

---

## テスト実行コマンド

```bash
# Lv.1 のみ（高速、CI の必須ステップ）
pytest tests/unit/ -v

# Lv.2 のみ（Vertex AI 必要、統合テスト）
pytest tests/integration/ -v

# 全テスト
pytest tests/ -v

# 収集確認（テストは実行しない）
pytest tests/ --co
```

## 将来の拡張

- **Lv.3 Eval スイート**: LLM-as-a-Judge による品質スコアリング（Vertex AI Gen AI Evaluation）
- **Lv.4 E2E シミュレーション**: マルチターン対話の再生テスト
- **Golden Dataset**: `adk eval` による理想的な出力との比較テスト
- **`pytest-rerunfailures`**: 非決定的テストの自動リトライ（`@pytest.mark.flaky(reruns=3)`）
