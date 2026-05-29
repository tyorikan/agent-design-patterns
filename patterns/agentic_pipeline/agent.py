"""Agentic Pipeline パターン — ADK BaseAgent + Antigravity Agent。

ADK Workflow の条件付きエッジは ADK v2 に実装されているが、
PGE パイプラインの複雑なループ制御（スコア履歴管理、リグレッションガード等）
には不十分だったため、BaseAgent を採用している。

各ノードの内部処理は Antigravity Agent（自律エージェント）に委任する。

認証: Vertex AI ADC のみ使用。

アーキテクチャ:
    PGEOrchestrator (BaseAgent)
        ├── run_planner_agent() → Antigravity Agent
        ├── run_generator_agent() → Antigravity Agent
        └── run_evaluator_agent() → Antigravity Agent
        └── ループ制御: REVISE → Planner に戻る

REVISE 条件:
    - score < 80 かつ改善可能 → REVISE（Planner に戻る）
    - score >= 80 → APPROVED
    - 最大反復到達 → 強制 APPROVED
    - 改善停滞（前回比 < 5点） → APPROVED
"""

import json
import logging
from pathlib import Path

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.genai import types

from .tools import (
    run_evaluator_agent,
    run_generator_agent,
    run_planner_agent,
)
from .tools import DEFAULT_OUTPUT_DIR

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 5


class _StateProxy:
    """ToolContext の最小限の代替。state 辞書へのアクセスを提供する。"""

    def __init__(self, state: dict):
        self.state = state


def _snapshot_dir(directory: Path) -> dict[str, tuple[float, int]]:
    """ディレクトリ内の全ファイルのスナップショットを取得する。

    .gitignore 対象のファイルは除外する。

    Returns:
        {相対パス: (mtime, size)} の辞書
    """
    snapshot = {}
    if not directory.exists():
        return snapshot
    for f in directory.rglob("*"):
        if f.is_file() and not _should_ignore(f, directory):
            rel = str(f.relative_to(directory))
            try:
                stat = f.stat()
                snapshot[rel] = (stat.st_mtime, stat.st_size)
            except OSError:
                pass
    return snapshot


# .gitignore に含まれるべきパターン（ディレクトリ名 or 拡張子）
_IGNORE_DIRS = {
    # Python
    "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache",
    ".venv", "venv", ".tox", ".eggs",
    # Node.js / Frontend
    "node_modules", ".next", ".nuxt", ".svelte-kit", ".turbo",
    ".parcel-cache", ".cache",
    # Build output
    "dist", "build", "out", "coverage",
    # Misc
    ".git", ".adk",
}
_IGNORE_EXTENSIONS = {
    ".pyc", ".pyo", ".so", ".egg", ".whl",
    ".map", ".min.js", ".min.css",  # フロントエンドビルド成果物
}
_IGNORE_FILES = {
    ".DS_Store", "Thumbs.db", ".coverage",
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",  # ロックファイル
}


def _should_ignore(filepath: Path, base: Path) -> bool:
    """gitignore 対象のファイルかどうかを判定する。"""
    if filepath.name.startswith(".") and filepath.name not in (".env.example",):
        return True
    if filepath.suffix in _IGNORE_EXTENSIONS:
        return True
    if filepath.name in _IGNORE_FILES:
        return True
    # パスの途中に無視ディレクトリが含まれるか
    try:
        rel_parts = filepath.relative_to(base).parts
    except ValueError:
        return False
    return bool(_IGNORE_DIRS & set(rel_parts))


def _count_lines(filepath: Path) -> int:
    """ファイルの行数をカウントする。バイナリファイルは 0 を返す。"""
    try:
        return len(filepath.read_text(encoding="utf-8").splitlines())
    except (UnicodeDecodeError, OSError):
        return 0


def _extract_file_description(filepath: Path) -> str:
    """ファイル内容から1行の説明を抽出する。

    Python: モジュール docstring の1行目 + 主要な class/def 名
    その他: 先頭コメントの1行目
    """
    try:
        content = filepath.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ""

    lines = content.splitlines()
    if not lines:
        return ""

    if filepath.suffix == ".py":
        return _extract_python_description(lines)

    # 非 Python: 先頭コメント行を探す
    for line in lines[:10]:
        stripped = line.strip()
        if stripped.startswith(("#", "//", "/*", "*")):
            comment = stripped.lstrip("#//* ").strip()
            if comment and len(comment) > 5:
                return comment
    return ""


def _extract_python_description(lines: list[str]) -> str:
    """Python ファイルから説明を抽出する。"""
    parts: list[str] = []

    # 1. モジュール docstring（先頭の三重引用符）
    docstring = _extract_module_docstring(lines)
    if docstring:
        parts.append(docstring)

    # 2. class / def 名を収集
    symbols: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("class ") and "(" in stripped:
            name = stripped.split("(")[0].replace("class ", "").strip()
            if not name.startswith("_"):
                symbols.append(name)
        elif stripped.startswith("def ") and "(" in stripped:
            name = stripped.split("(")[0].replace("def ", "").strip()
            if not name.startswith("_"):
                symbols.append(name)

    if symbols:
        sym_str = ", ".join(symbols[:5])
        if len(symbols) > 5:
            sym_str += f" 他{len(symbols) - 5}件"
        if parts:
            parts.append(f"({sym_str})")
        else:
            parts.append(sym_str)

    return " ".join(parts)


def _extract_module_docstring(lines: list[str]) -> str:
    """モジュール docstring の1行目を抽出する。"""
    in_docstring = False
    for line in lines[:30]:
        stripped = line.strip()
        if not in_docstring:
            # コメント行やインポート行はスキップ
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith(('"""', "'''")):
                marker = stripped[:3]
                # 1行 docstring: """text"""
                if stripped.count(marker) >= 2:
                    return stripped.strip(marker).strip(". ").strip()
                # 複数行 docstring の開始
                in_docstring = True
                content = stripped[3:].strip()
                if content:
                    return content.rstrip(". ").strip()
                continue
            # docstring でなければ終了
            break
        else:
            # docstring 内: 最初の非空行を返す
            if stripped:
                return stripped.rstrip(marker).rstrip(". ").strip()
    return ""


def _build_file_summary(
    directory: Path,
    before: dict[str, tuple[float, int]],
    user_request: str = "",
) -> str:
    """ファイル変更サマリー + コミットメッセージ風の要約を構築する。"""
    after = _snapshot_dir(directory)

    created = sorted(set(after) - set(before))
    deleted = sorted(set(before) - set(after))
    modified = sorted(
        p for p in set(after) & set(before)
        if after[p] != before[p]
    )

    if not created and not deleted and not modified:
        return "📁 ファイル変更なし"

    sections: list[str] = []

    # --- 1. コミットメッセージ風の要約 ---
    sections.append("### 📋 変更サマリー\n")

    if user_request:
        # ユーザー要件の先頭 80 文字をタイトルに
        title = user_request.strip().split("\n")[0][:80]
        sections.append(f"**feat:** {title}\n")

    # 各ファイルの説明を抽出
    if created:
        sections.append("**新規:**\n")
        for p in created:
            desc = _extract_file_description(directory / p)
            desc_str = f" — {desc}" if desc else ""
            sections.append(f"- `{p}`{desc_str}")
    if modified:
        sections.append("\n**変更:**\n")
        for p in modified:
            desc = _extract_file_description(directory / p)
            desc_str = f" — {desc}" if desc else ""
            sections.append(f"- `{p}`{desc_str}")
    if deleted:
        sections.append("\n**削除:**\n")
        for p in deleted:
            sections.append(f"- `{p}`")

    # --- 2. tree 形式のファイル一覧 ---
    sections.append(f"\n### 📁 出力ディレクトリ: `{directory}`\n")

    total_files = 0
    total_lines = 0

    tree_lines: list[str] = []
    all_entries: list[tuple[str, str]] = []
    for p in created:
        all_entries.append((p, "✨ NEW"))
    for p in modified:
        all_entries.append((p, "📝 MOD"))
    for p in deleted:
        all_entries.append((p, "🗑️  DEL"))
    all_entries.sort(key=lambda x: x[0])

    for i, (path, status) in enumerate(all_entries):
        is_last = i == len(all_entries) - 1
        prefix = "└── " if is_last else "├── "
        if status == "🗑️  DEL":
            tree_lines.append(f"{prefix}{status} {path}")
        else:
            filepath = directory / path
            lc = _count_lines(filepath)
            size = filepath.stat().st_size
            tree_lines.append(
                f"{prefix}{status} {path}  ({lc} lines, {size:,} bytes)"
            )
            total_lines += lc
        total_files += 1

    sections.append("```")
    sections.extend(tree_lines)
    sections.append("```")

    sections.append(
        f"\n> **合計:** {len(created)} 新規, {len(modified)} 変更, "
        f"{len(deleted)} 削除 ({total_files} files, {total_lines:,} lines)"
    )

    return "\n".join(sections)


def _summarize_plan(plan_json: str) -> str:
    """Planner 結果を Markdown 形式で整形して出力する。

    adk web (ngx-markdown) と adk run (ターミナル) の両方で読みやすくするため、
    Markdown 記法で出力する。
    """
    try:
        data = json.loads(plan_json)
    except (json.JSONDecodeError, TypeError):
        return f"Planner 完了\n\n{plan_json}"

    if not isinstance(data, dict):
        return f"Planner 完了\n\n{plan_json}"

    sections: list[str] = ["### 📐 Planner 完了"]

    arch = data.get("architecture", "")
    if arch:
        sections.append(f"\n**📋 設計方針:**\n\n{arch.strip()}")

    modules = data.get("modules", [])
    if modules:
        sections.append(f"\n**📦 モジュール一覧 ({len(modules)} files):**\n")
        for m in modules:
            sections.append(f"- `{m}`")

    test_strategy = data.get("test_strategy", "")
    if test_strategy:
        sections.append(f"\n**🧪 テスト戦略:**\n\n{test_strategy.strip()}")

    dir_structure = data.get("directory_structure", "")
    if dir_structure:
        sections.append(f"\n**📁 ディレクトリ構成:**\n\n```\n{dir_structure.strip()}\n```")

    return "\n".join(sections)


def _summarize_artifact(artifact_json: str) -> str:
    """Generator 結果を Markdown 形式で整形して出力する。"""
    try:
        data = json.loads(artifact_json)
    except (json.JSONDecodeError, TypeError):
        return f"Generator 完了\n\n{artifact_json}"

    if not isinstance(data, dict):
        return f"Generator 完了\n\n{artifact_json}"

    sections: list[str] = []

    files = data.get("files_created", [])
    sections.append(f"### 🔨 Generator 完了 — {len(files)} files 作成")
    if files:
        sections.append("\n**📄 作成ファイル:**\n")
        for f in files:
            sections.append(f"- `{f}`")

    summary = data.get("summary", "")
    if summary:
        sections.append(f"\n**📝 実装サマリー:**\n\n{summary.strip()}")

    return "\n".join(sections)


class PGEOrchestrator(BaseAgent):
    """Planner-Generator-Evaluator 3者間自律ループオーケストレーター。

    ADK Workflow の条件付きエッジは ADK v2 に実装されているが、
    PGE の複雑なループ制御には不十分なため BaseAgent を採用。

    フロー:
        1. Planner: ユーザー要件から設計方針を策定
        2. Generator: 設計方針に基づきコードを実装
        3. Evaluator: コード品質を評価し、verdict を返す
        4. verdict == REVISE → 1 に戻る（最大 MAX_ITERATIONS 回）
        5. verdict == APPROVED → 終了
    """

    async def _run_async_impl(self, ctx: InvocationContext):
        """PGE ループを制御する。"""
        state = ctx.session.state
        tool_context = _StateProxy(state)

        # ユーザーメッセージを session events から取得
        user_request = ""
        for event in reversed(ctx.session.events):
            if (
                event.content
                and event.content.role == "user"
                and event.content.parts
            ):
                texts = [p.text for p in event.content.parts if p.text]
                if texts:
                    user_request = "\n".join(texts)
                    break
        state["user_request"] = user_request
        output_dir_str = state.get("output_dir", "")
        output_dir = Path(output_dir_str).resolve() if output_dir_str else DEFAULT_OUTPUT_DIR
        logger.info(
            "PGE Orchestrator: user_request=%s, output_dir=%s",
            user_request[:100],
            output_dir,
        )

        # ループ前のファイルスナップショット
        before_snapshot = _snapshot_dir(output_dir)

        for iteration in range(1, MAX_ITERATIONS + 1):
            logger.info(
                "PGE Orchestrator: Iteration %d/%d", iteration, MAX_ITERATIONS
            )

            # --- Planner ---
            yield Event(
                author=self.name,
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part(
                            text=f"[Iteration {iteration}] Planner を起動します..."
                        )
                    ],
                ),
            )

            plan = await run_planner_agent(
                user_request=state.get("user_request", ""),
                tool_context=tool_context,
            )
            state["plan"] = plan

            # Planner 完了サマリー
            plan_summary = _summarize_plan(plan)
            yield Event(
                author=self.name,
                content=types.Content(
                    role="model",
                    parts=[types.Part(text=f"**[Iteration {iteration}]**\n\n{plan_summary}")],
                ),
            )

            # --- Generator ---
            yield Event(
                author=self.name,
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part(
                            text=f"[Iteration {iteration}] Generator を起動します..."
                        )
                    ],
                ),
            )

            artifact = await run_generator_agent(
                plan=plan,
                tool_context=tool_context,
            )
            state["artifact"] = artifact

            # Generator 完了サマリー
            gen_summary = _summarize_artifact(artifact)
            yield Event(
                author=self.name,
                content=types.Content(
                    role="model",
                    parts=[types.Part(text=f"**[Iteration {iteration}]**\n\n{gen_summary}")],
                ),
            )

            # --- Evaluator ---
            yield Event(
                author=self.name,
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part(
                            text=f"[Iteration {iteration}] Evaluator を起動します..."
                        )
                    ],
                ),
            )

            result_text = await run_evaluator_agent(
                plan=plan,
                artifact=artifact,
                tool_context=tool_context,
            )
            state["evaluator_feedback"] = result_text

            # --- Verdict 判定 ---
            if result_text.startswith("APPROVED"):
                logger.info("PGE Orchestrator: APPROVED at iteration %d", iteration)
                file_summary = _build_file_summary(
                    output_dir, before_snapshot, user_request
                )
                yield Event(
                    author=self.name,
                    content=types.Content(
                        role="model",
                        parts=[
                            types.Part(
                                text=(
                                    f"### [Iteration {iteration}] ✅ APPROVED\n\n"
                                    f"{result_text}\n\n"
                                    f"---\n\n{file_summary}"
                                )
                            )
                        ],
                    ),
                )
                return

            logger.info("PGE Orchestrator: REVISE at iteration %d", iteration)
            yield Event(
                author=self.name,
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part(
                            text=f"### [Iteration {iteration}] 🔄 REVISE\n\n{result_text}"
                        )
                    ],
                ),
            )

        # 最大反復到達
        logger.warning(
            "PGE Orchestrator: Max iterations (%d) reached", MAX_ITERATIONS
        )
        file_summary = _build_file_summary(
            output_dir, before_snapshot, user_request
        )
        yield Event(
            author=self.name,
            content=types.Content(
                role="model",
                parts=[
                    types.Part(
                        text=(
                            f"最大反復回数 ({MAX_ITERATIONS}) に到達しました。最終結果を返します。"
                            f"\n{file_summary}"
                        )
                    )
                ],
            ),
        )


root_agent = PGEOrchestrator(
    name="agentic_pipeline",
    description=(
        "汎用 PGE コード実装パイプライン。"
        "Antigravity Agent を頭脳とした Planner-Generator-Evaluator "
        "3者間自律レビューパイプライン。"
    ),
)
