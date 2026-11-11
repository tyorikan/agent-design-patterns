"""CLI-04: Grounded RAG & Production Deploy パターン実装。"""

from __future__ import annotations

import os
from typing import Any

from google.adk.agents import Agent
from google.adk.apps import App
from google.genai import types

from .retriever import KnowledgeRetriever, build_retriever_from_env

os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_ENTERPRISE", "True")

DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "gemini-3.8-flash")

_active_retriever: KnowledgeRetriever | None = None


def get_retriever() -> KnowledgeRetriever:
    """現在のアクティブな Retriever を取得する（テスト時に差し替え可能）。"""
    global _active_retriever
    if _active_retriever is None:
        _active_retriever = build_retriever_from_env()
    return _active_retriever


def set_retriever_for_testing(retriever: KnowledgeRetriever | None) -> None:
    """単体テスト・統合テスト用に任意の Retriever を注入する。"""
    global _active_retriever
    _active_retriever = retriever


def search_architecture_policies(query: str, top_k: int = 3) -> dict[str, Any]:
    """アーキテクチャ設計基準コーパスから関連規定を検索し、出典 ID 付きで返す。

    Args:
        query: 検索クエリ（例: 'マルチリージョン RPO RTO 基準', 'AI エージェント IAM 権限'）。
        top_k: 取得する最大件数（1〜5）。

    Returns:
        ヒットした規定リスト（`doc_id`, `title`, `snippet`, `score`）と件数。
    """
    bounded_k = max(1, min(5, top_k))
    results = get_retriever().search(query=query, top_k=bounded_k)
    return {
        "query": query,
        "match_count": len(results),
        "citations": [
            {
                "doc_id": r.doc_id,
                "title": r.title,
                "snippet": r.snippet,
                "score": r.score,
            }
            for r in results
        ],
    }


root_agent = Agent(
    name="architecture_policy_rag_agent",
    model=DEFAULT_MODEL,
    description="アーキテクチャ標準コーパスを検索し、出典 ID 付きで回答する Grounded RAG エージェント。",
    instruction="""あなたはアーキテクチャ標準案内エージェントです。以下のグラウンディング規約を厳守してください。

1. 質問を受けたら、必ず最初に `search_architecture_policies` ツールを呼び出して根拠規定を検索してください。
2. 回答するすべての技術要件・数値には、検索結果に含まれる出典 ID（例: `[DOC-ARCH-001]`）を必ず明記してください。
3. 検索結果が 0 件（`match_count == 0`）の場合や、検索された規定に記載されていない事項については、一般知識で推測・捏造せず「現在の標準規定コーパスには該当する記載がありません」と正直に回答してください。
""",
    tools=[search_architecture_policies],
    generate_content_config=types.GenerateContentConfig(
        temperature=0.0,
        thinking_config=types.ThinkingConfig(thinking_level="LOW"),
    ),
)

app = App(name="app", root_agent=root_agent)
