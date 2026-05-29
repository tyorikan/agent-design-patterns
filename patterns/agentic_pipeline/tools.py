"""Antigravity Agent ラッパーツール。

ADK の LlmAgent から呼び出される tool 関数として、
各 Antigravity Agent をラップする。

認証: Antigravity local harness は Gemini API Key が必須。
      環境変数 GEMINI_API_KEY から取得する。
"""

import json
import logging
import os
from pathlib import Path

from google.adk.tools import ToolContext
from google.antigravity import Agent, CapabilitiesConfig, LocalAgentConfig
from google.antigravity.hooks import policy
from google.antigravity.types import GeminiConfig

from shared.config import get_settings

from .prompts import (
    GENERATOR_SYSTEM_PROMPT,
    PLANNER_SYSTEM_PROMPT,
    build_evaluator_system_prompt,
)
from .schemas import ArtifactOutput, EvaluationOutput, PlanOutput

logger = logging.getLogger(__name__)

_settings = get_settings()

# デフォルト出力ディレクトリ（生成コードの書き出し先）
DEFAULT_OUTPUT_DIR = Path(__file__).parent / "output"
DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 後方互換: テストなどで直接参照しているコード用
OUTPUT_DIR = DEFAULT_OUTPUT_DIR


def _resolve_output_dir(tool_context: ToolContext) -> Path:
    """state['output_dir'] から出力ディレクトリを解決する。

    adk run --state '{"output_dir": "/path/to/project"}' で
    任意のディレクトリを対象にできる。未指定ならデフォルト。
    """
    output_dir_str = tool_context.state.get("output_dir", "")
    if output_dir_str:
        p = Path(output_dir_str).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p
    return DEFAULT_OUTPUT_DIR


def _build_config(
    system_instructions: str,
    response_schema: type | None = None,
    allow_commands: bool = False,
    allow_writes: bool = True,
    workspace_dir: str | None = None,
) -> LocalAgentConfig:
    """Antigravity Agent の共通設定を構築する。

    GEMINI_API_KEY 環境変数から API キーを取得し GeminiConfig に設定。

    Args:
        system_instructions: エージェントのシステムプロンプト
        response_schema: 構造化出力のスキーマ（Pydantic モデル）
        allow_commands: True の場合、pytest/ruff の実行を許可する
        allow_writes: True の場合、create_file/edit_file を有効化する
        workspace_dir: ファイル操作を制限するワークスペースディレクトリ
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    gemini_config = GeminiConfig(api_key=api_key) if api_key else GeminiConfig()

    # ポリシー構築: コマンド実行の許可/拒否を制御
    policies = []
    if allow_commands:
        # テスト・lint・ビルド・起動検証のコマンド実行を許可
        # ファイル変更系（--fix, install -g）は禁止: 修正は Generator の責務
        _BLOCKED_SUBCOMMANDS = ("--fix", "install -g", "rm ", "sudo ")
        _ALLOWED_PREFIXES = (
            # テスト・lint
            "pytest", "python -m pytest", "ruff check",
            # Python
            "python ", "pip install", "pip check",
            # Docker / Podman
            "docker build", "docker compose", "docker run",
            "podman build", "podman-compose", "podman run",
            # Node.js
            "npm run", "npm test", "npm start", "npx ",
            "node ", "yarn ", "pnpm ",
            # Go
            "go build", "go test", "go vet", "go run",
            # Make / Shell
            "make", "sh ", "bash ", "cat ", "head ", "tail ",
            "ls ", "find ", "wc ", "grep ",
            # Terraform / IaC
            "terraform validate", "terraform plan", "terraform fmt",
            # Misc
            "curl ", "java ", "javac ", "mvn ", "gradle ",
        )
        policies.append(
            policy.allow(
                "run_command",
                when=lambda args: (
                    args.get("CommandLine", "").startswith(_ALLOWED_PREFIXES)
                    and not any(
                        sub in args.get("CommandLine", "")
                        for sub in _BLOCKED_SUBCOMMANDS
                    )
                ),
            )
        )
    # allow_commands=False の場合はデフォルトの confirm_run_command() が適用される

    # LocalAgentConfig の kwargs を動的に構築
    # policies/workspaces が空の場合は渡さない（None は ValidationError になる）
    config_kwargs: dict = {
        "system_instructions": system_instructions,
        "response_schema": response_schema,
        "gemini_config": gemini_config,
    }
    # allow_writes=True の場合のみ書き込みツール（create_file, edit_file）を有効化
    if allow_writes:
        config_kwargs["capabilities"] = CapabilitiesConfig()
    if policies:
        config_kwargs["policies"] = policies
    if workspace_dir:
        config_kwargs["workspaces"] = [workspace_dir]

    return LocalAgentConfig(**config_kwargs)


# ── Planner 用 FunctionTool ──────────────────────────────
# Claude が既存プロジェクト改修時に自律的にファイルを探索するための軽量ツール。
# Generator/Evaluator の Antigravity Agent と違い、コマンド実行やファイル書き込みは不要。

# agent.py と共通の無視パターン
_PLANNER_IGNORE_DIRS = {
    "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache",
    ".venv", "venv", ".tox", ".eggs",
    "node_modules", ".next", ".nuxt", ".svelte-kit", ".turbo",
    ".parcel-cache", ".cache",
    "dist", "build", "out", "coverage",
    ".git", ".adk",
}


def read_file(file_path: str) -> str:
    """指定されたファイルの内容を読み取る。

    Args:
        file_path: 読み取るファイルのパス。

    Returns:
        ファイルの内容（テキスト）。
    """
    p = Path(file_path)
    if not p.exists():
        return f"Error: {file_path} が見つかりません"
    if not p.is_file():
        return f"Error: {file_path} はファイルではありません"
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        # 巨大ファイルはトークン節約のため先頭のみ
        max_chars = 30_000
        if len(content) > max_chars:
            return content[:max_chars] + f"\n\n... (truncated, {len(content)} chars total)"
        return content
    except Exception as e:
        return f"Error: {e}"


def list_directory(directory_path: str) -> str:
    """指定されたディレクトリの内容を一覧表示する。

    Args:
        directory_path: 一覧表示するディレクトリのパス。

    Returns:
        ディレクトリ内のファイルとサブディレクトリの一覧。
    """
    p = Path(directory_path)
    if not p.exists():
        return f"Error: {directory_path} が見つかりません"
    if not p.is_dir():
        return f"Error: {directory_path} はディレクトリではありません"
    try:
        entries = sorted(p.iterdir())
    except PermissionError:
        return f"Error: {directory_path} の読み取り権限がありません"
    lines = []
    for entry in entries:
        if entry.name.startswith(".") or entry.name in _PLANNER_IGNORE_DIRS:
            continue
        prefix = "📁" if entry.is_dir() else "📄"
        lines.append(f"{prefix} {entry.name}")
    return "\n".join(lines) if lines else "(empty directory)"


def _strip_markdown_fences(text: str) -> str:
    """マークダウンのコードフェンスを除去する。

    Claude は JSON 出力を ```json ... ``` で囲む傾向がある。
    ADK の output_schema (model_validate_json) はこれをパースできないため、
    手動で除去する。
    """
    import re

    stripped = text.strip()
    # ```json ... ``` or ``` ... ``` パターンを除去
    match = re.match(r"^```(?:json)?\s*\n(.*?)\n```\s*$", stripped, re.DOTALL)
    if match:
        return match.group(1).strip()
    return stripped


async def run_planner_agent(
    user_request: str,
    tool_context: ToolContext,
) -> str:
    """LlmAgent (Claude Opus 4.8 via Vertex AI) で設計方針を策定する。

    新規プロジェクトの場合は純粋な推論のみ。
    既存プロジェクト改修時は read_file / list_directory ツールで
    Claude が自律的に関連ファイルを探索して設計方針を策定する。

    Args:
        user_request: ユーザーの要件（例: "FastAPI で TODO アプリの REST API を実装"）
    """
    from google.adk.agents import LlmAgent
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    feedback = tool_context.state.get("evaluator_feedback", "")
    score_history_raw = tool_context.state.get("score_history", "[]")
    score_history: list[int] = json.loads(score_history_raw)
    prev_score = score_history[-1] if score_history else 0

    prompt = f"要件: {user_request}"

    # 既存プロジェクトの情報
    resolved_dir = _resolve_output_dir(tool_context)
    has_existing_files = resolved_dir.exists() and any(
        f for f in resolved_dir.iterdir()
        if not f.name.startswith(".") and f.name not in _PLANNER_IGNORE_DIRS
    )

    if has_existing_files and not feedback:
        # 初回かつ既存ファイルあり → Claude にツールで探索させる
        prompt += (
            f"\n\n## 既存プロジェクト情報\n"
            f"対象ディレクトリ: {resolved_dir}\n"
            f"**重要: これは既存プロジェクトへの機能追加・改修です。**\n"
            f"まず `list_directory` と `read_file` ツールで既存コードの構造と内容を確認し、\n"
            f"既存のコード構造・設計パターン・命名規則を尊重した設計方針を策定してください。\n"
        )
        logger.info("Planner: 既存プロジェクト改修モード（Claude Function Calling）")

    if feedback:
        if prev_score >= 60:
            prompt += (
                f"\n\n## 前回の評価フィードバック（前回スコア: {prev_score}）\n"
                f"**重要: 既存の設計・アーキテクチャは維持し、以下の指摘点のみを修正する設計変更を行ってください。**\n"
                f"全面的な再設計は禁止です。前回の成果物をベースに、差分修正の方針を策定してください。\n\n"
                f"{feedback}"
            )
            logger.info("Planner: 差分修正モード（score=%d、既存設計維持）", prev_score)
        else:
            prompt += (
                f"\n\n## 前回の評価フィードバック（前回スコア: {prev_score}）\n"
                f"設計に根本的な問題があります。アーキテクチャを見直してください。\n\n"
                f"{feedback}"
            )
            logger.info("Planner: 再設計モード（score=%d、根本的見直し）", prev_score)
    elif not has_existing_files:
        logger.info("Planner: 初回設計モード（新規プロジェクト）")

    # 既存プロジェクトがある場合はツールを提供
    planner_tools: list = []
    if has_existing_files:
        planner_tools = [read_file, list_directory]

    # LlmAgent を構築（Claude は models/__init__.py で lazy registration 済み）
    # NOTE: output_schema は使わない。Claude は JSON を ```json ... ``` で囲む傾向があり、
    # ADK の model_validate_json() がパースに失敗するため、手動パースする。
    planner = LlmAgent(
        name="planner_claude",
        model="claude-opus-4-8",
        instruction=PLANNER_SYSTEM_PROMPT,
        tools=planner_tools,
        output_key="plan",
    )

    # 独立した InMemorySessionService で 1 ショット実行
    session_service = InMemorySessionService()
    runner = Runner(
        agent=planner,
        app_name="pge_planner",
        session_service=session_service,
    )
    session = await session_service.create_session(
        app_name="pge_planner", user_id="pge",
    )

    result = ""
    async for event in runner.run_async(
        user_id="pge",
        session_id=session.id,
        new_message=types.Content(
            role="user",
            parts=[types.Part(text=prompt)],
        ),
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    result += part.text

    if not result:
        logger.warning("Planner: Claude から応答なし。空文字列を返します。")

    # Claude のマークダウンフェンスを除去して JSON を抽出
    result = _strip_markdown_fences(result)

    # PlanOutput バリデーション（ログ用、失敗しても続行）
    try:
        PlanOutput.model_validate_json(result)
        logger.info("Planner: PlanOutput バリデーション成功")
    except Exception as e:
        logger.warning("Planner: PlanOutput バリデーション失敗（続行）: %s", e)

    tool_context.state["plan"] = result
    logger.info("Planner: 設計方針策定完了")
    return result


async def run_generator_agent(
    plan: str,
    tool_context: ToolContext,
) -> str:
    """Antigravity Agent を使ってコードを実装する。

    設計方針に基づいて Python コードを生成し、
    create_file ツールで出力ディレクトリにファイルを書き出す。

    Args:
        plan: Planner が策定した設計方針（JSON 文字列）
    """
    resolved_dir = _resolve_output_dir(tool_context)
    output_dir = str(resolved_dir)

    config = _build_config(
        system_instructions=GENERATOR_SYSTEM_PROMPT,
        response_schema=ArtifactOutput,
        allow_commands=True,  # ruff check / pytest を自律実行して品質を自己検証
        workspace_dir=output_dir,
    )

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
    async with Agent(config) as agent:
        response = await agent.chat(prompt)
        result = await response.structured_output()

    if result is None:
        text = await response.text()
        tool_context.state["artifact"] = text
        return text

    result_json = json.dumps(result, ensure_ascii=False)
    tool_context.state["artifact"] = result_json
    logger.info("Generator: コード生成完了")
    return result_json


async def run_evaluator_agent(
    plan: str,
    artifact: str,
    tool_context: ToolContext,
) -> str:
    """Antigravity Agent を使ってコードをレビュー・スコアリングする。

    pytest と ruff を実行して品質を検証し、
    テスト合格率・コード品質・設計品質・テストカバレッジの4軸で評価する。
    REVISE/APPROVED の判定を行い、スコア履歴を管理し改善停滞を検出する。

    Args:
        plan: Planner が策定した設計方針（JSON 文字列）
        artifact: Generator が生成したコードの情報（JSON 文字列）
    """
    # スコア履歴の取得
    score_history_raw = tool_context.state.get("score_history", "[]")
    score_history: list[int] = json.loads(score_history_raw)
    iteration = len(score_history) + 1
    max_iterations = _settings.max_loop_iterations

    # 動的 system_instructions 生成
    system_prompt = build_evaluator_system_prompt(
        iteration=iteration,
        max_iterations=max_iterations,
        score_history=score_history,
    )

    resolved_dir = _resolve_output_dir(tool_context)
    output_dir = str(resolved_dir)

    config = _build_config(
        system_instructions=system_prompt,
        response_schema=EvaluationOutput,
        allow_commands=True,
        allow_writes=False,  # Evaluator は評価のみ。コード修正は Generator の責務。
        workspace_dir=output_dir,
    )

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
    async with Agent(config) as agent:
        response = await agent.chat(prompt)
        result = await response.structured_output()

    if result is None:
        text = await response.text()
        tool_context.state["evaluator_feedback"] = text
        return text

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
        and score < _settings.approval_threshold
        and result.get("verdict") == "APPROVED"
    ):
        # スコアが閾値未満なのに APPROVED → REVISE に上書き
        logger.info(
            "Evaluator: score=%d < threshold=%d、REVISE に変更",
            score,
            _settings.approval_threshold,
        )
        result["verdict"] = "REVISE"
        result["reasoning"] += (
            f" [score={score} < 閾値{_settings.approval_threshold} のため REVISE に変更]"
        )
    elif len(score_history) >= 2 and not is_regression:
        improvement = score_history[-1] - score_history[-2]
        if improvement < _settings.min_improvement and verdict == "REVISE":
            logger.info(
                "Evaluator: 改善停滞（改善幅 %d < 閾値 %d）、APPROVED に変更",
                improvement,
                _settings.min_improvement,
            )
            if isinstance(result, dict):
                result["verdict"] = "APPROVED"
                result["reasoning"] += f" [改善停滞: 前回比 +{improvement}点]"

    result_json = json.dumps(result, ensure_ascii=False)
    tool_context.state["evaluator_feedback"] = result_json
    final_verdict = result.get("verdict", "?") if isinstance(result, dict) else "?"

    # ===== 定量メトリクスのコンパクトサマリー =====
    _log_evaluation_metrics(result, iteration, max_iterations, score_history, final_verdict)

    # ADK Workflow の条件付きエッジは LlmAgent の出力テキストのキーワードマッチで分岐する。
    # ツール結果を verdict キーワード先頭の文字列で返し、LlmAgent がそのまま出力に使うよう促す。
    score = result.get("score", 0) if isinstance(result, dict) else 0
    reasoning = result.get("reasoning", "") if isinstance(result, dict) else ""
    return f"{final_verdict}: score={score}. {reasoning}"


def _log_evaluation_metrics(
    result: dict | None,
    iteration: int,
    max_iterations: int,
    score_history: list[int],
    final_verdict: str,
) -> None:
    """PGE 反復ごとの定量メトリクスを1行でログ出力する。

    出力例:
        PGE [1/5] score=68 tests=7/14 ruff=7errors CRITICAL:1 HIGH:1 MEDIUM:1 → REVISE
        PGE [2/5] score=85 tests=14/14 ruff=0errors MEDIUM:2 → APPROVED
        ━━━ PGE Summary: 2 iterations, 68→85 (+17), APPROVED ━━━
    """
    if not isinstance(result, dict):
        logger.info("PGE [%d/%d] score=? → %s (structured output 失敗)", iteration, max_iterations, final_verdict)
        return

    score = result.get("score", 0)
    test_result = result.get("test_result", "N/A")
    lint_result = result.get("lint_result", "N/A")

    # 課題の深刻度別カウント
    issues = result.get("issues", [])
    severity_counts: dict[str, int] = {}
    for issue in issues:
        if isinstance(issue, dict):
            sev = issue.get("severity", "UNKNOWN")
            severity_counts[sev] = severity_counts.get(sev, 0) + 1

    severity_str = " ".join(f"{k}:{v}" for k, v in sorted(severity_counts.items()))
    if not severity_str:
        severity_str = "issues=0"

    # 1反復1行のメトリクスログ
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

    # 最終判定時のみサマリーを出力
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
