"""AI が書いた投稿文のチェック。"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable

URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)

# 最近の投稿とこれ以上似ていたら作り直す（0〜1、1 は完全一致）
SIMILARITY_LIMIT = 0.6


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def count_lines(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip())


def find_problems(
    text: str,
    *,
    max_chars: int,
    ng_words: Iterable[str],
    recent_posts: Iterable[str],
    min_chars: int = 0,
    min_lines: int = 1,
    max_lines: int = 1000,
) -> list[str]:
    """問題点を日本語で返す。空リストなら合格。"""
    if not text.strip():
        return ["本文が空"]
    problems: list[str] = []
    if len(text) > max_chars:
        problems.append(f"{len(text)}文字で長すぎる（{max_chars}文字以内にする）")
    if len(text) < min_chars:
        problems.append(f"{len(text)}文字で短すぎる（{min_chars}文字以上にする）")
    lines = count_lines(text)
    if lines < min_lines:
        problems.append(f"{lines}行で少なすぎる（{min_lines}〜{max_lines}行にする）")
    if lines > max_lines:
        problems.append(f"{lines}行で多すぎる（{min_lines}〜{max_lines}行にする）")
    if URL_RE.search(text):
        problems.append("URL が入っている（URL は書かない）")
    if "#" in text or "＃" in text:
        problems.append("ハッシュタグ（#）が入っている（# は使わない）")
    hit = [w for w in ng_words if w and w in text]
    if hit:
        problems.append(f"使ってはいけない言葉が入っている: {'、'.join(hit)}")
    for old in recent_posts:
        if similarity(text, old) >= SIMILARITY_LIMIT:
            problems.append("最近の投稿と内容が似すぎている（別の話題・切り口にする）")
            break
    return problems
