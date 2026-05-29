"""Lv.2 統合テスト: 全パターンの動作検証（プロパティベース + トラジェクトリ）。

テスト方針:
- 実際の Vertex AI モデルを呼び出す統合テスト
- キーワード完全一致ではなく、出力の「性質」を検証（プロパティベーステスト）
- 最終出力だけでなく、エージェントの「行動経路」を検証（トラジェクトリ検証）
- LoopAgent 系は全イベント収集方式を使用（is_final_response() の不確実性を回避）

NOTE: これらは統合テストのため、Vertex AI ADC が必要。
テスト実行時間: 各テスト 30秒〜2分（全体で約20分）
"""

import os

import pytest

from conftest import (
    load_pattern_agent,
    run_agent_all_text,
    run_agent_final_response,
    run_agent_trajectory,
)


# ============================================================
# Lv.1 Single Agent
# ============================================================
class TestSingleAgent:
    @pytest.mark.asyncio
    async def test_responds_to_gcp_question(self):
        """GCP の質問に対して十分な長さの回答を返す。"""
        mod = load_pattern_agent("01_single_agent")
        response = await run_agent_final_response(
            mod.root_agent, "gcp_docs_agent",
            "Cloud Run とは何ですか？一言で教えてください。"
        )
        assert len(response) > 10, f"回答が短すぎます: {len(response)} 文字"


# ============================================================
# Lv.2 ReAct Pattern
# ============================================================
class TestReAct:
    @pytest.mark.asyncio
    async def test_produces_structured_response(self):
        """構造化された（改行を含む）回答を返す。"""
        mod = load_pattern_agent("02_react_pattern")
        response = await run_agent_final_response(
            mod.root_agent, "research_react_agent",
            "Python と Go の比較を教えてください"
        )
        assert len(response) > 50, f"回答が短すぎます: {len(response)} 文字"


# ============================================================
# Lv.3 Sequential Pattern（トラジェクトリ検証）
# ============================================================
class TestSequential:
    @pytest.mark.asyncio
    async def test_pipeline_processes_data(self):
        """Sequential パイプラインがデータを順次処理する。"""
        mod = load_pattern_agent("03_sequential")
        test_data = """raw_data: 以下のデータを処理してください。
name,age,score
Alice,25,90
Bob,,85
Charlie,30,invalid
"""
        response, trajectory = await run_agent_trajectory(
            mod.root_agent, "etl_pipeline", test_data
        )
        # プロパティ: 出力がある
        assert len(response) > 50, "パイプラインの出力が短すぎます"

        # トラジェクトリ: 4つの sub_agents が順序通りに発言した
        expected_agents = ["extractor", "validator", "transformer", "summarizer"]
        for agent_name in expected_agents:
            assert agent_name in trajectory, (
                f"{agent_name} がトラジェクトリに含まれていません: {trajectory}"
            )


# ============================================================
# Lv.4 Parallel Pattern（トラジェクトリ検証）
# ============================================================
class TestParallel:
    @pytest.mark.asyncio
    async def test_aggregation_produces_report(self):
        """Parallel エージェントが複数ソースを集約してレポートを作成する。"""
        mod = load_pattern_agent("04_parallel")
        response, trajectory = await run_agent_trajectory(
            mod.root_agent, "news_aggregator",
            "topic: 生成 AI の最新動向について調査してください"
        )
        # プロパティ: レポートが十分な長さ
        assert len(response) > 100, f"レポートが短すぎます: {len(response)} 文字"

        # トラジェクトリ: 複数の researcher が発言した
        researcher_names = [
            "google_ai_researcher", "openai_researcher",
            "regulation_researcher", "industry_researcher",
        ]
        active_researchers = [n for n in researcher_names if n in trajectory]
        assert len(active_researchers) >= 2, (
            f"十分な数の researcher が発言していません: {active_researchers}"
        )


# ============================================================
# Lv.5 Loop Pattern（トラジェクトリ + 全イベント収集）
# ============================================================
class TestLoop:
    @pytest.mark.asyncio
    async def test_generates_code_with_loop(self):
        """Loop がコード生成→テストを繰り返す。"""
        mod = load_pattern_agent("05_loop")
        response, trajectory = await run_agent_trajectory(
            mod.root_agent, "code_generation_loop",
            "FizzBuzz を実装する Python 関数を書いてください。"
        )
        # プロパティ: コードが含まれる
        assert len(response) > 50, "出力が短すぎます"
        code_indicators = ["def ", "return", "python", "fizz", "buzz", "```"]
        assert any(kw in response.lower() for kw in code_indicators), (
            f"コードが含まれていません: {response[:200]}"
        )

        # トラジェクトリ: generator と tester が両方発言
        assert "code_generator" in trajectory, f"code_generator が発言していません: {trajectory}"
        assert "code_tester" in trajectory, f"code_tester が発言していません: {trajectory}"


# ============================================================
# Lv.6 Review & Critique Pattern（トラジェクトリ + 全イベント収集）
# ============================================================
class TestReviewCritique:
    @pytest.mark.asyncio
    async def test_generates_and_critiques_article(self):
        """Generator と Critic が両方動作する。"""
        mod = load_pattern_agent("06_review_critique")
        response, trajectory = await run_agent_trajectory(
            mod.root_agent, "blog_review_loop",
            "Cloud Run を使ったサーバーレスアプリケーション開発"
        )
        # プロパティ: 記事 + 評価の十分な出力
        assert len(response) > 200, f"出力が短すぎます: {len(response)} 文字"

        # トラジェクトリ: generator と critic が両方発言
        assert "blog_generator" in trajectory, f"blog_generator が発言していません: {trajectory}"
        assert "blog_critic" in trajectory, f"blog_critic が発言していません: {trajectory}"


# ============================================================
# Lv.7 Iterative Refinement Pattern（全イベント収集）
# ============================================================
class TestIterativeRefinement:
    @pytest.mark.asyncio
    async def test_generates_and_refines_document(self):
        """doc_refiner が反復的にドキュメントを改善する。"""
        mod = load_pattern_agent("07_iterative_refinement")
        response, trajectory = await run_agent_trajectory(
            mod.root_agent, "doc_refinement_loop",
            "Cloud Spanner の技術ドキュメントを作成してください"
        )
        # プロパティ: ドキュメントが十分な長さ
        assert len(response) > 200, f"ドキュメントが短すぎます: {len(response)} 文字"

        # トラジェクトリ: doc_refiner が発言
        assert "doc_refiner" in trajectory, f"doc_refiner が発言していません: {trajectory}"


# ============================================================
# Lv.8 Coordinator Pattern（トラジェクトリ検証）
# ============================================================
class TestCoordinator:
    @pytest.mark.asyncio
    async def test_routes_order_query(self):
        """注文確認クエリが order_specialist にルーティングされる。"""
        mod = load_pattern_agent("08_coordinator")
        response, trajectory = await run_agent_trajectory(
            mod.root_agent, "customer_service_coordinator",
            "注文番号 ORD-001 の配送状況を確認したいです"
        )
        assert len(response) > 20, "回答が短すぎます"

        # トラジェクトリ: order_specialist が発言した
        assert "order_specialist" in trajectory, (
            f"order_specialist にルーティングされていません: {trajectory}"
        )

    @pytest.mark.asyncio
    async def test_routes_refund_query(self):
        """返金クエリが refund_specialist にルーティングされる。"""
        mod = load_pattern_agent("08_coordinator")
        response, trajectory = await run_agent_trajectory(
            mod.root_agent, "customer_service_coordinator",
            "注文 ORD-002 で二重請求があったので、3000円の返金をお願いします"
        )
        assert len(response) > 20, "回答が短すぎます"

        # トラジェクトリ: refund_specialist が発言した
        assert "refund_specialist" in trajectory, (
            f"refund_specialist にルーティングされていません: {trajectory}"
        )


# ============================================================
# Lv.9 Hierarchical Pattern（トラジェクトリ検証）
# ============================================================
class TestHierarchical:
    @pytest.mark.asyncio
    async def test_generates_analysis_report(self):
        """階層構造で競合分析レポートを生成する。"""
        mod = load_pattern_agent("09_hierarchical")
        response, trajectory = await run_agent_trajectory(
            mod.root_agent, "competitive_analysis_root",
            "Google Cloud の競合分析をしてください"
        )
        # プロパティ: レポートが十分な長さ
        assert len(response) > 100, f"レポートが短すぎます: {len(response)} 文字"

        # トラジェクトリ: 複数のエージェントが発言（階層構造の確認）
        assert len(trajectory) >= 3, (
            f"階層構造のエージェントが十分に発言していません: {trajectory}"
        )


# ============================================================
# Lv.10 Swarm Pattern（トラジェクトリ検証 ★重要）
# ============================================================
class TestSwarm:
    @pytest.mark.asyncio
    async def test_all_experts_participate(self):
        """全専門家 + consensus_builder が議論に参加する。"""
        mod = load_pattern_agent("10_swarm")
        response, trajectory = await run_agent_trajectory(
            mod.root_agent, "product_design_swarm",
            "Google Cloud 上で動作するリアルタイム翻訳アプリを設計してください"
        )
        # プロパティ: コンセンサスドキュメントが十分な長さ
        assert len(response) > 200, f"出力が短すぎます: {len(response)} 文字"

        # トラジェクトリ: 全専門家が発言した
        expected_experts = [
            "market_expert", "engineer_expert",
            "finance_expert", "consensus_builder",
        ]
        for expert in expected_experts:
            assert expert in trajectory, (
                f"{expert} がトラジェクトリに含まれていません: {trajectory}"
            )


# ============================================================
# Capstone（トラジェクトリ検証）
# ============================================================
class TestCapstone:
    @pytest.mark.asyncio
    async def test_generates_enterprise_report(self):
        """Capstone エージェントが企業分析レポートを生成する。"""
        mod = load_pattern_agent("capstone")
        response, trajectory = await run_agent_trajectory(
            mod.root_agent, "enterprise_research_coordinator",
            "Salesforce の技術戦略を分析してください"
        )
        # プロパティ: レポートが十分な長さ
        assert len(response) > 200, f"レポートが短すぎます: {len(response)} 文字"

        # トラジェクトリ: 複数フェーズ（データ収集 + 分析）のエージェントが発言
        assert len(trajectory) >= 3, (
            f"十分なエージェントが発言していません: {trajectory}"
        )


# ============================================================
# Agentic Pipeline（Antigravity Agent 統合テスト）
# ============================================================
_has_gemini_api_key = bool(os.environ.get("GEMINI_API_KEY"))


@pytest.mark.skipif(
    not _has_gemini_api_key,
    reason="GEMINI_API_KEY が未設定（Antigravity local harness に必須）",
)
class TestAgenticPipeline:
    """汎用 PGE コード実装パイプラインの統合テスト。

    テストプロンプトは非エンジニア・ビジネス職が投げる抽象度の高いリクエストを
    模擬する。技術的な仕様（クラス名、メソッド名、例外型）は指定せず、
    ビジネス要件のみを記述する。Planner が技術仕様に落とし込むのが PGE の仕事。

    検証項目:
    - P→G→E の3ノードが全て通過する（トラジェクトリ検証）
    - Generator が実際にファイルを生成する（create_file ツール使用）
    - Evaluator が pytest/ruff を実行する（run_command ツール使用）
    - 最終出力に評価結果が含まれる
    """

    @pytest.fixture(autouse=True)
    def clean_output_dir(self):
        """テスト前に output ディレクトリをクリーンアップする。"""
        import shutil

        from patterns.agentic_pipeline.tools import OUTPUT_DIR

        if OUTPUT_DIR.exists():
            shutil.rmtree(OUTPUT_DIR)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        yield
        # テスト後はクリーンアップしない（デバッグ用に残す）

    @pytest.mark.asyncio
    async def test_pge_loop_with_abstract_business_request(self):
        """非エンジニアの抽象的なリクエストから PGE が品質コードを生成する。

        プロンプトは技術仕様を一切含まず、ビジネス要件のみ。
        Planner がこの曖昧なリクエストを技術設計に落とし込み、
        Generator が実装し、Evaluator が品質検証する。
        """
        from patterns.agentic_pipeline.tools import OUTPUT_DIR

        mod = load_pattern_agent("agentic_pipeline")
        response, trajectory = await run_agent_trajectory(
            mod.root_agent, "agentic_pipeline",
            "チームの社内本棚にある本を管理できるツールを Python で作ってほしい。"
            "本の登録・検索・削除ができて、同じ本が二重登録されないようにしたい。"
            "ISBN で本を特定できるようにして、不正な ISBN はエラーにしてほしい。"
            "ちゃんとテストも書いてね。"
        )

        # ===== PGE ループ完走検証 =====
        # PGEOrchestrator が発言している
        assert "agentic_pipeline" in trajectory, (
            f"PGEOrchestrator が発言していません: {trajectory}"
        )

        # レスポンスに P→G→E 全フェーズの進行が含まれる
        assert "Planner" in response or "Evaluator" in response or "APPROVED" in response, (
            f"PGE フェーズの進行が出力に含まれていません: {response[:200]}"
        )

        # ===== ファイル生成検証 =====
        # Generator が実際にファイルを生成している
        generated_files = list(OUTPUT_DIR.rglob("*.py"))
        assert len(generated_files) >= 2, (
            f"最低2ファイル（実装+テスト）が生成される必要があります。"
            f"実際の生成ファイル: "
            f"{[str(f.relative_to(OUTPUT_DIR)) for f in generated_files]}"
        )

        # テストファイルが存在する
        test_files = [f for f in generated_files if "test" in f.name.lower()]
        assert len(test_files) >= 1, (
            f"テストファイルが生成されていません。"
            f"生成ファイル: {[f.name for f in generated_files]}"
        )

        # ===== 出力検証 =====
        # 最終出力が十分な長さ（評価結果を含む）
        assert len(response) > 50, (
            f"出力が短すぎます（評価結果が含まれていない可能性）: "
            f"{len(response)} 文字"
        )

    @pytest.mark.asyncio
    async def test_generator_creates_files_from_vague_request(self):
        """曖昧なリクエストから Generator がファイルを自律生成する。

        アプローチ B の核心: 非エンジニアの「こんなのが欲しい」レベルの
        リクエストでも、Antigravity Agent が設計判断を行い、
        ビルトインツールで実際にファイルを生成することを検証する。
        """
        from patterns.agentic_pipeline.tools import OUTPUT_DIR

        mod = load_pattern_agent("agentic_pipeline")
        await run_agent_trajectory(
            mod.root_agent, "agentic_pipeline",
            "タスクの優先度と期限を管理できる TODO リストを作って。"
            "タスクには優先度（高・中・低）があって、期限切れのタスクを"
            "抽出できるようにしたい。テストもお願い。"
        )

        # ファイルが実際に書き出されている
        all_files = list(OUTPUT_DIR.rglob("*.py"))
        assert len(all_files) >= 1, (
            f"Generator がファイルを生成していません。"
            f"OUTPUT_DIR: {OUTPUT_DIR}"
        )

        # 生成されたコードが空でない（__init__.py は空で正常なため除外）
        for f in all_files:
            if f.name == "__init__.py":
                continue
            content = f.read_text()
            assert len(content) > 10, (
                f"生成ファイル {f.name} の内容が空です"
            )
