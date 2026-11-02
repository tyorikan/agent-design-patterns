"""agents_cli_patterns（CLI-01 〜 CLI-04）の単体・結合テスト。

クラウド認証やネットワークアクセスを一切行わず、以下をインプロセスで検証する。
- 全 4 サブプロジェクトの `agents-cli` マニフェスト・仕様書・コンテキストファイル整合性
- CLI-01: SLO エラーバジェット計算・Runbook 検索・構造化エラーフィードバック検証
- CLI-02: FinOps ツール・`eval_config.yaml` インライン採点関数・CI 評価ゲート（exit 0 / exit 1）
- CLI-03: IAM / セキュリティ勧告ツール・FastAPI Lifespan + A2A AgentCard エンドポイント配信
- CLI-04: Retriever 抽象化 / 依存性注入・`global` 回避リージョン解決・`/healthz` エンドポイント
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI_ROOT = REPO_ROOT / "agents_cli_patterns"

SUBPROJECTS = (
    "cli01_spec_driven_agent",
    "cli02_evaluation_gate",
    "cli03_a2a_interoperability",
    "cli04_grounded_rag_deploy",
)


class TestAgentsCliProjectScaffolds:
    """全 4 パターンが `agents-cli 1.12+` 準拠の標準ファイル構成を持つことを検証する。"""

    @pytest.mark.parametrize("subproject", SUBPROJECTS)
    def test_required_project_files_exist(self, subproject: str) -> None:
        proj_dir = CLI_ROOT / subproject
        for rel in (
            "agents-cli-manifest.yaml",
            ".agents-cli-spec.md",
            "AGENTS.md",
            "pyproject.toml",
            "README.md",
            "demo.py",
            "app/__init__.py",
            "app/agent.py",
        ):
            target = proj_dir / rel
            assert target.is_file(), f"必須ファイルが不足しています: {target}"

    @pytest.mark.parametrize("subproject", SUBPROJECTS)
    def test_manifest_schema_valid(self, subproject: str) -> None:
        manifest_path = CLI_ROOT / subproject / "agents-cli-manifest.yaml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        assert manifest["acli_version"] == "1.12.0"
        assert manifest["agent_directory"] == "app"
        assert manifest["framework"] == "google-adk"
        assert manifest["create_params"]["deployment_target"] in {"agent_runtime", "cloud_run"}


class TestCli01SpecDrivenAgent:
    """CLI-01: Spec-Driven Agent のツール・App 構造を検証する。"""

    def test_app_and_root_agent_contract(self) -> None:
        from agents_cli_patterns.cli01_spec_driven_agent.app.agent import app, root_agent

        assert app.name == "app"
        assert app.root_agent is root_agent
        assert root_agent.name == "slo_diagnostics_agent"
        assert root_agent.model == "gemini-3.8-flash"

    def test_calculate_error_budget_statuses(self) -> None:
        from agents_cli_patterns.cli01_spec_driven_agent.app.agent import calculate_error_budget

        # 30日 = 43,200分、SLO 99.9% => 許容ダウンタイム 43.2分
        healthy = calculate_error_budget(99.9, consumed_downtime_minutes=10.0, window_days=30)
        assert healthy["allowed_downtime_minutes"] == 43.2
        assert healthy["remaining_budget_minutes"] == 33.2
        assert healthy["status"] == "HEALTHY"

        warning = calculate_error_budget(99.9, consumed_downtime_minutes=35.0, window_days=30)
        assert warning["status"] == "WARNING"

        exhausted = calculate_error_budget(99.9, consumed_downtime_minutes=50.0, window_days=30)
        assert exhausted["remaining_budget_minutes"] == -6.8
        assert exhausted["status"] == "EXHAUSTED"

    def test_calculate_error_budget_structured_validation(self) -> None:
        from agents_cli_patterns.cli01_spec_driven_agent.app.agent import calculate_error_budget

        assert "error" in calculate_error_budget(100.0, 5.0)
        assert "error" in calculate_error_budget(0.0, 5.0)
        assert "error" in calculate_error_budget(99.9, -1.0)
        assert "error" in calculate_error_budget(99.9, 5.0, window_days=0)

    def test_lookup_runbook_known_and_unknown(self) -> None:
        from agents_cli_patterns.cli01_spec_driven_agent.app.agent import lookup_runbook

        hit = lookup_runbook("LATENCY")
        assert hit["found"] is True
        assert hit["category"] == "latency"
        assert len(hit["checks"]) >= 3

        miss = lookup_runbook("unknown_symptom")
        assert miss["found"] is False
        assert "latency" in miss["available_categories"]
        assert "hint" in miss


class TestCli02EvaluationGate:
    """CLI-02: 評価データセット・インライン採点関数・CI 評価ゲートを検証する。"""

    def test_finops_tools(self) -> None:
        from agents_cli_patterns.cli02_evaluation_gate.app.agent import (
            estimate_savings,
            inspect_cost_spike,
        )

        bq = inspect_cost_spike("bigquery")
        assert bq["found"] is True
        assert bq["spike_ratio"] == 4.5

        unknown = inspect_cost_spike("nonexistent")
        assert unknown["found"] is False

        savings = estimate_savings(2000.0, 60.0)
        assert savings["monthly_savings_usd"] == 1200.0
        assert savings["annual_savings_usd"] == 14400.0
        assert savings["projected_monthly_usd"] == 800.0

        assert "error" in estimate_savings(-10.0, 50.0)
        assert "error" in estimate_savings(100.0, 120.0)

    def test_eval_config_and_inline_custom_metrics(self) -> None:
        eval_dir = CLI_ROOT / "cli02_evaluation_gate" / "tests" / "eval"
        cfg = yaml.safe_load((eval_dir / "eval_config.yaml").read_text(encoding="utf-8"))
        assert set(cfg["metrics_to_run"]) == {
            "custom_response_quality",
            "non_empty_structured_answer",
            "agent_turn_count",
        }

        dataset = json.loads(
            (eval_dir / "datasets" / "basic-dataset.json").read_text(encoding="utf-8")
        )
        assert len(dataset["eval_cases"]) >= 2

        # インライン Python メトリクスを実行して採点ロジックを検証
        inline_fns: dict[str, Any] = {}
        for metric_def in cfg["custom_metrics"]:
            if "custom_function" in metric_def:
                ns: dict[str, Any] = {}
                exec(metric_def["custom_function"], ns)
                inline_fns[metric_def["name"]] = ns["evaluate"]

        assert (
            inline_fns["non_empty_structured_answer"](
                {"response": "原因はフルスキャン集計であり、対策後の月額は $800 です。"}
            )["score"]
            == 1.0
        )
        assert inline_fns["non_empty_structured_answer"]({"response": "短い"})["score"] == 0.0
        assert (
            inline_fns["agent_turn_count"]({"agent_data": {"turns": [{"id": 1}, {"id": 2}]}})[
                "score"
            ]
            == 2.0
        )

    def test_ci_eval_gate_pass_and_block(self, tmp_path: Path) -> None:
        gate_script = CLI_ROOT / "cli02_evaluation_gate" / "scripts" / "ci_eval_gate.py"
        spec = importlib.util.spec_from_file_location("ci_eval_gate", gate_script)
        assert spec and spec.loader
        gate_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gate_mod)

        pass_file = tmp_path / "results_pass.json"
        pass_file.write_text(
            json.dumps(
                {
                    "summary_metrics": [
                        {"metric_name": "custom_response_quality", "mean_score": 4.5},
                        {"metric_name": "non_empty_structured_answer", "mean_score": 1.0},
                        {"metric_name": "agent_turn_count", "mean_score": 1.0},
                    ]
                }
            ),
            encoding="utf-8",
        )
        assert gate_mod.main(["--result-file", str(pass_file)]) == 0

        fail_file = tmp_path / "results_fail.json"
        fail_file.write_text(
            json.dumps(
                {
                    "summary_metrics": [
                        {"metric_name": "custom_response_quality", "mean_score": 2.5},
                        {"metric_name": "non_empty_structured_answer", "mean_score": 1.0},
                        {"metric_name": "agent_turn_count", "mean_score": 1.0},
                    ]
                }
            ),
            encoding="utf-8",
        )
        assert gate_mod.main(["--result-file", str(fail_file)]) == 1


class TestCli03A2aInteroperability:
    """CLI-03: IAM / 勧告ツールと A2A AgentCard エンドポイントを検証する。"""

    def test_security_tools(self) -> None:
        from agents_cli_patterns.cli03_a2a_interoperability.app.agent import (
            evaluate_iam_binding,
            lookup_security_advisory,
        )

        owner = evaluate_iam_binding("roles/owner")
        assert owner["risk_level"] == "CRITICAL"

        public = evaluate_iam_binding("roles/run.invoker", principal_type="allUsers")
        assert public["risk_level"] == "CRITICAL"

        low = evaluate_iam_binding("roles/aiplatform.user")
        assert low["risk_level"] == "LOW"

        adv = lookup_security_advisory("adv-2026-0204")
        assert adv["found"] is True
        assert adv["severity"] == "HIGH"

    @pytest.mark.asyncio
    async def test_a2a_well_known_agent_card_served(self) -> None:
        from agents_cli_patterns.cli03_a2a_interoperability.app import fast_api_app

        async with fast_api_app.app.router.lifespan_context(fast_api_app.app):
            transport = httpx.ASGITransport(app=fast_api_app.app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                resp = await client.get("/a2a/app/.well-known/agent-card.json")
                assert resp.status_code == 200
                card = resp.json()
                assert card["name"] == "security_advisory_agent"
                assert len(card.get("skills", [])) >= 1
                interfaces = card.get("supportedInterfaces", [])
                assert any(iface.get("protocolBinding") == "JSONRPC" for iface in interfaces)


class TestCli04GroundedRagDeploy:
    """CLI-04: Retriever 注入・リージョン分離・FastAPI `/healthz` を検証する。"""

    def test_local_corpus_retriever_and_di(self) -> None:
        from agents_cli_patterns.cli04_grounded_rag_deploy.app.agent import (
            search_architecture_policies,
            set_retriever_for_testing,
        )
        from agents_cli_patterns.cli04_grounded_rag_deploy.app.retriever import (
            LocalCorpusRetriever,
            RetrievedChunk,
        )

        retriever = LocalCorpusRetriever()
        hits = retriever.search("RPO RTO マルチリージョン Idempotency-Key", top_k=2)
        assert len(hits) >= 1
        assert hits[0].doc_id == "DOC-ARCH-001"
        assert retriever.search("") == []

        class _FakeRetriever:
            def search(self, query: str, top_k: int = 3) -> list[RetrievedChunk]:
                return [
                    RetrievedChunk(
                        doc_id="DOC-TEST-999",
                        title="テスト規定",
                        snippet=f"query={query}",
                        score=0.99,
                    )
                ]

        try:
            set_retriever_for_testing(_FakeRetriever())
            res = search_architecture_policies("テスト検索", top_k=1)
            assert res["match_count"] == 1
            assert res["citations"][0]["doc_id"] == "DOC-TEST-999"
        finally:
            set_retriever_for_testing(None)

    def test_resolve_session_region_avoids_global(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from agents_cli_patterns.cli04_grounded_rag_deploy.app.app_utils.services import (
            resolve_session_region,
        )

        monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "global")
        monkeypatch.delenv("GOOGLE_CLOUD_AGENT_ENGINE_LOCATION", raising=False)
        assert resolve_session_region() == "us-central1"

        monkeypatch.setenv("GOOGLE_CLOUD_AGENT_ENGINE_LOCATION", "asia-northeast1")
        assert resolve_session_region() == "asia-northeast1"

    @pytest.mark.asyncio
    async def test_healthz_endpoint(self) -> None:
        from agents_cli_patterns.cli04_grounded_rag_deploy.app.fast_api_app import app

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.get("/healthz")
            assert resp.status_code == 200
            body = resp.json()
            assert body["status"] == "ok"
            assert body["session_region"] != "global"
