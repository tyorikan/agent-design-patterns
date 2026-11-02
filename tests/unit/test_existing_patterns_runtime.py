"""既存 13 パターン（`patterns/`）および `shared/demo_runner.py` の決定論的ランタイム単体テスト。

外部 API やクラウド認証を一切使用せず、`GeminiScriptedLlm(BaseLlm)` を用いて
ADK 2.13 の `Runner` / `Workflow` / `JoinNode` / `@node` ルーター / `RequestInput` /
`sub_agents` 動的委譲 / `PGEOrchestrator` の実働経路をすべてインプロセスで検証する。
"""

from __future__ import annotations

import importlib
from collections.abc import AsyncGenerator, Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from google.adk.agents import BaseAgent, LlmAgent
from google.adk.models._capabilities import LlmCapabilities
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.workflow import Workflow
from google.genai import types
from pydantic import PrivateAttr

from conftest import (
    load_pattern_agent,
    run_agent_final_response,
    run_agent_trajectory,
)


class GeminiScriptedLlm(BaseLlm):
    """`is_gemini_model` チェック（`google_search` 等）を通過する決定論的テスト用 LLM。"""

    model: str = "gemini-3.8-flash"
    _steps: list[LlmResponse | Callable[[LlmRequest], LlmResponse]] = PrivateAttr(
        default_factory=list
    )
    _requests: list[LlmRequest] = PrivateAttr(default_factory=list)

    def __init__(
        self,
        steps: list[LlmResponse | Callable[[LlmRequest], LlmResponse]],
        model: str = "gemini-3.8-flash",
    ) -> None:
        super().__init__(model=model)
        self._steps = list(steps)
        self._requests = []

    @property
    def capabilities(self) -> LlmCapabilities:
        return LlmCapabilities(output_schema_and_tools=True)

    @property
    def call_count(self) -> int:
        return len(self._requests)

    @property
    def requests(self) -> list[LlmRequest]:
        return list(self._requests)

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        del stream
        self._requests.append(llm_request)
        idx = min(len(self._requests) - 1, len(self._steps) - 1)
        step = self._steps[idx]
        resp = step(llm_request) if callable(step) else step
        yield resp


def _text_resp(text: str) -> LlmResponse:
    return LlmResponse(
        content=types.Content(role="model", parts=[types.Part.from_text(text=text)])
    )


def _tool_call_resp(
    name: str,
    args: dict[str, Any],
    call_id: str = "call_1",
    thought_text: str | None = None,
) -> LlmResponse:
    parts: list[types.Part] = []
    if thought_text is not None:
        parts.append(types.Part(text=thought_text, thought=True))
    parts.append(
        types.Part(
            function_call=types.FunctionCall(
                id=call_id,
                name=name,
                args=args,
            )
        )
    )
    return LlmResponse(content=types.Content(role="model", parts=parts))


def _collect_llm_agents(target: Any) -> dict[str, LlmAgent]:
    """`Workflow` または `BaseAgent` ツリー内の全 `LlmAgent` を名前辞書として収集する。"""
    found: dict[str, LlmAgent] = {}

    def _visit(obj: Any) -> None:
        if isinstance(obj, LlmAgent):
            found[obj.name] = obj
            for sub in obj.sub_agents:
                _visit(sub)
        elif isinstance(obj, Workflow):
            for node_obj in obj.graph.nodes:
                _visit(node_obj)
        elif isinstance(obj, BaseAgent):
            for sub in obj.sub_agents:
                _visit(sub)

    _visit(target)
    return found


@contextmanager
def _patch_agent_models(
    target: Any,
    models_by_name: dict[str, BaseLlm],
) -> Iterator[dict[str, LlmAgent]]:
    """対象エージェント群の `.model` を一時的にテスト用 `BaseLlm` に差し替え、終了時に復元する。"""
    agents = _collect_llm_agents(target)
    originals: dict[str, str | BaseLlm] = {}
    try:
        for name, llm in models_by_name.items():
            assert name in agents, f"エージェント {name!r} が見つかりません: {list(agents)}"
            originals[name] = agents[name].model
            agents[name].model = llm
        yield agents
    finally:
        for name, orig in originals.items():
            agents[name].model = orig


def _system_instruction_text(req: LlmRequest) -> str:
    """`LlmRequest.config.system_instruction` を文字列として取り出す。"""
    if not req.config or not req.config.system_instruction:
        return ""
    si = req.config.system_instruction
    if isinstance(si, str):
        return si
    if isinstance(si, types.Content) and si.parts:
        return "".join(p.text for p in si.parts if p.text)
    return str(si)


# =============================================================================
# Lv.1: Single Agent (p01_single_agent)
# =============================================================================
class TestP01SingleAgentRuntime:
    def test_get_current_date_tool_returns_utc_date(self) -> None:
        mod = load_pattern_agent("p01_single_agent")
        res = mod.get_current_date()
        assert "date" in res and len(res["date"]) == 10
        assert res["year"].isdigit()

    @pytest.mark.asyncio
    async def test_single_agent_executes_tool_and_answers(self) -> None:
        mod = load_pattern_agent("p01_single_agent")
        llm = GeminiScriptedLlm(
            [
                _tool_call_resp("get_current_date", {}),
                _text_resp("現在日付を確認しました。Cloud Run はフルマネージド実行環境です。"),
            ]
        )
        with _patch_agent_models(mod.root_agent, {"gcp_docs_agent": llm}):
            ans = await run_agent_final_response(
                mod.root_agent, "gcp_docs_agent", "Cloud Run の最新情報を教えてください"
            )
        assert "Cloud Run" in ans
        assert llm.call_count == 2


# =============================================================================
# Lv.2: ReAct Pattern (p02_react_pattern)
# =============================================================================
class TestP02ReactPatternRuntime:
    def test_calculate_safe_ast_math_and_guards(self) -> None:
        mod = load_pattern_agent("p02_react_pattern")
        assert mod.calculate("100 * 1.08")["result"] == "108.0"
        assert mod.calculate("2 ** 10")["result"] == "1024"
        assert mod.calculate("-5 + 12 // 5")["result"] == "-3"

        # '^'（ビット排他的論理和）の誤用を明示エラーとして案内する
        caret_err = mod.calculate("2 ^ 10")
        assert "error" in caret_err and "**" in caret_err["error"]

        # ゼロ除算・巨大指数・任意コード実行はすべて安全に拒否される
        assert "error" in mod.calculate("10 / 0")
        assert "error" in mod.calculate("2 ** 5000")
        assert "error" in mod.calculate("__import__('os').system('echo unsafe')")

    @pytest.mark.asyncio
    async def test_run_with_react_trace_separates_thought_and_final_answer(self) -> None:
        from rich.console import Console

        mod = load_pattern_agent("p02_react_pattern")
        final_With_thought = LlmResponse(
            content=types.Content(
                role="model",
                parts=[
                    types.Part(text="計算結果 1024 を確認したため最終回答を作成する", thought=True),
                    types.Part.from_text(text="2 の 10 乗は 1024 です。"),
                ],
            )
        )
        llm = GeminiScriptedLlm(
            [
                _tool_call_resp(
                    "calculate",
                    {"expression": "2 ** 10"},
                    thought_text="べき乗を計算ツールで求める",
                ),
                final_With_thought,
            ]
        )
        recorder = Console(record=True, width=100)
        orig_console = mod.console
        mod.console = recorder
        try:
            with _patch_agent_models(mod.root_agent, {"research_react_agent": llm}):
                await mod.run_with_react_trace("2 の 10 乗を計算してください")
        finally:
            mod.console = orig_console

        rendered = recorder.export_text()
        assert "Action" in rendered and "calculate" in rendered
        assert "Observation" in rendered and "1024" in rendered
        assert "Final Answer" in rendered and "2 の 10 乗は 1024 です。" in rendered


# =============================================================================
# Lv.3: Sequential Pattern (p03_sequential)
# =============================================================================
class TestP03SequentialRuntime:
    @pytest.mark.asyncio
    async def test_sequential_pipeline_propagates_state_across_four_steps(self) -> None:
        mod = load_pattern_agent("p03_sequential")
        models = {
            "extractor": GeminiScriptedLlm([_text_resp("EXTRACTED_ROWS=3")]),
            "validator": GeminiScriptedLlm([_text_resp("QUALITY_SCORE=92")]),
            "transformer": GeminiScriptedLlm([_text_resp("TRANSFORMED_NORMALIZED")]),
            "summarizer": GeminiScriptedLlm([_text_resp("# ETL パイプライン実行レポート\n完了")]),
        }
        with _patch_agent_models(mod.root_agent, models):
            text, trajectory = await run_agent_trajectory(
                mod.root_agent, "etl_pipeline", "id,val\n1,10\n2,20\n3,30"
            )

        assert trajectory == ["extractor", "validator", "transformer", "summarizer"]
        assert "ETL パイプライン実行レポート" in text
        # 最終 summarizer のシステムプロンプトに前段 3 ステップの output_key が展開されていること
        summarizer_si = _system_instruction_text(models["summarizer"].requests[0])
        assert "EXTRACTED_ROWS=3" in summarizer_si
        assert "QUALITY_SCORE=92" in summarizer_si
        assert "TRANSFORMED_NORMALIZED" in summarizer_si


# =============================================================================
# Lv.4: Parallel Pattern + JoinNode (p04_parallel)
# =============================================================================
class TestP04ParallelJoinRuntime:
    @pytest.mark.asyncio
    async def test_join_node_runs_synthesizer_exactly_once(self) -> None:
        mod = load_pattern_agent("p04_parallel")
        models = {
            "google_ai_researcher": GeminiScriptedLlm([_text_resp("GOOGLE_AI_TREND")]),
            "openai_researcher": GeminiScriptedLlm([_text_resp("OPENAI_TREND")]),
            "regulation_researcher": GeminiScriptedLlm([_text_resp("EU_AI_ACT_TREND")]),
            "industry_researcher": GeminiScriptedLlm([_text_resp("FINTECH_CASE")]),
            "synthesizer": GeminiScriptedLlm([_text_resp("# AI 最新動向レポート\n統合完了")]),
        }
        with _patch_agent_models(mod.root_agent, models):
            text, trajectory = await run_agent_trajectory(
                mod.root_agent, "news_aggregator", "生成 AI トレンド調査"
            )

        # JoinNode により synthesizer は 4 回ではなく厳密に 1 回だけ呼ばれる
        assert models["synthesizer"].call_count == 1
        assert trajectory[-1] == "synthesizer"
        assert "AI 最新動向レポート" in text

        synth_si = _system_instruction_text(models["synthesizer"].requests[0])
        for expected_piece in (
            "GOOGLE_AI_TREND",
            "OPENAI_TREND",
            "EU_AI_ACT_TREND",
            "FINTECH_CASE",
        ):
            assert expected_piece in synth_si


# =============================================================================
# Lv.5: Loop Pattern (p05_loop)
# =============================================================================
class TestP05LoopRuntime:
    @pytest.mark.asyncio
    async def test_revises_on_failure_and_injects_feedback_on_second_iteration(self) -> None:
        mod = load_pattern_agent("p05_loop")
        gen_llm = GeminiScriptedLlm(
            [
                _text_resp("```python\ndef add(a, b): return a + b\n```"),
                _text_resp("```python\ndef add(a: int, b: int) -> int:\n    return a + b\n```"),
            ]
        )
        tester_llm = GeminiScriptedLlm(
            [
                _text_resp("スコア: 60/100\nステータス: [NEEDS_REVISION]\n型注釈がありません"),
                _text_resp("スコア: 92/100\nステータス: [APPROVED]"),
            ]
        )
        with _patch_agent_models(
            mod.root_agent,
            {"code_generator": gen_llm, "code_tester": tester_llm},
        ):
            text, _ = await run_agent_trajectory(
                mod.root_agent, "code_generation_loop", "加算関数を実装して"
            )

        assert gen_llm.call_count == 2
        assert tester_llm.call_count == 2
        assert "def add(a: int, b: int) -> int:" in text
        # 2 周目の generator プロンプトに 1 周目のフィードバックが含まれている
        second_si = _system_instruction_text(gen_llm.requests[1])
        assert "型注釈がありません" in second_si

    @pytest.mark.asyncio
    async def test_stops_at_max_iterations_when_never_approved(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mod = load_pattern_agent("p05_loop")
        monkeypatch.setattr(mod, "MAX_ITERATIONS", 3)
        gen_llm = GeminiScriptedLlm([_text_resp("def broken(): pass")])
        tester_llm = GeminiScriptedLlm([_text_resp("ステータス: [NEEDS_REVISION]")])

        with _patch_agent_models(
            mod.root_agent,
            {"code_generator": gen_llm, "code_tester": tester_llm},
        ):
            await run_agent_trajectory(
                mod.root_agent, "code_generation_loop", "実装して"
            )

        assert gen_llm.call_count == 3
        assert tester_llm.call_count == 3


# =============================================================================
# Lv.6: Review & Critique Pattern (p06_review_critique)
# =============================================================================
class TestP06ReviewCritiqueRuntime:
    @pytest.mark.asyncio
    async def test_critic_feedback_triggers_generator_revision(self) -> None:
        mod = load_pattern_agent("p06_review_critique")
        gen_llm = GeminiScriptedLlm(
            [
                _text_resp("初稿ドラフト: Cloud Run の紹介"),
                _text_resp("改訂版記事: Cloud Run の具体的な gcloud デプロイ手順付き解説"),
            ]
        )
        critic_llm = GeminiScriptedLlm(
            [
                _text_resp("総合スコア: 68/100\n[NEEDS_REVISION] コード例を追加してください"),
                _text_resp("総合スコア: 88/100\n[APPROVED] - 公開可能です"),
            ]
        )
        with _patch_agent_models(
            mod.root_agent,
            {"blog_generator": gen_llm, "blog_critic": critic_llm},
        ):
            text, _ = await run_agent_trajectory(
                mod.root_agent, "blog_review_loop", "Cloud Run 入門"
            )

        assert gen_llm.call_count == 2
        assert critic_llm.call_count == 2
        assert "改訂版記事" in text
        second_si = _system_instruction_text(gen_llm.requests[1])
        assert "コード例を追加してください" in second_si


# =============================================================================
# Lv.7: Iterative Refinement Pattern (p07_iterative_refinement)
# =============================================================================
class TestP07IterativeRefinementRuntime:
    @pytest.mark.asyncio
    async def test_self_refinement_loops_until_complete(self) -> None:
        mod = load_pattern_agent("p07_iterative_refinement")
        refiner_llm = GeminiScriptedLlm(
            [
                _text_resp(
                    "---DOCUMENT---\n第1版ドキュメント\n---SCORE---\n総合スコア: 72/100\n判定: [CONTINUE]\n---END---"
                ),
                _text_resp(
                    "---DOCUMENT---\n第2版完成ドキュメント\n---SCORE---\n総合スコア: 90/100\n判定: [COMPLETE]\n---END---"
                ),
            ]
        )
        with _patch_agent_models(mod.root_agent, {"doc_refiner": refiner_llm}):
            text, _ = await run_agent_trajectory(
                mod.root_agent, "doc_refinement_loop", "Spanner 入門"
            )

        assert refiner_llm.call_count == 2
        assert "第2版完成ドキュメント" in text
        second_si = _system_instruction_text(refiner_llm.requests[1])
        assert "第1版ドキュメント" in second_si


# =============================================================================
# Lv.8: Coordinator Pattern (p08_coordinator)
# =============================================================================
class TestP08CoordinatorRuntime:
    def test_specialist_tools_return_expected_dicts(self) -> None:
        mod = load_pattern_agent("p08_coordinator")
        assert mod.check_order_status("ORD-001")["status"] == "配送中"
        assert mod.check_order_status("ORD-999")["status"] == "見つかりません"
        assert mod.process_return_request("ORD-001", "破損")["return_status"] == "受付完了"
        assert mod.process_refund("ORD-002", 3000, "重複請求")["refund_amount"] == "¥3,000"
        assert mod.get_product_info("Pixel")["availability"] == "在庫あり"

    @pytest.mark.asyncio
    async def test_coordinator_delegates_to_order_specialist(self) -> None:
        mod = load_pattern_agent("p08_coordinator")
        coord_llm = GeminiScriptedLlm(
            [_tool_call_resp("transfer_to_agent", {"agent_name": "order_specialist"})]
        )
        order_llm = GeminiScriptedLlm(
            [
                _tool_call_resp("check_order_status", {"order_id": "ORD-001"}),
                _text_resp("注文 ORD-001 は現在ヤマト運輸にて配送中です。"),
            ]
        )
        other_llm = GeminiScriptedLlm([_text_resp("unused")])
        with _patch_agent_models(
            mod.root_agent,
            {
                "customer_service_coordinator": coord_llm,
                "order_specialist": order_llm,
                "return_specialist": other_llm,
                "refund_specialist": other_llm,
                "product_specialist": other_llm,
            },
        ):
            text, trajectory = await run_agent_trajectory(
                mod.root_agent,
                "customer_service_coordinator",
                "ORD-001 の配送状況を教えてください",
            )

        assert "order_specialist" in trajectory
        assert "ヤマト運輸" in text
        assert other_llm.call_count == 0


# =============================================================================
# Lv.9: Hierarchical Pattern (p09_hierarchical)
# =============================================================================
class TestP09HierarchicalRuntime:
    @pytest.mark.asyncio
    async def test_downstream_agents_never_raise_keyerror_when_state_keys_missing(
        self,
    ) -> None:
        """動的委譲で一部のワーカーが未実行でも callable instruction が安全に動作する。"""
        mod = load_pattern_agent("p09_hierarchical")
        for target_agent in (
            mod.news_researcher,
            mod.financial_analyst,
            mod.tech_analyst,
            mod.report_coordinator,
        ):
            llm = GeminiScriptedLlm([_text_resp(f"{target_agent.name} 安全完了")])
            orig = target_agent.model
            target_agent.model = llm
            try:
                ans = await run_agent_final_response(
                    target_agent, f"test_{target_agent.name}", "Example Corp を分析して"
                )
                assert f"{target_agent.name} 安全完了" in ans
            finally:
                target_agent.model = orig


# =============================================================================
# Lv.10: Swarm Pattern (p10_swarm)
# =============================================================================
class TestP10SwarmRuntime:
    @pytest.mark.asyncio
    async def test_swarm_iterates_second_round_when_consensus_not_reached(self) -> None:
        mod = load_pattern_agent("p10_swarm")
        market_llm = GeminiScriptedLlm(
            [
                _text_resp("Round1 市場提案"),
                _text_resp("Round2 スコープ調整済み市場提案"),
            ]
        )
        eng_llm = GeminiScriptedLlm(
            [_text_resp("Round1 技術評価"), _text_resp("Round2 技術合意")]
        )
        fin_llm = GeminiScriptedLlm(
            [_text_resp("Round1 財務懸念"), _text_resp("Round2 財務合意 [SWARM_CONSENSUS]")]
        )
        builder_llm = GeminiScriptedLlm(
            [
                _text_resp("未解決課題: 初期コスト超過\n[NEEDS_ANOTHER_ROUND]"),
                _text_resp("# 製品設計コンセンサスドキュメント\n全専門家が合意 [CONSENSUS_REACHED]"),
            ]
        )
        with _patch_agent_models(
            mod.root_agent,
            {
                "market_expert": market_llm,
                "engineer_expert": eng_llm,
                "finance_expert": fin_llm,
                "consensus_builder": builder_llm,
            },
        ):
            text, _ = await run_agent_trajectory(
                mod.root_agent, "product_design_swarm", "リアルタイム翻訳 SaaS"
            )

        assert market_llm.call_count == 2
        assert builder_llm.call_count == 2
        assert "[CONSENSUS_REACHED]" in text
        round2_si = _system_instruction_text(market_llm.requests[1])
        assert "初期コスト超過" in round2_si


# =============================================================================
# Lv.11: Human-in-the-Loop Pattern (p11_human_in_the_loop)
# =============================================================================
class TestP11HumanInTheLoopRuntime:
    @pytest.mark.asyncio
    async def test_auto_approved_bypasses_human_interrupt(self) -> None:
        mod = load_pattern_agent("p11_human_in_the_loop")
        creator_llm = GeminiScriptedLlm([_text_resp("事実ベースの安全な製品紹介原稿")])
        checker_llm = GeminiScriptedLlm(
            [_text_resp("審査スコア: 94/100\n承認ステータス: [AUTO_APPROVED]")]
        )
        pub_llm = GeminiScriptedLlm([_text_resp("# 📢 公開承認済みコンテンツ\n自動公開完了")])

        with _patch_agent_models(
            mod.root_agent,
            {
                "content_creator": creator_llm,
                "compliance_checker": checker_llm,
                "final_publisher": pub_llm,
            },
        ):
            text, trajectory = await run_agent_trajectory(
                mod.app, mod.app.name, "製品紹介原稿を作成して"
            )

        assert pub_llm.call_count == 1
        assert "final_publisher" in trajectory
        assert "自動公開完了" in text

    @pytest.mark.asyncio
    async def test_human_review_required_pauses_and_approve_publishes(self) -> None:
        mod = load_pattern_agent("p11_human_in_the_loop")
        creator_llm = GeminiScriptedLlm([_text_resp("工数 80% 削減を謳う原稿")])
        checker_llm = GeminiScriptedLlm(
            [_text_resp("審査スコア: 75/100\n承認ステータス: [HUMAN_REVIEW_REQUIRED]")]
        )
        pub_llm = GeminiScriptedLlm([_text_resp("# 📢 公開承認済みコンテンツ\n人間承認後に公開")])

        session_service = InMemorySessionService()
        await session_service.create_session(
            app_name=mod.app.name, user_id="u1", session_id="s_approve"
        )
        runner = Runner(app=mod.app, session_service=session_service)

        with _patch_agent_models(
            mod.root_agent,
            {
                "content_creator": creator_llm,
                "compliance_checker": checker_llm,
                "final_publisher": pub_llm,
            },
        ):
            interrupt_fc: types.FunctionCall | None = None
            async for event in runner.run_async(
                user_id="u1",
                session_id="s_approve",
                new_message=types.Content(
                    role="user", parts=[types.Part.from_text(text="原稿作成")]
                ),
            ):
                for fc in event.get_function_calls():
                    if fc.name == "adk_request_input":
                        interrupt_fc = fc

            # 一時停止時点では final_publisher はまだ呼ばれていない
            assert interrupt_fc is not None
            assert pub_llm.call_count == 0

            resumed_text = ""
            async for event in runner.run_async(
                user_id="u1",
                session_id="s_approve",
                new_message=types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            function_response=types.FunctionResponse(
                                id=interrupt_fc.id,
                                name=interrupt_fc.name,
                                response={"result": "APPROVE: 注記追加のうえ承認"},
                            )
                        )
                    ],
                ),
            ):
                if event.content and event.content.parts:
                    resumed_text += "".join(p.text for p in event.content.parts if p.text)

            assert pub_llm.call_count == 1
            assert "人間承認後に公開" in resumed_text

    @pytest.mark.asyncio
    async def test_human_review_reject_blocks_publisher_and_emits_abort_notice(
        self,
    ) -> None:
        mod = load_pattern_agent("p11_human_in_the_loop")
        creator_llm = GeminiScriptedLlm([_text_resp("誇大表現を含む原稿")])
        checker_llm = GeminiScriptedLlm(
            [_text_resp("審査スコア: 55/100\n承認ステータス: [REJECTED]")]
        )
        pub_llm = GeminiScriptedLlm([_text_resp("絶対に呼ばれてはならない公開出力")])

        session_service = InMemorySessionService()
        await session_service.create_session(
            app_name=mod.app.name, user_id="u1", session_id="s_reject"
        )
        runner = Runner(app=mod.app, session_service=session_service)

        with _patch_agent_models(
            mod.root_agent,
            {
                "content_creator": creator_llm,
                "compliance_checker": checker_llm,
                "final_publisher": pub_llm,
            },
        ):
            interrupt_fc: types.FunctionCall | None = None
            async for event in runner.run_async(
                user_id="u1",
                session_id="s_reject",
                new_message=types.Content(
                    role="user", parts=[types.Part.from_text(text="原稿作成")]
                ),
            ):
                for fc in event.get_function_calls():
                    if fc.name == "adk_request_input":
                        interrupt_fc = fc

            assert interrupt_fc is not None

            reject_text = ""
            async for event in runner.run_async(
                user_id="u1",
                session_id="s_reject",
                new_message=types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            function_response=types.FunctionResponse(
                                id=interrupt_fc.id,
                                name=interrupt_fc.name,
                                response={"result": "REJECT: 法務リスクのため公開不可"},
                            )
                        )
                    ],
                ),
            ):
                if event.content and event.content.parts:
                    reject_text += "".join(p.text for p in event.content.parts if p.text)

            # 却下時は final_publisher が 0 回のまま終了し、中止通知が出力される
            assert pub_llm.call_count == 0
            assert "コンテンツ公開中止" in reject_text


# =============================================================================
# Capstone: Enterprise Research Workflow (capstone)
# =============================================================================
class TestCapstoneRuntime:
    @pytest.mark.asyncio
    async def test_capstone_join_and_review_loop_end_to_end(self) -> None:
        mod = load_pattern_agent("capstone")
        models = {
            "enterprise_research_coordinator": GeminiScriptedLlm(
                [_text_resp("対象企業: Example Cloud Corp")]
            ),
            "enterprise_web_researcher": GeminiScriptedLlm([_text_resp("WEB_INFO")]),
            "enterprise_tech_researcher": GeminiScriptedLlm([_text_resp("TECH_STACK_INFO")]),
            "enterprise_financial_researcher": GeminiScriptedLlm([_text_resp("FINANCE_INFO")]),
            "enterprise_analyst": GeminiScriptedLlm([_text_resp("SWOT_ANALYSIS_DONE")]),
            "enterprise_report_writer": GeminiScriptedLlm(
                [
                    _text_resp("初版レポートドラフト"),
                    _text_resp("# 企業技術戦略評価レポート\n改訂完成版"),
                ]
            ),
            "enterprise_report_critic": GeminiScriptedLlm(
                [
                    _text_resp("総合スコア: 78/100\n[NEEDS_IMPROVEMENT] 財務数値を補強してください"),
                    _text_resp("総合スコア: 92/100\n[REPORT_APPROVED] - 配布可能"),
                ]
            ),
        }
        with _patch_agent_models(mod.root_agent, models):
            text, _ = await run_agent_trajectory(
                mod.root_agent, "enterprise_research_workflow", "Example Cloud Corp を分析"
            )

        # JoinNode により enterprise_analyst は 3 回ではなく 1 回だけ実行される
        assert models["enterprise_analyst"].call_count == 1
        # Review & Critique ループにより writer と critic は 2 回ずつ実行される
        assert models["enterprise_report_writer"].call_count == 2
        assert models["enterprise_report_critic"].call_count == 2
        assert "改訂完成版" in text
        writer_second_si = _system_instruction_text(
            models["enterprise_report_writer"].requests[1]
        )
        assert "財務数値を補強してください" in writer_second_si


# =============================================================================
# Agentic Pipeline: PGEOrchestrator (agentic_pipeline)
# =============================================================================
class TestAgenticPipelineRuntime:
    @pytest.mark.asyncio
    async def test_pge_orchestrator_iterates_revise_then_approved(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        mod = load_pattern_agent("agentic_pipeline")
        calls: list[str] = []

        async def _fake_planner(user_request: str, tool_context: Any) -> str:
            calls.append("planner")
            return '{"architecture": "clean", "modules": ["app.py"], "test_strategy": "pytest", "directory_structure": "app.py"}'

        async def _fake_generator(plan: str, tool_context: Any) -> str:
            calls.append("generator")
            (tmp_path / "app.py").write_text("def hello() -> str:\n    return 'ok'\n")
            return '{"files_created": ["app.py"], "summary": "implemented"}'

        eval_Count = 0

        async def _fake_evaluator(plan: str, artifact: str, tool_context: Any) -> str:
            nonlocal eval_Count
            eval_Count += 1
            calls.append(f"evaluator_{eval_Count}")
            if eval_Count == 1:
                return "REVISE: score=68. テストケースを追加してください"
            return "APPROVED: score=91. すべての品質基準を満たしています"

        monkeypatch.setattr(mod, "run_planner_agent", _fake_planner)
        monkeypatch.setattr(mod, "run_generator_agent", _fake_generator)
        monkeypatch.setattr(mod, "run_evaluator_agent", _fake_evaluator)

        text, trajectory = await run_agent_trajectory(
            mod.root_agent,
            "agentic_pipeline",
            "シンプルな挨拶モジュールを作成してください",
            initial_state={"output_dir": str(tmp_path)},
        )

        assert calls == [
            "planner",
            "generator",
            "evaluator_1",
            "planner",
            "generator",
            "evaluator_2",
        ]
        assert "agentic_pipeline" in trajectory
        assert "APPROVED" in text
        assert "app.py" in text


# =============================================================================
# Shared Demo Runner & All 13 `demo.py` Modules Smoke Test
# =============================================================================
class TestDemoModulesAndRunner:
    def test_all_pattern_demo_modules_import_cleanly(self) -> None:
        demo_packages = [
            "p01_single_agent",
            "p02_react_pattern",
            "p03_sequential",
            "p04_parallel",
            "p05_loop",
            "p06_review_critique",
            "p07_iterative_refinement",
            "p08_coordinator",
            "p09_hierarchical",
            "p10_swarm",
            "p11_human_in_the_loop",
            "capstone",
            "agentic_pipeline",
        ]
        for pkg in demo_packages:
            demo_mod = importlib.import_module(f"patterns.{pkg}.demo")
            assert demo_mod is not None

    @pytest.mark.asyncio
    async def test_shared_demo_runner_formats_multi_agent_and_filters_thoughts(
        self,
    ) -> None:
        from rich.console import Console

        import shared.demo_runner as dr

        mod = load_pattern_agent("p03_sequential")
        thought_and_text = LlmResponse(
            content=types.Content(
                role="model",
                parts=[
                    types.Part(text="内部推論メモ（非表示になるべき）", thought=True),
                    types.Part.from_text(text="最終サマリー出力"),
                ],
            )
        )
        models = {
            "extractor": GeminiScriptedLlm([_text_resp("抽出OK")]),
            "validator": GeminiScriptedLlm([_text_resp("検証OK")]),
            "transformer": GeminiScriptedLlm([_text_resp("変換OK")]),
            "summarizer": GeminiScriptedLlm([thought_and_text]),
        }
        recorder = Console(record=True, width=100)
        orig_console = dr.console
        dr.console = recorder
        try:
            with _patch_agent_models(mod.root_agent, models):
                await dr.run_agent_demo(mod.root_agent, "etl_pipeline", ["a,b\n1,2"])
        finally:
            dr.console = orig_console

        rendered = recorder.export_text()
        assert "[extractor]" in rendered
        assert "[summarizer]" in rendered
        assert "最終サマリー出力" in rendered
        assert "内部推論メモ（非表示になるべき）" not in rendered
