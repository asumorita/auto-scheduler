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
    theme: str
    audience: str
    tone: str
    topic_tag: str
    max_chars: int
    formats: tuple[str, ...]
    ng_words: tuple[str, ...]
    link_url: str
    link_every: int
    link_label: str
    model: str
    effort: str


def load_config(path: Path = CONFIG_PATH) -> Config:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"config.toml の書き方に誤りがあります: {e}") from None

    account = raw.get("account", {})
    post = raw.get("post", {})
    link = raw.get("link", {})
    ai = raw.get("ai", {})

    cfg = Config(
        theme=str(account.get("theme", "")).strip(),
        audience=str(account.get("audience", "")).strip(),
        tone=str(account.get("tone", "")).strip(),
        topic_tag=str(account.get("topic_tag", "")).strip(),
        max_chars=int(post.get("max_chars", 400)),
        formats=tuple(str(f).strip() for f in post.get("formats", []) if str(f).strip()),
        ng_words=tuple(str(w).strip() for w in post.get("ng_words", []) if str(w).strip()),
        link_url=str(link.get("url", "")).strip(),
        link_every=int(link.get("every", 0)),
        link_label=str(link.get("label", "【PR】")).strip(),
        model=str(ai.get("model", "claude-opus-5-5")).strip(),
        effort=str(ai.get("effort", "medium")).strip(),
    )

    if not cfg.theme:
        raise ConfigError("config.toml の theme（テーマ）が空です。")
    if not cfg.formats:
        raise ConfigError("config.toml の formats（投稿パターン）が空です。")
    if not 50 <= cfg.max_chars <= THREADS_MAX_CHARS:
        raise ConfigError(f"max_chars は 50〜{THREADS_MAX_CHARS} の間にしてください。")
    if cfg.effort not in ("low", "medium", "high", "xhigh", "max"):
        raise ConfigError("effort は low / medium / high のどれかにしてください。")
    if cfg.link_every < 0:
        raise ConfigError("link の every は 0 以上にしてください。")
    if cfg.link_every > 0 and not cfg.link_url.startswith(("https://", "http://")):
        raise ConfigError("link の every を使うときは、url に https:// から始まるURLを入れてください。")
    if len(cfg.topic_tag) > 50 or any(c in cfg.topic_tag for c in ".&"):
        raise ConfigError("topic_tag は50文字以内で、「.」と「&」は使えません。")
    return cfg
