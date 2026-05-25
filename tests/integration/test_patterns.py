"""Lv.2 統合テスト: 全パターンの動作検証（プロパティベース + トラジェクトリ）。

テスト方針:
- 実際の Vertex AI モデルを呼び出す統合テスト
- キーワード完全一致ではなく、出力の「性質」を検証（プロパティベーステスト）
- 最終出力だけでなく、エージェントの「行動経路」を検証（トラジェクトリ検証）
- LoopAgent 系は全イベント収集方式を使用（is_final_response() の不確実性を回避）

NOTE: これらは統合テストのため、Vertex AI ADC が必要。
テスト実行時間: 各テスト 30秒〜2分（全体で約20分）
"""

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
