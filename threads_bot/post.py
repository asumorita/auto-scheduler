"""1回分の投稿を行う（GitHub Actions から定期的に呼ばれる）。

使い方:
    python -m threads_bot.post

環境変数:
    ANTHROPIC_API_KEY     Claude API のキー
    THREADS_ACCESS_TOKEN  Threads の長期アクセストークン
    DRY_RUN               "true" なら投稿文を作るだけで投稿しない（テスト用）
    GITHUB_EVENT_NAME     GitHub Actions が設定。"schedule"（定期実行）のときは
                          config.toml の enabled が true の場合だけ投稿する
"""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import anthropic

from . import threads_api
from .config import THREADS_MAX_CHARS, Config, ConfigError, load_config
from .generator import GenerationError, generate_post
from .history import append_history, load_history, posts_since_last_link
from .validate import find_problems

JST = ZoneInfo("Asia/Tokyo")
MAX_ATTEMPTS = 3
RECENT_FOR_PROMPT = 12  # AI に見せる最近の投稿の数（約1日分）
RECENT_FOR_CHECK = 60  # 似すぎチェックに使う最近の投稿の数（約5日分）


def log(message: str) -> None:
    print(message, flush=True)


def write_summary(markdown: str) -> None:
    """GitHub Actions の実行結果ページに表示する。"""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(markdown + "\n")


def is_true(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes")


def should_add_link(cfg: Config, history: list[dict]) -> bool:
    if cfg.link_every <= 0 or not cfg.link_url:
        return False
    return posts_since_last_link(history) >= cfg.link_every - 1


def compose(body: str, cfg: Config, with_link: bool) -> str:
    if not with_link:
        return body
    return f"{cfg.link_label}\n{body}\n\n{cfg.link_url}"


def body_limit(cfg: Config, with_link: bool) -> int:
    """本文に使える文字数（リンクと広告表記の分を差し引く）。"""
    if not with_link:
        return cfg.max_chars
    extra = len(cfg.link_label) + len(cfg.link_url) + 3  # 改行3つ分
    return min(cfg.max_chars, THREADS_MAX_CHARS - extra)


def pick(items: tuple[str, ...], index: int) -> str:
    return items[index % len(items)]


def create_body(cfg: Config, history: list[dict], with_link: bool, now: datetime) -> tuple[str, str, str]:
    """投稿文を作ってチェックする。合格した本文・切り口・話題を返す。"""
    fmt = pick(cfg.formats, len(history))
    topic = pick(cfg.topics, len(history))
    bodies = [h.get("body") or h.get("text", "") for h in history]
    recent_for_prompt = bodies[-RECENT_FOR_PROMPT:]
    recent_for_check = list(cfg.style_examples) + bodies[-RECENT_FOR_CHECK:]
    limit = body_limit(cfg, with_link)
    prompt_cfg = replace(cfg, max_chars=limit)

    client = anthropic.Anthropic()
    feedback: list[str] = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        log(f"投稿文を作成中…（{attempt}回目、話題: {topic}、切り口: {fmt}）")
        body = generate_post(
            client,
            prompt_cfg,
            fmt=fmt,
            topic=topic,
            recent_posts=recent_for_prompt,
            now=now,
            feedback=feedback,
        )
        feedback = find_problems(
            body,
            max_chars=limit,
            min_chars=cfg.min_chars,
            min_lines=cfg.min_lines,
            max_lines=cfg.max_lines,
            ng_words=cfg.ng_words,
            recent_posts=recent_for_check,
        )
        if not feedback:
            return body, fmt, topic
        log("チェックで不合格: " + " / ".join(feedback))
    raise GenerationError(f"{MAX_ATTEMPTS}回作り直しても条件を満たす投稿ができませんでした")


def run() -> int:
    dry_run = is_true(os.environ.get("DRY_RUN"))
    token = os.environ.get("THREADS_ACCESS_TOKEN", "").strip()
    now = datetime.now(JST)

    cfg = load_config()
    if os.environ.get("GITHUB_EVENT_NAME") == "schedule" and not cfg.enabled:
        log("config.toml の enabled が false なので、今回は投稿しません。")
        return 0

    history = load_history()
    with_link = should_add_link(cfg, history)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        log("エラー: ANTHROPIC_API_KEY が設定されていません（GitHub の Secrets に登録してください）")
        return 1
    if not token and not dry_run:
        log("エラー: THREADS_ACCESS_TOKEN が設定されていません（「Threads 初期設定」を先に実行してください）")
        return 1

    # 先に Threads の接続を確かめる（トークンが無効なら AI の料金を使わずに止める）
    me = None
    if token:
        me = threads_api.get_me(token)
        log(f"Threads アカウントを確認しました: @{me.get('username', '?')}")
    else:
        log("注意: THREADS_ACCESS_TOKEN がないため、Threads アカウントの確認は省きました")

    body, fmt, topic = create_body(cfg, history, with_link, now)
    text = compose(body, cfg, with_link)
    log("----- 投稿文 -----\n" + text + "\n------------------")

    if dry_run:
        write_summary(
            "## テスト実行（投稿はしていません）\n\n"
            + (f"アカウント: @{me.get('username', '?')}\n\n" if me else "")
            + f"話題: {topic} ／ 切り口: {fmt}\n\n```\n{text}\n```"
        )
        log("テスト実行のため、投稿はしません。")
        return 0

    media_id = threads_api.publish_text(token, me["id"], text, cfg.topic_tag)
    try:
        permalink = threads_api.get_permalink(token, media_id)
    except threads_api.ThreadsError:
        permalink = ""

    append_history(
        {
            "posted_at": now.isoformat(timespec="seconds"),
            "topic": topic,
            "format": fmt,
            "body": body,
            "text": text,
            "has_link": with_link,
            "threads_id": media_id,
            "permalink": permalink,
        }
    )
    log(f"投稿しました: {permalink or media_id}")
    write_summary(f"## 投稿しました\n\n{permalink}\n\n```\n{text}\n```")
    return 0


def main() -> int:
    try:
        return run()
    except ConfigError as e:
        log(f"設定エラー: {e}")
    except GenerationError as e:
        log(f"投稿文の作成エラー: {e}")
    except threads_api.ThreadsError as e:
        log(f"Threads エラー: {e}")
    except anthropic.AuthenticationError:
        log("Claude API エラー: ANTHROPIC_API_KEY が正しくありません")
    except anthropic.PermissionDeniedError:
        log("Claude API エラー: この API キーではモデルを使えません（権限・残高を確認してください）")
    except anthropic.RateLimitError:
        log("Claude API エラー: 利用回数の上限に達しました。時間をおいて再実行してください")
    except anthropic.APIStatusError as e:
        log(f"Claude API エラー（HTTP {e.status_code}）: {e.message}")
    except anthropic.APIConnectionError:
        log("Claude API エラー: 接続できませんでした")
    return 1


if __name__ == "__main__":
    sys.exit(main())
