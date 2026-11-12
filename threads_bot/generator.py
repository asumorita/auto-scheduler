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
    examples = "\n\n".join(
        f"<example>\n{example}\n</example>" for example in cfg.style_examples
    ) or "（なし）"
    return f"""あなたは Threads アカウントの投稿を、書き手本人になりかわって書く担当者です。

# アカウント
- テーマ: {cfg.theme}
- 書き手: {cfg.persona}
- 読者: {cfg.audience}
- 文体: {cfg.tone}

# 文体のお手本（このアカウントの過去の投稿）
雰囲気・言葉づかい・改行の入れ方だけを参考にしてください。内容や言い回しをそのまま使ってはいけません。
{examples}

# 形式
- 投稿の本文だけを出力してください。前置き・説明・タイトル・かぎかっこでのくくりは付けません。
- {cfg.min_lines}〜{min(cfg.max_lines, 6)}行、{cfg.min_chars}〜{cfg.max_chars}文字。短すぎると読まれないので、中身のある内容にしてください。
- ハッシュタグ（#）・URL・商品名・ブランド名は書きません。

# 内容のルール（健康の話なので、正確さと法律を守ります）
- 病気が「治る」「予防できる」「改善する」と言い切らないでください。特定の食品・サプリ・商品の効き目もうたいません（薬機法・健康増進法に触れるおそれがあるため）。
- 数字・統計・研究・専門家の発言は、広く知られていて確かなものだけにしてください。出典や数字を作ってはいけません。自信がなければ数字を使わずに書きます。
- 「〜な人がいた」「ネットで見かけた」は、よく聞く一般的な話として書きます。実在しそうな特定の人物や、「〇kg痩せた」のような具体的な結果を作ってはいけません。
- 書き手自身のことは「私も〜を意識しています」「試してみようと思います」程度にとどめ、具体的な成果や数値は書きません。
- 家族の不幸・病気など、書き手の個人的な出来事は書きません。
- 体の不調など医療の判断が必要な話題では、「気になる人はお医者さんに相談を」と添えてください。
- 「絶対」「必ず」のような言い切りや、不安をあおる書き方はしません。
- 最近の投稿と同じ話題・同じ書き出しを避け、毎回新しい切り口にしてください。"""


def build_user_prompt(
    *,
    fmt: str,
    topic: str,
    recent_posts: Sequence[str],
    now: datetime,
    feedback: Sequence[str] = (),
) -> str:
    date = f"{now:%Y年%m月%d日}（{WEEKDAYS[now.weekday()]}）{now:%H時ごろ}"
    recent = "\n---\n".join(recent_posts) if recent_posts else "（まだありません）"
    prompt = f"""今は {date} です。
今回の話題: {topic}
今回の切り口: {fmt}

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
    topic: str,
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
                "content": build_user_prompt(
                    fmt=fmt, topic=topic, recent_posts=recent_posts, now=now, feedback=feedback
                ),
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
