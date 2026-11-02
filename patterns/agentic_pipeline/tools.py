"""Antigravity Agent ラッパーツール（google-antigravity 0.1.23+ 対応）。

ADK の BaseAgent（PGEOrchestrator）から呼び出されるフェーズ実行関数として、
各 Antigravity Agent（Planner / Generator / Evaluator）を構成・実行する。

主な SDK 機能構成（google-antigravity 0.1.23+）:
    - 認証: `GEMINI_API_KEY` 設定時は Gemini Developer API、未設定時は Vertex AI ADC（`project` / `location`）
    - 9段階優先度ポリシー: `workspace_only` + 個別コマンド拒否（`deny("run_command", when=...)`）+ 名前付きワイルドカード許可（`allow("*")`）
    - コマンド実行隔離: `RunCommandConfig(enable_sandbox=True, timeout_seconds=120.0, enable_daemons=False)`
    - セッション予算・履歴圧縮・リトライ: フェーズ別 `BudgetConfig` / `CompactionConfig` / `RetryConfig`
    - 観測性とデータ隔離: `agent.conversation.total_usage` によるトークン計測と一時 `app_data_dir` 分離
"""

import json
import logging
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from google.adk.tools.tool_context import ToolContext

from shared.config import get_settings

from .prompts import (
    GENERATOR_SYSTEM_PROMPT,
    PLANNER_SYSTEM_PROMPT,
    build_evaluator_system_prompt,
)
from .schemas import ArtifactOutput, EvaluationOutput, PlanOutput

if TYPE_CHECKING:
    from google.antigravity import LocalAgentConfig


class StateContext(Protocol):
    """`state` 辞書を保持するコンテキストの最小プロトコル（`ToolContext` および `_StateProxy` 互換）。"""

    state: Any


logger = logging.getLogger(__name__)

# デフォルト出力ディレクトリ（生成コードの書き出し先）
DEFAULT_OUTPUT_DIR = Path(__file__).parent / "output"
DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 後方互換: テストなどで直接参照しているコード用
OUTPUT_DIR = DEFAULT_OUTPUT_DIR

# コマンド実行タイムアウト・履歴圧縮閾値・フェーズ別予算上限（max_model_calls, max_tool_calls, max_total_tokens）
DEFAULT_COMMAND_TIMEOUT_SECONDS = 120.0
DEFAULT_COMPACTION_TOKEN_THRESHOLD = 120_000
STAGE_BUDGET_LIMITS: dict[str, tuple[int, int, int]] = {
    "planner": (12, 15, 200_000),
    "generator": (30, 60, 500_000),
    "evaluator": (25, 45, 400_000),
}

# ファイル変更・破壊系オプションのブロックパターン（Evaluator での書き換えや危険操作を遮断）
_BLOCKED_FLAG_SUBSTRINGS: tuple[str, ...] = ("--fix", "install -g")
_BLOCKED_COMMAND_RE = re.compile(r"(?:^|[;&|()\s])(?:rm|rmdir|sudo)\b")

# テスト・lint・ビルド・起動検証で許可するコマンドプレフィックス
_ALLOWED_COMMAND_PREFIXES: tuple[str, ...] = (
    # テスト・lint
    "pytest",
    "python -m pytest",
    "python3 -m pytest",
    "ruff check",
    # Python
    "python ",
    "python3 ",
    "pip install",
    "pip check",
    "uv run",
    # Docker / Podman
    "docker build",
    "docker compose",
    "docker run",
    "podman build",
    "podman-compose",
    "podman run",
    # Node.js
    "npm run",
    "npm test",
    "npm start",
    "npx ",
    "node ",
    "yarn ",
    "pnpm ",
    # Go
    "go build",
    "go test",
    "go vet",
    "go run",
    # Make / Shell 参照・ディレクトリ作成
    "make",
    "mkdir ",
    "echo ",
    "sh ",
    "bash ",
    "cat ",
    "head ",
    "tail ",
    "ls",
    "find ",
    "wc ",
    "grep ",
    # Terraform / IaC
    "terraform validate",
    "terraform plan",
    "terraform fmt",
    # Misc
    "curl ",
    "java ",
    "javac ",
    "mvn ",
    "gradle ",
)

# 先頭の環境変数代入（例: PYTHONPATH=src）やディレクトリ移動（cd <dir> &&）を剥がす正規表現
_LEADING_ENV_OR_CD_RE = re.compile(
    r"^(?:(?:[A-Za-z_][A-Za-z0-9_]*=(?:\"[^\"]*\"|'[^']*'|\S+)\s+)|(?:cd\s+(?:\"[^\"]*\"|'[^']*'|\S+)\s*&&\s*))+"
)


def _load_antigravity_sdk() -> tuple[Any, Any, Any, Any, Any, Any]:
    """Antigravity SDK モジュールを遅延ロードする。

    軽量テスト環境でもモジュールインポート自体は壊れないよう、実行・設定構築時に読み込む。
    """
    from google.antigravity import Agent, CapabilitiesConfig, LocalAgentConfig
    from google.antigravity import types as agy_types
    from google.antigravity.hooks import policy
    from google.antigravity.types import BuiltinTools

    return Agent, BuiltinTools, CapabilitiesConfig, LocalAgentConfig, policy, agy_types


def _resolve_output_dir(tool_context: ToolContext | StateContext) -> Path:
    """state['output_dir'] から出力ディレクトリを解決する。

    `adk run --state '{"output_dir": "/path/to/project"}'` で
    任意のディレクトリを対象にできる。未指定ならデフォルト。
    """
    output_dir_str = tool_context.state.get("output_dir", "")
    if output_dir_str:
        p = Path(output_dir_str).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p
    return DEFAULT_OUTPUT_DIR


def _is_allowed_command(command_line: str) -> bool:
    """検証・ビルド用シェルコマンドとして許可されるかを判定する。"""
    cmd = command_line.strip()
    if not cmd:
        return False
    if any(flag in cmd for flag in _BLOCKED_FLAG_SUBSTRINGS):
        return False
    if _BLOCKED_COMMAND_RE.search(cmd):
        return False
    normalized = _LEADING_ENV_OR_CD_RE.sub("", cmd).strip()
    if normalized == "ls" or normalized.startswith("ls "):
        return True
    return normalized.startswith(_ALLOWED_COMMAND_PREFIXES)


def _build_config(
    system_instructions: str,
    response_schema: type | None = None,
    allow_commands: bool = False,
    allow_writes: bool = True,
    workspace_dir: str | None = None,
    stage: str = "generator",
    app_data_dir: str | None = None,
) -> "LocalAgentConfig":
    """Antigravity Agent の共通設定（google-antigravity 0.1.23+ 対応）を構築する。

    `GEMINI_API_KEY` が設定されていれば Gemini API エンドポイントを優先し、
    未設定の場合は `Settings`（Vertex AI ADC + `default_model`）を使用する。

    Args:
        system_instructions: エージェントのシステムプロンプト
        response_schema: 構造化出力のスキーマ（Pydantic モデル）
        allow_commands: True の場合、テスト・lint 等の検証コマンド実行と OS サンドボックスを有効化する
        allow_writes: False の場合、create_file / edit_file ツールをモデルコンテキストから無効化する
        workspace_dir: ファイル操作を制限するワークスペースディレクトリ
        stage: フェーズ識別子（`"planner"` / `"generator"` / `"evaluator"`）に応じた `BudgetConfig` を適用する
        app_data_dir: Antigravity 一時データ・スクラッチ保存先ディレクトリ（絶対パス）
    """
    (
        _,
        BuiltinTools,
        CapabilitiesConfig,
        LocalAgentConfig,
        policy,
        agy_types,
    ) = _load_antigravity_sdk()
    settings = get_settings()
    api_key = os.environ.get("GEMINI_API_KEY") or settings.gemini_api_key

    # ポリシー構築（google-antigravity 0.1.23+ の 9 段階優先度・未一致 Fail-Closed 仕様に対応）:
    # `policies` をカスタム指定すると既定の `confirm_run_command()` が置き換わるため、
    # 許可対象外コマンドを個別拒否（Specific Deny）した上で、ファイル操作・finish 等の
    # ワークスペース内ツールを名前付きワイルドカード許可（`allow("*")`）する。
    # `allow_all()` ではなく名前付き `allow("*")` と `workspace_only` を併用することで、
    # 出力ディレクトリ外へのファイルアクセス制限を維持する。
    policies: list[Any] = []
    if allow_commands:
        if workspace_dir:
            policies.extend(policy.workspace_only([workspace_dir]))
        policies.append(
            policy.deny(
                "run_command",
                when=lambda args: not _is_allowed_command(
                    args.get("CommandLine", "")
                ),
                name="restrict_run_command",
                reason=(
                    "許可されていないコマンド、または変更系オプション（--fix / rm / sudo 等）が含まれています。"
                ),
            )
        )
        policies.append(policy.allow("*", name="allow_workspace_tools"))
    elif workspace_dir:
        policies.extend(policy.workspace_only([workspace_dir]))
        policies.extend(policy.confirm_run_command())

    run_command_cfg = (
        agy_types.RunCommandConfig(
            enable_sandbox=True,
            timeout_seconds=DEFAULT_COMMAND_TIMEOUT_SECONDS,
            enable_daemons=False,
        )
        if allow_commands
        else None
    )

    capabilities = CapabilitiesConfig(
        enable_subagents=False,
        run_command_config=run_command_cfg,
        disabled_tools=(
            None
            if allow_writes
            else [BuiltinTools.CREATE_FILE, BuiltinTools.EDIT_FILE]
        ),
    )

    max_models, max_tools, max_tokens = STAGE_BUDGET_LIMITS.get(
        stage, STAGE_BUDGET_LIMITS["generator"]
    )
    budget_config = agy_types.BudgetConfig(
        max_model_calls=max_models,
        max_tool_calls=max_tools,
        max_total_tokens=max_tokens,
    )
    compaction_config = agy_types.CompactionConfig(
        token_threshold=DEFAULT_COMPACTION_TOKEN_THRESHOLD
    )
    retry_config = agy_types.RetryConfig(
        api_retry=agy_types.ModelAPIRetryConfig(
            max_retries=3,
            initial_sleep_duration_ms=1000,
            exponential_multiplier=2.0,
            jitter_range=0.1,
        ),
        model_output_retry=agy_types.ModelOutputRetryConfig(max_retries=3),
    )

    venv_bin = str(Path(sys.executable).resolve().parent)
    current_path = os.environ.get("PATH", "")
    path_parts = current_path.split(os.pathsep) if current_path else []
    merged_path = (
        os.pathsep.join([venv_bin, *path_parts])
        if venv_bin not in path_parts
        else current_path
    )

    config_kwargs: dict[str, Any] = {
        "system_instructions": system_instructions,
        "response_schema": response_schema,
        "model": settings.default_model,
        "capabilities": capabilities,
        "budget_config": budget_config,
        "compaction_config": compaction_config,
        "retry_config": retry_config,
        "env": {"PATH": merged_path},
    }
    if api_key:
        config_kwargs["api_key"] = api_key
        config_kwargs["vertex"] = False
    else:
        config_kwargs["vertex"] = settings.google_genai_use_vertexai
        config_kwargs["project"] = settings.google_cloud_project
        config_kwargs["location"] = settings.google_cloud_location

    if policies:
        config_kwargs["policies"] = policies
    if workspace_dir:
        config_kwargs["workspaces"] = [workspace_dir]
    if app_data_dir:
        config_kwargs["app_data_dir"] = str(Path(app_data_dir).resolve())

    return LocalAgentConfig(**config_kwargs)


def _record_usage_entry(
    tool_context: ToolContext | StateContext,
    stage: str,
    usage: Any,
    stop_reason: Any,
) -> dict[str, Any]:
    """セッション終了時のトークン消費量と停止理由を `usage_history` 状態に追記する。"""
    stop_value = (
        str(stop_reason.value)
        if hasattr(stop_reason, "value")
        else str(stop_reason or "UNSPECIFIED")
    )
    entry = {
        "stage": stage,
        "prompt_tokens": int(getattr(usage, "prompt_token_count", 0) or 0),
        "cached_tokens": int(getattr(usage, "cached_content_token_count", 0) or 0),
        "candidates_tokens": int(getattr(usage, "candidates_token_count", 0) or 0),
        "thoughts_tokens": int(getattr(usage, "thoughts_token_count", 0) or 0),
        "total_tokens": int(getattr(usage, "total_token_count", 0) or 0),
        "stop_reason": stop_value,
    }
    history_raw = tool_context.state.get("usage_history", "[]")
    try:
        history: list[dict[str, Any]] = json.loads(history_raw)
    except (json.JSONDecodeError, TypeError):
        history = []
    history.append(entry)
    tool_context.state["usage_history"] = json.dumps(history, ensure_ascii=False)

    if stop_value != "UNSPECIFIED":
        logger.warning(
            "Antigravity [%s] セッションが予算またはクォータ制限で停止しました: stop_reason=%s, total_tokens=%d",
            stage,
            stop_value,
            entry["total_tokens"],
        )
    else:
        logger.info(
            "Antigravity [%s] usage: total=%d (prompt=%d, candidates=%d, thoughts=%d)",
            stage,
            entry["total_tokens"],
            entry["prompt_tokens"],
            entry["candidates_tokens"],
            entry["thoughts_tokens"],
        )
    return entry


async def _execute_antigravity_turn(
    *,
    stage: str,
    prompt: str,
    tool_context: ToolContext | StateContext,
    system_instructions: str,
    response_schema: type | None,
    allow_commands: bool,
    allow_writes: bool,
    workspace_dir: str | None,
) -> tuple[dict[str, Any] | None, str]:
    """一時 `app_data_dir` 上で Antigravity Agent を 1 セッション実行し、構造化出力と使用量を回収する。"""
    Agent, _, _, _, _, _ = _load_antigravity_sdk()
    with tempfile.TemporaryDirectory(prefix=f"antigravity_{stage}_") as tmp_app_data:
        config = _build_config(
            system_instructions=system_instructions,
            response_schema=response_schema,
            allow_commands=allow_commands,
            allow_writes=allow_writes,
            workspace_dir=workspace_dir,
            stage=stage,
            app_data_dir=tmp_app_data,
        )
        async with Agent(config) as agent:
            response = await agent.chat(prompt)
            structured = await response.structured_output()
            fallback_text = await response.text() if structured is None else ""
            usage = agent.conversation.total_usage
            stop_reason = response.stop_reason

    _record_usage_entry(tool_context, stage, usage, stop_reason)
    return structured, fallback_text


async def run_planner_agent(
    user_request: str,
    tool_context: ToolContext | StateContext,
) -> str:
    """Antigravity Agent を使ってソフトウェア設計方針を策定する。

    初回はゼロから設計し、再設計時は evaluator_feedback を参照して
    設計方針を見直す。Planner は読み取り専用（ファイル書き込み・シェル実行とも無効）で動作する。

    Args:
        user_request: ユーザーの要件（例: "FastAPI で TODO アプリの REST API を実装"）
    """
    feedback = tool_context.state.get("evaluator_feedback", "")
    score_history_raw = tool_context.state.get("score_history", "[]")
    score_history: list[int] = json.loads(score_history_raw)
    prev_score = score_history[-1] if score_history else 0

    prompt = f"要件: {user_request}"

    # 既存プロジェクトのコンテキスト（初回のみ）
    resolved_dir = _resolve_output_dir(tool_context)
    output_dir = str(resolved_dir)
    existing_files = list(resolved_dir.rglob("*.py"))
    existing_files = [f for f in existing_files if "__pycache__" not in str(f)]
    if existing_files and not feedback:
        prompt += (
            f"\n\n## 既存プロジェクト情報\n"
            f"対象ディレクトリ: {resolved_dir}\n"
            f"**重要: これは既存プロジェクトへの機能追加・改修です。**\n"
            f"既存のコード構造・設計パターン・命名規則を尊重し、\n"
            f"既存コードとの整合性を保った設計方針を策定してください。\n\n"
            f"### 既存ファイル一覧\n"
        )
        for f in sorted(existing_files):
            rel = f.relative_to(resolved_dir)
            prompt += f"- {rel}\n"
        logger.info(
            "Planner: 既存プロジェクト改修モード（%d ファイル）", len(existing_files)
        )

    if feedback:
        if prev_score >= 60:
            # スコアが一定以上 → 既存設計を維持し、指摘点のみ修正
            prompt += (
                f"\n\n## 前回の評価フィードバック（前回スコア: {prev_score}）\n"
                f"**重要: 既存の設計・アーキテクチャは維持し、以下の指摘点のみを修正する設計変更を行ってください。**\n"
                f"全面的な再設計は禁止です。前回の成果物をベースに、差分修正の方針を策定してください。\n\n"
                f"{feedback}"
            )
            logger.info("Planner: 差分修正モード（score=%d、既存設計維持）", prev_score)
        else:
            # スコアが低い → 根本的に見直す
            prompt += (
                f"\n\n## 前回の評価フィードバック（前回スコア: {prev_score}）\n"
                f"設計に根本的な問題があります。アーキテクチャを見直してください。\n\n"
                f"{feedback}"
            )
            logger.info("Planner: 再設計モード（score=%d、根本的見直し）", prev_score)
    elif not existing_files:
        logger.info("Planner: 初回設計モード（新規プロジェクト）")

    result, fallback_text = await _execute_antigravity_turn(
        stage="planner",
        prompt=prompt,
        tool_context=tool_context,
        system_instructions=PLANNER_SYSTEM_PROMPT,
        response_schema=PlanOutput,
        allow_commands=False,
        allow_writes=False,
        workspace_dir=output_dir,
    )

    if result is None:
        tool_context.state["plan"] = fallback_text
        return fallback_text

    result_json = json.dumps(result, ensure_ascii=False)
    tool_context.state["plan"] = result_json
    logger.info("Planner: 設計方針策定完了")
    return result_json


async def run_generator_agent(
    plan: str,
    tool_context: ToolContext | StateContext,
) -> str:
    """Antigravity Agent を使ってコードを実装する。

    設計方針に基づいてコードとテストを生成し、
    create_file / edit_file ツールで出力ディレクトリに書き出す。

    Args:
        plan: Planner が策定した設計方針（JSON 文字列）
    """
    resolved_dir = _resolve_output_dir(tool_context)
    output_dir = str(resolved_dir)

    # 既存ファイルがある場合（2回目以降 or 既存プロジェクト改修）は差分修正モード
    _SOURCE_EXTENSIONS = {
        ".py", ".ts", ".tsx", ".js", ".jsx", ".css", ".scss",
        ".html", ".json", ".yaml", ".yml", ".toml", ".md",
        ".tf", ".hcl", ".go", ".rs", ".java",
    }
    existing_files = [
        f for f in resolved_dir.rglob("*")
        if f.is_file()
        and f.suffix in _SOURCE_EXTENSIONS
        and "__pycache__" not in str(f)
        and "node_modules" not in str(f)
        and ".next" not in str(f)
    ]

    prompt = (
        f"以下の設計方針に基づいてコードを実装してください。\n\n"
        f"## 出力ディレクトリ\n{output_dir}\n\n"
        f"すべてのファイルは上記ディレクトリ内に create_file ツールで作成してください。\n\n"
        f"## 設計方針\n{plan}"
    )

    if existing_files:
        prompt += (
            "\n\n## ⚠️ 重要: 差分修正モード\n"
            "出力ディレクトリに既存のコードがあります。\n"
            "**既存のコードをベースに、Evaluator から指摘された問題点のみを修正してください。**\n"
            "全面的な書き直しは禁止です。既存のファイル構造・クラス設計・テストを維持し、\n"
            "問題のある部分だけを edit_file または create_file（上書き）で修正してください。\n\n"
            "### 既存ファイル一覧\n"
        )
        for f in sorted(existing_files):
            rel = f.relative_to(resolved_dir)
            prompt += f"- {rel}\n"

        # Evaluator フィードバックを明示的に含める
        feedback = tool_context.state.get("evaluator_feedback", "")
        if feedback:
            prompt += f"\n### Evaluator からの指摘事項\n{feedback}\n"

    logger.info("Generator: コード生成開始（出力先: %s）", output_dir)
    result, fallback_text = await _execute_antigravity_turn(
        stage="generator",
        prompt=prompt,
        tool_context=tool_context,
        system_instructions=GENERATOR_SYSTEM_PROMPT,
        response_schema=ArtifactOutput,
        allow_commands=True,  # ruff check / pytest を自律実行して品質を自己検証
        allow_writes=True,
        workspace_dir=output_dir,
    )

    if result is None:
        tool_context.state["artifact"] = fallback_text
        return fallback_text

    result_json = json.dumps(result, ensure_ascii=False)
    tool_context.state["artifact"] = result_json
    logger.info("Generator: コード生成完了")
    return result_json


async def run_evaluator_agent(
    plan: str,
    artifact: str,
    tool_context: ToolContext | StateContext,
) -> str:
    """Antigravity Agent を使ってコードをレビュー・スコアリングする。

    pytest と ruff を実行して品質を検証し、
    テスト合格率・コード品質・設計品質・テストカバレッジ等を評価する。
    REVISE/APPROVED の判定を行い、スコア履歴を管理し改善停滞を検出する。

    Args:
        plan: Planner が策定した設計方針（JSON 文字列）
        artifact: Generator が生成したコードの情報（JSON 文字列）
    """
    settings = get_settings()
    score_history_raw = tool_context.state.get("score_history", "[]")
    score_history: list[int] = json.loads(score_history_raw)
    iteration = len(score_history) + 1
    max_iterations = settings.max_loop_iterations

    # 動的 system_instructions 生成
    system_prompt = build_evaluator_system_prompt(
        iteration=iteration,
        max_iterations=max_iterations,
        score_history=score_history,
    )

    resolved_dir = _resolve_output_dir(tool_context)
    output_dir = str(resolved_dir)

    prompt = (
        f"## 設計方針\n{plan}\n\n"
        f"## 生成されたコード情報\n{artifact}\n\n"
        f"## 出力ディレクトリ\n{output_dir}\n\n"
        f"上記ディレクトリに対して、以下の検証をすべて実行してください:\n\n"
        f"1. `ls -R {output_dir}` でファイル一覧を確認し、設計方針の全モジュールが揃っているか検証\n"
        f"2. Python ファイルがあれば `python -c \"import ...\"` で import エラーがないか確認\n"
        f"3. Dockerfile / docker-compose.yml / podman-compose.yml があれば "
        f"ビルド・起動テストを実行\n"
        f"4. requirements.txt があれば `pip install -r requirements.txt` で "
        f"依存関係を確認\n"
        f"5. `python -m pytest` でテストを実行\n"
        f"6. `ruff check .` でコード品質を確認\n"
        f"7. コードを読み、設計品質をレビュー\n\n"
        f"すべての検証結果に基づいてスコアリングし、verdict を判定してください。\n"
        f"**動かないコードは 0 点です。**"
    )

    logger.info("Evaluator: レビュー開始（反復 %d/%d）", iteration, max_iterations)
    result, fallback_text = await _execute_antigravity_turn(
        stage="evaluator",
        prompt=prompt,
        tool_context=tool_context,
        system_instructions=system_prompt,
        response_schema=EvaluationOutput,
        allow_commands=True,
        allow_writes=False,  # Evaluator は評価のみ。コード修正は Generator の責務。
        workspace_dir=output_dir,
    )

    if result is None:
        tool_context.state["evaluator_feedback"] = fallback_text
        return fallback_text

    # スコア履歴に追加
    score = result.get("score", 0) if isinstance(result, dict) else 0
    score_history.append(score)
    tool_context.state["score_history"] = json.dumps(score_history)

    # Critical/High 課題チェック（スコアに関わらずブロッカーがあれば REVISE）
    has_blockers = False
    if isinstance(result, dict):
        issues = result.get("issues", [])
        has_blockers = any(
            isinstance(i, dict) and i.get("severity") in ("CRITICAL", "HIGH")
            for i in issues
        )

    # 強制終了判定: 最大反復到達 or 改善停滞
    verdict = result.get("verdict", "APPROVED") if isinstance(result, dict) else "APPROVED"
    prev_score = score_history[-2] if len(score_history) >= 2 else None
    is_regression = prev_score is not None and score < prev_score

    if iteration >= max_iterations:
        logger.info("Evaluator: 最大反復到達（%d回）、強制 APPROVED", max_iterations)
        if isinstance(result, dict):
            result["verdict"] = "APPROVED"
            result["reasoning"] += f" [最大反復回数 {max_iterations} に到達]"
    elif has_blockers:
        # ブロッカーがある場合は verdict に関わらず常に REVISE
        if isinstance(result, dict) and result.get("verdict") != "REVISE":
            logger.info("Evaluator: CRITICAL/HIGH 課題が残存、REVISE に変更")
            result["verdict"] = "REVISE"
            result["reasoning"] += " [CRITICAL/HIGH 課題が残存するため REVISE に変更]"
    elif is_regression and isinstance(result, dict) and result.get("verdict") == "APPROVED":
        # スコアが前回より下がったのに APPROVED → REVISE に上書き
        logger.info(
            "Evaluator: リグレッション検出（%d→%d）、REVISE に変更",
            prev_score,
            score,
        )
        result["verdict"] = "REVISE"
        result["reasoning"] += (
            f" [リグレッション: {prev_score}→{score} のため REVISE に変更]"
        )
    elif (
        isinstance(result, dict)
        and score < settings.approval_threshold
        and result.get("verdict") == "APPROVED"
    ):
        # スコアが閾値未満なのに APPROVED → REVISE に上書き
        logger.info(
            "Evaluator: score=%d < threshold=%d、REVISE に変更",
            score,
            settings.approval_threshold,
        )
        result["verdict"] = "REVISE"
        result["reasoning"] += (
            f" [score={score} < 閾値{settings.approval_threshold} のため REVISE に変更]"
        )
    elif len(score_history) >= 2 and not is_regression:
        improvement = score_history[-1] - score_history[-2]
        if improvement < settings.min_improvement and verdict == "REVISE":
            logger.info(
                "Evaluator: 改善停滞（改善幅 %d < 閾値 %d）、APPROVED に変更",
                improvement,
                settings.min_improvement,
            )
            if isinstance(result, dict):
                result["verdict"] = "APPROVED"
                result["reasoning"] += f" [改善停滞: 前回比 +{improvement}点]"

    result_json = json.dumps(result, ensure_ascii=False)
    tool_context.state["evaluator_feedback"] = result_json
    final_verdict = result.get("verdict", "?") if isinstance(result, dict) else "?"

    # ===== 定量メトリクスのコンパクトサマリー =====
    _log_evaluation_metrics(result, iteration, max_iterations, score_history, final_verdict)

    score = result.get("score", 0) if isinstance(result, dict) else 0
    reasoning = result.get("reasoning", "") if isinstance(result, dict) else ""
    return f"{final_verdict}: score={score}. {reasoning}"


def _log_evaluation_metrics(
    result: dict[str, Any] | None,
    iteration: int,
    max_iterations: int,
    score_history: list[int],
    final_verdict: str,
) -> None:
    """PGE 反復ごとの定量メトリクスを1行でログ出力する。"""
    if not isinstance(result, dict):
        logger.info(
            "PGE [%d/%d] score=? → %s (structured output 失敗)",
            iteration,
            max_iterations,
            final_verdict,
        )
        return

    score = result.get("score", 0)
    test_result = result.get("test_result", "N/A")
    lint_result = result.get("lint_result", "N/A")

    issues = result.get("issues", [])
    severity_counts: dict[str, int] = {}
    for issue in issues:
        if isinstance(issue, dict):
            sev = issue.get("severity", "UNKNOWN")
            severity_counts[sev] = severity_counts.get(sev, 0) + 1

    severity_str = " ".join(f"{k}:{v}" for k, v in sorted(severity_counts.items()))
    if not severity_str:
        severity_str = "issues=0"

    logger.info(
        "PGE [%d/%d] score=%d tests=%s ruff=%s %s → %s",
        iteration,
        max_iterations,
        score,
        test_result,
        lint_result,
        severity_str,
        final_verdict,
    )

    if final_verdict == "APPROVED":
        if len(score_history) >= 2:
            progression = "→".join(str(s) for s in score_history)
            improvement = score_history[-1] - score_history[0]
            sign = "+" if improvement >= 0 else ""
            logger.info(
                "━━━ PGE Summary: %d iterations, %s (%s%d), APPROVED ━━━",
                len(score_history),
                progression,
                sign,
                improvement,
            )
        else:
            logger.info(
                "━━━ PGE Summary: 1 iteration, score=%d, APPROVED ━━━",
                score,
            )
