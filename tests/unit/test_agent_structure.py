"""Lv.1 ユニットテスト: 全12パターンのエージェント構成を決定的に検証。

LLM を呼び出さない。エージェントの名前、型、sub_agents の構成、
output_key の設定を検証する。ミリ秒で完了する。
"""

from pathlib import Path

import pytest
from google.adk.agents import LlmAgent

from conftest import load_pattern_agent


# =====================================================
# Lv.1 Single Agent
# =====================================================
class TestSingleAgentStructure:
    def setup_method(self):
        self.mod = load_pattern_agent("01_single_agent")

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
        self.mod = load_pattern_agent("02_react_pattern")

    def test_root_agent_is_llm_agent(self):
        assert isinstance(self.mod.root_agent, LlmAgent)

    def test_agent_name(self):
        assert self.mod.root_agent.name == "research_react_agent"

    def test_agent_has_tools(self):
        assert self.mod.root_agent.tools, "ReAct Agent には tools が必要です"


# =====================================================
# Lv.3 Sequential Pattern
# =====================================================
class TestSequentialStructure:
    def setup_method(self):
        self.mod = load_pattern_agent("03_sequential")

    def test_root_agent_name(self):
        assert self.mod.root_agent.name == "etl_pipeline"

    def test_sub_agents_count(self):
        """Sequential は4つの sub_agents を持つ。"""
        assert len(self.mod.root_agent.sub_agents) == 4

    def test_sub_agents_order(self):
        """extractor → validator → transformer → summarizer の順序。"""
        names = [a.name for a in self.mod.root_agent.sub_agents]
        assert names == ["extractor", "validator", "transformer", "summarizer"]

    def test_sub_agents_have_output_keys(self):
        """先頭3つの sub_agents は output_key を持つ（パイプラインのデータ受け渡し用）。"""
        for agent in self.mod.root_agent.sub_agents[:3]:
            assert agent.output_key, f"{agent.name} に output_key が設定されていません"


# =====================================================
# Lv.4 Parallel Pattern
# =====================================================
class TestParallelStructure:
    def setup_method(self):
        self.mod = load_pattern_agent("04_parallel")

    def test_root_agent_name(self):
        assert self.mod.root_agent.name == "news_aggregator"

    def test_sub_agents_count(self):
        """SequentialAgent(root) は ParallelAgent + Synthesizer の2つを持つ。"""
        assert len(self.mod.root_agent.sub_agents) == 2

    def test_parallel_has_researchers(self):
        """ParallelAgent 内に複数の researcher がいる。"""
        parallel_agent = self.mod.root_agent.sub_agents[0]
        assert len(parallel_agent.sub_agents) >= 4, "researcher が4つ以上必要です"

    def test_researchers_have_unique_output_keys(self):
        """各 researcher は固有の output_key を持つ。"""
        parallel_agent = self.mod.root_agent.sub_agents[0]
        keys = [a.output_key for a in parallel_agent.sub_agents]
        assert len(keys) == len(set(keys)), f"output_key が重複しています: {keys}"


# =====================================================
# Lv.5 Loop Pattern
# =====================================================
class TestLoopStructure:
    def setup_method(self):
        self.mod = load_pattern_agent("05_loop")

    def test_root_agent_name(self):
        assert self.mod.root_agent.name == "code_generation_loop"

    def test_sub_agents_count(self):
        """LoopAgent は code_generator と code_tester の2つ。"""
        assert len(self.mod.root_agent.sub_agents) == 2

    def test_sub_agents_names(self):
        names = [a.name for a in self.mod.root_agent.sub_agents]
        assert "code_generator" in names
        assert "code_tester" in names

    def test_has_max_iterations(self):
        assert self.mod.root_agent.max_iterations is not None
        assert self.mod.root_agent.max_iterations > 0


# =====================================================
# Lv.6 Review & Critique Pattern
# =====================================================
class TestReviewCritiqueStructure:
    def setup_method(self):
        self.mod = load_pattern_agent("06_review_critique")

    def test_root_agent_name(self):
        assert self.mod.root_agent.name == "blog_review_loop"

    def test_sub_agents_count(self):
        """LoopAgent は generator と critic の2つ。"""
        assert len(self.mod.root_agent.sub_agents) == 2

    def test_sub_agents_names(self):
        names = [a.name for a in self.mod.root_agent.sub_agents]
        assert "blog_generator" in names
        assert "blog_critic" in names

    def test_generator_has_output_key(self):
        """generator は article_draft を output_key に持つ。"""
        gen = next(a for a in self.mod.root_agent.sub_agents if a.name == "blog_generator")
        assert gen.output_key == "article_draft"


# =====================================================
# Lv.7 Iterative Refinement Pattern
# =====================================================
class TestIterativeRefinementStructure:
    def setup_method(self):
        self.mod = load_pattern_agent("07_iterative_refinement")

    def test_root_agent_name(self):
        assert self.mod.root_agent.name == "doc_refinement_loop"

    def test_sub_agents_count(self):
        """自己反復のため sub_agents は1つ（doc_refiner）。"""
        assert len(self.mod.root_agent.sub_agents) == 1

    def test_sub_agent_name(self):
        assert self.mod.root_agent.sub_agents[0].name == "doc_refiner"


# =====================================================
# Lv.8 Coordinator Pattern
# =====================================================
class TestCoordinatorStructure:
    def setup_method(self):
        self.mod = load_pattern_agent("08_coordinator")

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
        self.mod = load_pattern_agent("09_hierarchical")

    def test_root_agent_is_llm_agent(self):
        assert isinstance(self.mod.root_agent, LlmAgent)

    def test_has_sub_agents(self):
        """階層構造のため、sub_agents を持つ。"""
        assert len(self.mod.root_agent.sub_agents) >= 2


# =====================================================
# Lv.10 Swarm Pattern
# =====================================================
class TestSwarmStructure:
    def setup_method(self):
        self.mod = load_pattern_agent("10_swarm")

    def test_root_agent_name(self):
        assert self.mod.root_agent.name == "product_design_swarm"

    def test_has_loop_agent(self):
        """SequentialAgent 内に LoopAgent がある。"""
        loop = self.mod.root_agent.sub_agents[0]
        assert loop.name == "debate_loop"

    def test_loop_has_experts(self):
        """LoopAgent 内に全専門家 + consensus_builder がいる。"""
        loop = self.mod.root_agent.sub_agents[0]
        names = {a.name for a in loop.sub_agents}
        expected = {"market_expert", "engineer_expert", "finance_expert", "consensus_builder"}
        assert expected.issubset(names), f"不足: {expected - names}"


# =====================================================
# Lv.11 Human-in-the-Loop Pattern
# =====================================================
class TestHumanInTheLoopStructure:
    def setup_method(self):
        self.mod = load_pattern_agent("11_human_in_the_loop")

    def test_root_agent_is_llm_agent(self):
        assert isinstance(self.mod.root_agent, LlmAgent)

    def test_content_creator_has_output_key(self):
        """content_creator は output_key を持つ。"""
        assert hasattr(self.mod, "content_creator")
        assert self.mod.content_creator.output_key == "generated_content"

    def test_compliance_checker_exists(self):
        """compliance_checker が定義されている。"""
        assert hasattr(self.mod, "compliance_checker")
        assert self.mod.compliance_checker.name == "compliance_checker"


# =====================================================
# Capstone
# =====================================================
class TestCapstoneStructure:
    def setup_method(self):
        self.mod = load_pattern_agent("capstone")

    def test_root_agent_is_coordinator(self):
        """root_agent は LlmAgent（Coordinator）。"""
        assert isinstance(self.mod.root_agent, LlmAgent)
        assert self.mod.root_agent.name == "enterprise_research_coordinator"

    def test_has_pipeline_sub_agent(self):
        """Coordinator の sub_agents に enterprise_research_pipeline がある。"""
        sub_names = [a.name for a in self.mod.root_agent.sub_agents]
        assert "enterprise_research_pipeline" in sub_names, (
            f"enterprise_research_pipeline が見つかりません: {sub_names}"
        )

    def test_pipeline_has_parallel_and_loop(self):
        """Pipeline 内に ParallelAgent（データ収集）と LoopAgent（レポート改善）を含む。"""
        pipeline = next(
            a for a in self.mod.root_agent.sub_agents
            if a.name == "enterprise_research_pipeline"
        )
        sub_names = [a.name for a in pipeline.sub_agents]
        assert any("data_collection" in n for n in sub_names), (
            f"data_collection が見つかりません: {sub_names}"
        )
        assert any("report_refinement" in n or "refinement" in n for n in sub_names), (
            f"report_refinement が見つかりません: {sub_names}"
        )
