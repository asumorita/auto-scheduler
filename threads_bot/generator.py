"""Claude に投稿文を書いてもらう。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import anthropic

from .config import Config

# 安全上の理由でモデルが断ったとき、サーバー側で別モデルが代わりに書く仕組み
FALLBACK_BETA = "server-side-fallback-2026-07-01"

WEEKDAYS = "月火水木金土日"


class GenerationError(Exception):
    pass


def build_system_prompt(cfg: Config) -> str:
    return f"""あなたは Threads アカウントの投稿を書く担当者です。

# アカウント
- テーマ: {cfg.theme}
- 読者: {cfg.audience}
- 文体: {cfg.tone}

# 書き方のルール
- 投稿の本文だけを出力してください。前置き・説明・タイトル・かぎかっこでのくくりは付けません。
- {cfg.max_chars}文字以内。スマホで読みやすいよう、適度に改行してください。
- ハッシュタグ（#）と URL は書きません。
- 絵文字は使わないか、使っても1〜2個までにしてください。
- 体験談・実績・数字・統計をでっちあげないでください。「私は〜で月◯万円」のような作り話は書きません。確かでないことは断定しません。
- 「絶対」「必ず儲かる」のような誇大な表現や、投資・医療の具体的な助言はしません。
- 最近の投稿と同じ話題・同じ書き出しを避け、毎回新しい切り口にしてください。"""


def build_user_prompt(
    *,
    fmt: str,
    recent_posts: Sequence[str],
    now: datetime,
    feedback: Sequence[str] = (),
) -> str:
    date = f"{now:%Y年%m月%d日}（{WEEKDAYS[now.weekday()]}）"
    recent = "\n---\n".join(recent_posts) if recent_posts else "（まだありません）"
    prompt = f"""今日は {date} です。
今回の投稿パターン: {fmt}

最近の投稿（これらと被らないようにしてください）:
<recent_posts>
{recent}
</recent_posts>

投稿を1つ書いてください。"""
    if feedback:
        reasons = "\n".join(f"- {r}" for r in feedback)
        prompt += f"\n\n前回書いてもらった案は、次の理由で使えませんでした。直して書き直してください。\n{reasons}"
    return prompt


def generate_post(
    client: anthropic.Anthropic,
    cfg: Config,
    *,
    fmt: str,
    recent_posts: Sequence[str],
    now: datetime,
    feedback: Sequence[str] = (),
) -> str:
    response = client.beta.messages.create(
        model=cfg.model,
        max_tokens=16000,
        betas=[FALLBACK_BETA],
        fallbacks="default",
        output_config={"effort": cfg.effort},
        system=build_system_prompt(cfg),
        messages=[
            {
                "role": "user",
                "content": build_user_prompt(fmt=fmt, recent_posts=recent_posts, now=now, feedback=feedback),
            }
        ],
    )

    if response.stop_reason == "refusal":
        raise GenerationError("AI が今回の投稿の作成を断りました")
    if response.stop_reason == "max_tokens":
        raise GenerationError("AI の出力が途中で切れました")

    text = "".join(block.text for block in response.content if block.type == "text").strip()
    if not text:
        raise GenerationError("AI の出力が空でした")
    return text
