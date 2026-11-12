"""投稿履歴（data/history.jsonl）の読み書き。

GitHub Actions が投稿のたびにこのファイルをリポジトリへ保存するので、
アカウントに何かあっても投稿内容は手元に残る。
"""

from __future__ import annotations

import json
from pathlib import Path

HISTORY_PATH = Path(__file__).parent / "data" / "history.jsonl"


def load_history(path: Path = HISTORY_PATH) -> list[dict]:
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            entries.append(json.loads(line))
    return entries


def append_history(entry: dict, path: Path = HISTORY_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def posts_since_last_link(history: list[dict]) -> int:
    count = 0
    for entry in reversed(history):
        if entry.get("has_link"):
            break
        count += 1
    return count
