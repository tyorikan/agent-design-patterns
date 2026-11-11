"""`custom_response_quality` 用インプロセス LLM-as-a-Judge 評価モジュール。

`agents-cli eval grade` / `agents-cli eval run` のワーカープールから呼び出される。
退役済みモデルのハードコードを避け、`EVAL_JUDGE_MODEL`（既定: `gemini-3.8-flash`）と
構造化出力（Pydantic スキーマ）で再現性の高い 1〜5 点採点を行う。
"""

from __future__ import annotations

import os
import threading
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel

_local = threading.local()
JUDGE_MODEL = os.environ.get("EVAL_JUDGE_MODEL", "gemini-3.8-flash")


class _Verdict(BaseModel):
    """LLM-as-a-Judge の構造化採点結果。"""

    score: int  # 1 (不正確・無回答) 〜 5 (正確かつ明瞭)
    explanation: str


def _client() -> genai.Client:
    """スレッドごとに 1 つの GenAI クライアントを初期化する。"""
    client = getattr(_local, "client", None)
    if client is None:
        os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
        os.environ.setdefault("GOOGLE_GENAI_USE_ENTERPRISE", "True")
        client = _local.client = genai.Client()
    return client


def evaluate(instance: dict[str, Any]) -> dict[str, Any]:
    """1 件の評価インスタンスを 1〜5 点で採点する。"""
    reference = instance.get("reference")
    rubric = (
        "エージェントの最終回答を 1〜5 点（1=不正確または無回答、5=正確・具体的・明瞭）で採点してください。"
    )
    if reference:
        rubric += (
            " 期待される正解（Expected Answer）に含まれる主要な事実・数値と矛盾がある場合は減点してください。"
        )

    prompt = (
        f"あなたはエンタープライズ AI エージェントの品質評価者です。{rubric}\n\n"
        f"User Prompt:\n{instance.get('prompt', '')}\n\n"
        f"Final Response:\n{instance.get('response', '')}\n"
    )
    if reference:
        prompt += f"\nExpected Answer (ground truth):\n{reference}\n"
    prompt += f"\nAgent Trace:\n{instance.get('agent_data', '')}\n"

    response = _client().models.generate_content(
        model=JUDGE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.0,
            response_mime_type="application/json",
            response_schema=_Verdict,
            thinking_config=types.ThinkingConfig(thinking_level="LOW"),
        ),
    )
    verdict = response.parsed
    if not isinstance(verdict, _Verdict):
        return {"score": 0, "explanation": response.text or "構造化出力の解析に失敗しました"}
    return {
        "score": max(1, min(5, verdict.score)),
        "explanation": verdict.explanation,
    }
