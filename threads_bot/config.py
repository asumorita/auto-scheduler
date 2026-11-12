"""config.toml を読み込む。"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

CONFIG_PATH = Path(__file__).with_name("config.toml")

# Threads が受け付ける1投稿の上限文字数
THREADS_MAX_CHARS = 500


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    enabled: bool
    theme: str
    persona: str
    audience: str
    tone: str
    topic_tag: str
    style_examples: tuple[str, ...]
    min_chars: int
    max_chars: int
    min_lines: int
    max_lines: int
    formats: tuple[str, ...]
    topics: tuple[str, ...]
    ng_words: tuple[str, ...]
    link_url: str
    link_every: int
    link_label: str
    threads_app_id: str
    threads_redirect_uri: str
    model: str
    effort: str


def _strings(values) -> tuple[str, ...]:
    return tuple(str(v).strip() for v in (values or []) if str(v).strip())


def load_config(path: Path = CONFIG_PATH) -> Config:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"config.toml の書き方に誤りがあります: {e}") from None

    bot = raw.get("bot", {})
    account = raw.get("account", {})
    post = raw.get("post", {})
    link = raw.get("link", {})
    threads = raw.get("threads", {})
    ai = raw.get("ai", {})

    cfg = Config(
        enabled=bool(bot.get("enabled", False)),
        theme=str(account.get("theme", "")).strip(),
        persona=str(account.get("persona", "")).strip(),
        audience=str(account.get("audience", "")).strip(),
        tone=str(account.get("tone", "")).strip(),
        topic_tag=str(account.get("topic_tag", "")).strip(),
        style_examples=_strings(account.get("style_examples")),
        min_chars=int(post.get("min_chars", 0)),
        max_chars=int(post.get("max_chars", 400)),
        min_lines=int(post.get("min_lines", 1)),
        max_lines=int(post.get("max_lines", 20)),
        formats=_strings(post.get("formats")),
        topics=_strings(post.get("topics")) or ("（テーマに沿って自由に）",),
        ng_words=_strings(post.get("ng_words")),
        link_url=str(link.get("url", "")).strip(),
        link_every=int(link.get("every", 0)),
        link_label=str(link.get("label", "【PR】")).strip(),
        threads_app_id=str(threads.get("app_id", "")).strip(),
        threads_redirect_uri=str(threads.get("redirect_uri", "")).strip(),
        model=str(ai.get("model", "claude-opus-5-5")).strip(),
        effort=str(ai.get("effort", "medium")).strip(),
    )

    if not cfg.theme:
        raise ConfigError("config.toml の theme（テーマ）が空です。")
    if not cfg.formats:
        raise ConfigError("config.toml の formats（投稿の切り口）が空です。")
    if not 50 <= cfg.max_chars <= THREADS_MAX_CHARS:
        raise ConfigError(f"max_chars は 50〜{THREADS_MAX_CHARS} の間にしてください。")
    if not 0 <= cfg.min_chars < cfg.max_chars:
        raise ConfigError("min_chars は 0 以上、max_chars より小さくしてください。")
    if not 1 <= cfg.min_lines <= cfg.max_lines:
        raise ConfigError("min_lines は 1 以上、max_lines 以下にしてください。")
    if cfg.effort not in ("low", "medium", "high", "xhigh", "max"):
        raise ConfigError("effort は low / medium / high のどれかにしてください。")
    if cfg.link_every < 0:
        raise ConfigError("link の every は 0 以上にしてください。")
    if cfg.link_every > 0 and not cfg.link_url.startswith(("https://", "http://")):
        raise ConfigError("link の every を使うときは、url に https:// から始まるURLを入れてください。")
    if len(cfg.topic_tag) > 50 or any(c in cfg.topic_tag for c in ".&"):
        raise ConfigError("topic_tag は50文字以内で、「.」と「&」は使えません。")
    return cfg
