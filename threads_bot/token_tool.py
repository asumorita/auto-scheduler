"""Threads のアクセストークンを取得・更新し、GitHub の Secrets に保存する。

使い方（GitHub Actions から呼ばれる）:
    python -m threads_bot.token_tool auth-url    # 認証用URLを表示
    python -m threads_bot.token_tool from-code   # 認証コード → 長期トークンを保存
    python -m threads_bot.token_tool refresh     # 長期トークンの期限を延ばして保存

環境変数:
    THREADS_APP_ID         Meta のアプリの「Threads アプリID」
    THREADS_APP_SECRET     Meta のアプリの「Threads app secret」
    THREADS_REDIRECT_URI   Meta のアプリに登録したリダイレクトURL
    THREADS_ACCESS_TOKEN   現在のトークン（refresh のとき）
    AUTH_CODE              認証後のURL、またはその中の code（from-code のとき）
    GH_TOKEN               Secrets を書き換えられる GitHub のトークン
    GITHUB_REPOSITORY      owner/repo（GitHub Actions が自動で設定）
"""

from __future__ import annotations

import os
import subprocess
import sys
from urllib.parse import parse_qs, urlparse

from . import threads_api
from .threads_api import ThreadsError

SECRET_NAME = "THREADS_ACCESS_TOKEN"


class SetupError(Exception):
    pass


def log(message: str) -> None:
    print(message, flush=True)


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SetupError(f"{name} が設定されていません")
    return value


def redirect_uri() -> str:
    uri = os.environ.get("THREADS_REDIRECT_URI", "").strip()
    if uri:
        return uri
    repo = require_env("GITHUB_REPOSITORY")
    return f"https://github.com/{repo}/"


def extract_code(raw: str) -> str:
    """認証後のURLを丸ごと貼られても、code だけを取り出す。"""
    raw = raw.strip()
    if "code=" in raw:
        values = parse_qs(urlparse(raw).query).get("code") or parse_qs(raw.split("?", 1)[-1]).get("code")
        if values:
            raw = values[0]
    # Threads は code の末尾に「#_」を付けて返す
    raw = raw.split("#", 1)[0].strip()
    if not raw:
        raise SetupError("認証コードが見つかりません。認証後に表示されたURLを丸ごと貼ってください")
    return raw


def mask(value: str) -> None:
    """GitHub Actions のログで値を *** に置き換える。"""
    print(f"::add-mask::{value}", flush=True)


def save_secret(token: str) -> None:
    gh_token = os.environ.get("GH_TOKEN", "").strip()
    if not gh_token:
        raise SetupError(
            "GH_PAT_FOR_SECRETS が設定されていないため、トークンを保存できません（README の手順4）"
        )
    repo = require_env("GITHUB_REPOSITORY")
    result = subprocess.run(
        ["gh", "secret", "set", SECRET_NAME, "--repo", repo],
        input=token,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise SetupError(
            "Secrets への保存に失敗しました。GH_PAT_FOR_SECRETS の権限"
            "（このリポジトリの Secrets: Read and write）を確認してください"
        )
    log(f"{SECRET_NAME} を保存しました。")


def cmd_auth_url() -> None:
    url = threads_api.build_authorize_url(require_env("THREADS_APP_ID"), redirect_uri())
    log("次のURLをブラウザで開いて、Threads アカウントでアクセスを許可してください:")
    log(url)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(
                "## 手順1: このリンクを開いて「許可」してください\n\n"
                f"[Threads で許可する]({url})\n\n"
                "許可したあとに表示されたページのURL（アドレスバーの内容）を丸ごとコピーして、"
                "「2. コードからトークンを保存」で貼り付けてください。\n"
            )


def cmd_from_code() -> None:
    code = extract_code(require_env("AUTH_CODE"))
    mask(code)
    app_secret = require_env("THREADS_APP_SECRET")
    short_token = threads_api.exchange_code(require_env("THREADS_APP_ID"), app_secret, redirect_uri(), code)
    mask(short_token)
    long_token = threads_api.exchange_for_long_lived(short_token, app_secret)
    mask(long_token)
    me = threads_api.get_me(long_token)
    log(f"Threads アカウント @{me.get('username', '?')} の長期トークン（60日）を取得しました。")
    save_secret(long_token)


def cmd_refresh() -> None:
    token = require_env("THREADS_ACCESS_TOKEN")
    try:
        new_token = threads_api.refresh_long_lived(token)
    except ThreadsError as refresh_error:
        new_token = None
        # 短期トークンが登録されている場合は、長期トークンへの交換を試す
        app_secret = os.environ.get("THREADS_APP_SECRET", "").strip()
        if app_secret:
            try:
                new_token = threads_api.exchange_for_long_lived(token, app_secret)
            except ThreadsError:
                new_token = None
        if new_token is None:
            # 発行から24時間以内のトークンは更新できない。今のトークンが使えるなら次回に回す
            me = threads_api.get_me(token)
            log(
                f"注意: 今回はトークンを更新できませんでした（{refresh_error}）。"
                f"@{me.get('username', '?')} のトークンはまだ使えるので、次回の自動更新で再試行します。"
            )
            return
    mask(new_token)
    me = threads_api.get_me(new_token)
    log(f"Threads アカウント @{me.get('username', '?')} のトークンを更新しました（60日有効）。")
    save_secret(new_token)


COMMANDS = {"auth-url": cmd_auth_url, "from-code": cmd_from_code, "refresh": cmd_refresh}


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in COMMANDS:
        log(f"使い方: python -m threads_bot.token_tool [{' | '.join(COMMANDS)}]")
        return 2
    try:
        COMMANDS[argv[1]]()
    except (SetupError, ThreadsError) as e:
        log(f"エラー: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
