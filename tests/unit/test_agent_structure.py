"""Lv.1 ユニットテスト: 全12パターンのエージェント構成を決定的に検証。

LLM を呼び出さない。エージェントの名前、型、Workflow の edges 構造、
output_key の設定を検証する。ミリ秒で完了する。

ADK v2: SequentialAgent/ParallelAgent/LoopAgent → Workflow に移行済み。
"""

from pathlib import Path

import pytest
from google.adk.agents import LlmAgent
from google.adk.workflow import Workflow

from conftest import load_pattern_agent


# =====================================================
# Lv.1 Single Agent
# =====================================================
class TestSingleAgentStructure:
    def setup_method(self):
        self.mod = load_pattern_agent("p01_single_agent")

    def test_root_agent_is_llm_agent(self):
        assert isinstance(self.mod.root_agent, LlmAgent)

    def test_agent_name(self):
        assert self.mod.root_agent.name == "gcp_docs_agent"

    def test_agent_has_tools(self):
        """Single Agent はツールを持つ。"""
        assert self.mod.root_agent.tools, "tools が空です"


# =====================================================
# Lv.2 ReAct Pattern
# =====================================================
class TestReActStructure:
    def setup_method(self):
        self.mod = load_pattern_agent("p02_react_pattern")

    def test_root_agent_is_llm_agent(self):
        assert isinstance(self.mod.root_agent, LlmAgent)

    def test_agent_name(self):
        assert self.mod.root_agent.name == "research_react_agent"

    def test_agent_has_tools(self):
        assert self.mod.root_agent.tools, "ReAct Agent には tools が必要です"


# =====================================================
# Lv.3 Sequential Pattern (Workflow チェーンタプル)
# =====================================================
class TestSequentialStructure:
    def setup_method(self):
        self.mod = load_pattern_agent("p03_sequential")

    def test_root_agent_is_workflow(self):
        assert isinstance(self.mod.root_agent, Workflow)

    def test_root_agent_name(self):
        assert self.mod.root_agent.name == "etl_pipeline"

    def test_graph_has_expected_nodes(self):
        """Workflow グラフに4つのエージェントノード + START がある。"""
        node_names = [n.name for n in self.mod.root_agent.graph.nodes]
        assert "__START__" in node_names
        for expected in ["extractor", "validator", "transformer", "summarizer"]:
            assert expected in node_names, f"{expected} がグラフノードにない"

    def test_graph_is_sequential(self):
        """エッジが順序通りに接続されている（チェーン構造）。"""
        edges = [(e.from_node.name, e.to_node.name) for e in self.mod.root_agent.graph.edges]
        # START → extractor → validator → transformer → summarizer
        assert ("__START__", "extractor") in edges
        assert ("extractor", "validator") in edges
        assert ("validator", "transformer") in edges
        assert ("transformer", "summarizer") in edges

    def test_agents_have_output_keys(self):
        """先頭3つのエージェントは output_key を持つ。"""
        nodes = {n.name: n for n in self.mod.root_agent.graph.nodes if isinstance(n, LlmAgent)}
        for name in ["extractor", "validator", "transformer"]:
            assert nodes[name].output_key, f"{name} に output_key がありません"


# =====================================================
# Lv.4 Parallel Pattern (Workflow ネストタプル fan-out/fan-in)
# =====================================================
class TestParallelStructure:
    def setup_method(self):
        self.mod = load_pattern_agent("p04_parallel")

    def test_root_agent_is_workflow(self):
        assert isinstance(self.mod.root_agent, Workflow)

    def test_root_agent_name(self):
        assert self.mod.root_agent.name == "news_aggregator"

    def test_graph_has_fan_out(self):
        """START から複数のリサーチャーへの fan-out エッジがある。"""
        start_edges = [
            e.to_node.name
            for e in self.mod.root_agent.graph.edges
            if e.from_node.name == "__START__"
        ]
        assert len(start_edges) >= 4, f"fan-out エッジが4つ以上必要: {start_edges}"

    def test_researchers_have_unique_output_keys(self):
        """各リサーチャーは固有の output_key を持つ。"""
        nodes = [n for n in self.mod.root_agent.graph.nodes if isinstance(n, LlmAgent)]
        researcher_keys = [n.output_key for n in nodes if n.output_key and n.name != "news_synthesizer"]
        assert len(researcher_keys) == len(set(researcher_keys)), f"output_key が重複: {researcher_keys}"


# =====================================================
# Lv.5 Loop Pattern (Workflow 条件付きサイクル)
# =====================================================
class TestLoopStructure:
    def setup_method(self):
        self.mod = load_pattern_agent("p05_loop")

    def test_root_agent_is_workflow(self):
        assert isinstance(self.mod.root_agent, Workflow)

    def test_root_agent_name(self):
        assert self.mod.root_agent.name == "code_generation_loop"

    def test_graph_has_cycle_edge(self):
        """条件付きサイクルエッジ（route 付き）がある。"""
        cycle_edges = [e for e in self.mod.root_agent.graph.edges if e.route is not None]
        assert len(cycle_edges) > 0, "条件付きサイクルエッジがありません"

    def test_graph_has_generator_and_tester(self):
        node_names = [n.name for n in self.mod.root_agent.graph.nodes]
        assert "code_generator" in node_names
        assert "code_tester" in node_names


# =====================================================
# Lv.6 Review & Critique Pattern (Workflow 条件付きサイクル)
# =====================================================
class TestReviewCritiqueStructure:
    def setup_method(self):
        self.mod = load_pattern_agent("p06_review_critique")

    def test_root_agent_is_workflow(self):
        assert isinstance(self.mod.root_agent, Workflow)

    def test_root_agent_name(self):
        assert self.mod.root_agent.name == "blog_review_loop"

    def test_graph_has_cycle_edge(self):
        """条件付きサイクルエッジがある。"""
        cycle_edges = [e for e in self.mod.root_agent.graph.edges if e.route is not None]
        assert len(cycle_edges) > 0

    def test_generator_has_output_key(self):
        """generator は article_draft を output_key に持つ。"""
        gen = next(
            (n for n in self.mod.root_agent.graph.nodes if n.name == "blog_generator"),
            None,
        )
        assert gen is not None
        assert gen.output_key == "article_draft"


# =====================================================
# Lv.7 Iterative Refinement Pattern (Workflow 条件付きサイクル)
# =====================================================
class TestIterativeRefinementStructure:
    def setup_method(self):
        self.mod = load_pattern_agent("p07_iterative_refinement")

    def test_root_agent_is_workflow(self):
        assert isinstance(self.mod.root_agent, Workflow)

    def test_root_agent_name(self):
        assert self.mod.root_agent.name == "doc_refinement_loop"

    def test_graph_has_cycle_edge(self):
        """自己反復の条件付きサイクルエッジがある。"""
        cycle_edges = [e for e in self.mod.root_agent.graph.edges if e.route is not None]
        assert len(cycle_edges) > 0

    def test_doc_refiner_in_graph(self):
        node_names = [n.name for n in self.mod.root_agent.graph.nodes]
        assert "doc_refiner" in node_names


# =====================================================
# Lv.8 Coordinator Pattern
# =====================================================
class TestCoordinatorStructure:
    def setup_method(self):
        self.mod = load_pattern_agent("p08_coordinator")

    def test_root_agent_is_llm_agent(self):
        assert isinstance(self.mod.root_agent, LlmAgent)

    def test_root_agent_name(self):
        assert self.mod.root_agent.name == "customer_service_coordinator"

    def test_has_specialist_sub_agents(self):
        """Coordinator は4つの専門エージェントを持つ。"""
        assert len(self.mod.root_agent.sub_agents) == 4

    def test_specialist_names(self):
        names = {a.name for a in self.mod.root_agent.sub_agents}
        expected = {"order_specialist", "return_specialist", "refund_specialist", "product_specialist"}
        assert names == expected, f"期待: {expected}, 実際: {names}"


# =====================================================
# Lv.9 Hierarchical Pattern
# =====================================================
class TestHierarchicalStructure:
    def setup_method(self):
        self.mod = load_pattern_agent("p09_hierarchical")

    def test_root_agent_is_llm_agent(self):
        assert isinstance(self.mod.root_agent, LlmAgent)

    def test_has_sub_agents(self):
        """階層構造のため、sub_agents を持つ。"""
        assert len(self.mod.root_agent.sub_agents) >= 2


# =====================================================
# Lv.10 Swarm Pattern (Workflow 条件付きサイクル)
# =====================================================
class TestSwarmStructure:
    def setup_method(self):
        self.mod = load_pattern_agent("p10_swarm")

    def test_root_agent_is_workflow(self):
        assert isinstance(self.mod.root_agent, Workflow)

    def test_root_agent_name(self):
        assert self.mod.root_agent.name == "product_design_swarm"

    def test_graph_has_experts(self):
        """グラフに全専門家 + consensus_builder がいる。"""
        node_names = {n.name for n in self.mod.root_agent.graph.nodes}
        expected = {"market_expert", "engineer_expert", "finance_expert", "consensus_builder"}
        assert expected.issubset(node_names), f"不足: {expected - node_names}"

    def test_graph_has_cycle_edge(self):
        """条件付きサイクルエッジがある。"""
        cycle_edges = [e for e in self.mod.root_agent.graph.edges if e.route is not None]
        assert len(cycle_edges) > 0


# =====================================================
# Lv.11 Human-in-the-Loop Pattern (Workflow)
# =====================================================
class TestHumanInTheLoopStructure:
    def setup_method(self):
        self.mod = load_pattern_agent("p11_human_in_the_loop")

    def test_root_agent_is_workflow(self):
        assert isinstance(self.mod.root_agent, Workflow)

    def test_content_creator_has_output_key(self):
        """content_creator は output_key を持つ。"""
        assert hasattr(self.mod, "content_creator")
        assert self.mod.content_creator.output_key == "generated_content"

    def test_compliance_checker_exists(self):
        """compliance_checker が定義されている。"""
        assert hasattr(self.mod, "compliance_checker")
        assert self.mod.compliance_checker.name == "compliance_checker"


# =====================================================
# Capstone (Workflow + Coordinator)
# =====================================================
class TestCapstoneStructure:
    def setup_method(self):
        self.mod = load_pattern_agent("capstone")

    def test_root_agent_is_workflow(self):
        """root_agent は Workflow（Coordinator を含む）。"""
        assert isinstance(self.mod.root_agent, Workflow)

    def test_root_agent_name(self):
        assert self.mod.root_agent.name == "enterprise_research_workflow"

    def test_graph_has_coordinator(self):
        """グラフに coordinator ノードがある。"""
        node_names = [n.name for n in self.mod.root_agent.graph.nodes]
        assert "enterprise_research_coordinator" in node_names

    def test_graph_has_fan_out_researchers(self):
        """coordinator から3つのリサーチャーへの fan-out がある。"""
        coordinator_edges = [
            e.to_node.name
            for e in self.mod.root_agent.graph.edges
            if e.from_node.name == "enterprise_research_coordinator"
        ]
        assert len(coordinator_edges) >= 3, f"fan-out エッジが3つ以上必要: {coordinator_edges}"

    def test_graph_has_cycle_edge(self):
        """レポート改善の条件付きサイクルエッジがある。"""
        cycle_edges = [e for e in self.mod.root_agent.graph.edges if e.route is not None]
        assert len(cycle_edges) > 0


# =====================================================
# Agentic Pipeline (BaseAgent + Antigravity, PGE ループ)
# =====================================================
class TestAgenticPipelineStructure:
    def setup_method(self):
        self.mod = load_pattern_agent("agentic_pipeline")

    def test_root_agent_is_base_agent(self):
        """root_agent は BaseAgent（PGEOrchestrator）。"""
        assert not isinstance(self.mod.root_agent, Workflow)
        assert not isinstance(self.mod.root_agent, LlmAgent)

    def test_root_agent_name(self):
        assert self.mod.root_agent.name == "agentic_pipeline"

    def test_root_agent_is_pge_orchestrator(self):
        """PGEOrchestrator クラスのインスタンスである。"""
        from patterns.agentic_pipeline.agent import PGEOrchestrator
        # モジュール二重ロード問題を回避
        assert type(self.mod.root_agent).__name__ == "PGEOrchestrator"

    def test_max_iterations_defined(self):
        """MAX_ITERATIONS が定義されている。"""
        assert hasattr(self.mod, "MAX_ITERATIONS")
        assert self.mod.MAX_ITERATIONS >= 3

    def test_schemas_are_valid(self):
        """Pydantic スキーマが正しく定義されている。"""
        from patterns.agentic_pipeline.schemas import (
            ArtifactOutput,
            EvaluationOutput,
            Issue,
            PlanOutput,
            Severity,
        )

        # 有効なデータで検証
        plan = PlanOutput(
            architecture="クリーンアーキテクチャ",
            modules=["main.py", "models.py"],
            test_strategy="pytest で主要機能をカバー",
            directory_structure="src/\n  main.py\n  models.py",
        )
        assert len(plan.modules) == 2

        artifact = ArtifactOutput(
            files_created=["main.py", "tests/test_main.py"],
            summary="REST API を実装",
        )
        assert len(artifact.files_created) == 2

        evaluation = EvaluationOutput(
            score=85,
            test_result="5 passed",
            lint_result="0 errors",
            issues=[
                Issue(
                    severity=Severity.MEDIUM,
                    description="docstring 不足",
                    file="main.py",
                    suggestion="関数に docstring を追加",
                ),
            ],
            suggestions=["テストカバレッジを向上"],
            verdict="APPROVED",
            reasoning="品質基準クリア",
        )
        assert evaluation.score == 85
        assert evaluation.verdict == "APPROVED"
        assert evaluation.issues[0].severity == Severity.MEDIUM

    def test_evaluator_prompt_builder(self):
        """build_evaluator_system_prompt が反復情報を含む。"""
        from patterns.agentic_pipeline.prompts import build_evaluator_system_prompt

        prompt = build_evaluator_system_prompt(
            iteration=2, max_iterations=3, score_history=[65],
        )
        assert "2/3" in prompt
        assert "[65]" in prompt

