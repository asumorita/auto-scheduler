"""Threads 公式 API とのやり取り。

アクセストークンをログに出さないよう、例外メッセージには URL を含めない。
"""

from __future__ import annotations

import time
from urllib.parse import urlencode

import requests

GRAPH = "https://graph.threads.net"
API = f"{GRAPH}/v1.0"
AUTHORIZE_URL = "https://threads.net/oauth/authorize"
SCOPES = "threads_basic,threads_content_publish"
TIMEOUT = 30

# 投稿の下書き（コンテナ）を作ってから公開するまでの待ち時間（秒）
PUBLISH_WAIT_SECONDS = 30


class ThreadsError(Exception):
    pass


def _request(method: str, url: str, *, params: dict | None = None, data: dict | None = None) -> dict:
    try:
        resp = requests.request(method, url, params=params, data=data, timeout=TIMEOUT)
    except requests.RequestException as e:
        # e には URL（＝トークン）が含まれ得るので、種類名だけ出す
        raise ThreadsError(f"Threads への接続に失敗しました（{type(e).__name__}）") from None

    try:
        body = resp.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}

    if resp.status_code >= 400 or "error" in body:
        err = body.get("error") or {}
        message = err.get("message", "") if isinstance(err, dict) else str(err)
        code = err.get("code") if isinstance(err, dict) else None
        raise ThreadsError(f"Threads API エラー（HTTP {resp.status_code}, code={code}）: {message}")
    return body


def get_me(token: str) -> dict:
    """トークンの持ち主（id, username）を返す。トークンの確認にも使う。"""
    return _request("GET", f"{API}/me", params={"fields": "id,username", "access_token": token})


def publish_text(token: str, user_id: str, text: str, topic_tag: str = "") -> str:
    """テキスト投稿を公開し、投稿の ID を返す。"""
    data = {"media_type": "TEXT", "text": text, "access_token": token}
    if topic_tag:
        data["topic_tag"] = topic_tag
    container = _request("POST", f"{API}/{user_id}/threads", data=data)
    creation_id = container.get("id")
    if not creation_id:
        raise ThreadsError("投稿の下書きを作れませんでした（ID が返ってきません）")

    time.sleep(PUBLISH_WAIT_SECONDS)

    published = _request(
        "POST",
        f"{API}/{user_id}/threads_publish",
        data={"creation_id": creation_id, "access_token": token},
    )
    media_id = published.get("id")
    if not media_id:
        raise ThreadsError("投稿を公開できませんでした（ID が返ってきません）")
    return media_id


def get_permalink(token: str, media_id: str) -> str:
    body = _request("GET", f"{API}/{media_id}", params={"fields": "permalink", "access_token": token})
    return body.get("permalink", "")


def build_authorize_url(app_id: str, redirect_uri: str) -> str:
    query = urlencode(
        {
            "client_id": app_id,
            "redirect_uri": redirect_uri,
            "scope": SCOPES,
            "response_type": "code",
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


def exchange_code(app_id: str, app_secret: str, redirect_uri: str, code: str) -> str:
    """認証コード → 短期トークン（1時間）。"""
    body = _request(
        "POST",
        f"{GRAPH}/oauth/access_token",
        data={
            "client_id": app_id,
            "client_secret": app_secret,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
            "code": code,
        },
    )
    return _token_from(body)


def exchange_for_long_lived(short_token: str, app_secret: str) -> str:
    """短期トークン → 長期トークン（60日）。"""
    body = _request(
        "GET",
        f"{GRAPH}/access_token",
        params={"grant_type": "th_exchange_token", "client_secret": app_secret, "access_token": short_token},
    )
    return _token_from(body)


def refresh_long_lived(token: str) -> str:
    """長期トークンの期限を60日に戻す（発行から24時間以上たったものだけ可能）。"""
    body = _request(
        "GET",
        f"{GRAPH}/refresh_access_token",
        params={"grant_type": "th_refresh_token", "access_token": token},
    )
    return _token_from(body)


def _token_from(body: dict) -> str:
    token = body.get("access_token")
    if not token:
        raise ThreadsError("トークンが返ってきませんでした")
    return token
