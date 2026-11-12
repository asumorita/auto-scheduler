"""外部の API を呼ばずに、ボットの動きを確かめるテスト。

実行: python -m unittest discover -s threads_bot/tests -t .
"""

from __future__ import annotations

import os
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import requests

from threads_bot import history, post, threads_api, token_tool
from threads_bot.config import load_config
from threads_bot.generator import FALLBACK_BETA, GenerationError, generate_post
from threads_bot.validate import find_problems

NOW = datetime(2026, 11, 12, 8, 0)


class ConfigTest(unittest.TestCase):
    def test_bundled_config_loads(self):
        cfg = load_config()
        self.assertTrue(cfg.theme)
        self.assertLessEqual(cfg.max_chars, 500)
        self.assertEqual(cfg.model, "claude-opus-5-5")


class ValidateTest(unittest.TestCase):
    def check(self, text, recent=()):
        return find_problems(text, max_chars=20, ng_words=["必ず稼げる"], recent_posts=recent)

    def test_ok(self):
        self.assertEqual(self.check("短くて普通の投稿です"), [])

    def test_too_long(self):
        self.assertTrue(any("長すぎる" in p for p in self.check("あ" * 21)))

    def test_url_hashtag_ng(self):
        problems = self.check("必ず稼げる #AI https://x")
        self.assertEqual(len(problems), 3)

    def test_too_similar(self):
        problems = self.check("今日のコツはメモです", recent=["今日のコツはメモです！"])
        self.assertTrue(any("似すぎ" in p for p in problems))


class ExtractCodeTest(unittest.TestCase):
    def test_full_url_with_fragment(self):
        url = "https://github.com/owner/repo/?code=AQBabc123#_"
        self.assertEqual(token_tool.extract_code(url), "AQBabc123")

    def test_bare_code(self):
        self.assertEqual(token_tool.extract_code("AQBabc123#_"), "AQBabc123")
        self.assertEqual(token_tool.extract_code("code=AQBabc123#_"), "AQBabc123")


class ThreadsApiTest(unittest.TestCase):
    def test_error_message_does_not_leak_token(self):
        response = mock.Mock(status_code=400)
        response.json.return_value = {"error": {"message": "Invalid parameter", "code": 100}}
        with mock.patch("threads_bot.threads_api.requests.request", return_value=response):
            with self.assertRaises(threads_api.ThreadsError) as ctx:
                threads_api.get_me("SECRET-TOKEN")
        self.assertNotIn("SECRET-TOKEN", str(ctx.exception))
        self.assertIn("Invalid parameter", str(ctx.exception))

    def test_connection_error_does_not_leak_token(self):
        err = requests.ConnectionError("failed for url ...?access_token=SECRET-TOKEN")
        with mock.patch("threads_bot.threads_api.requests.request", side_effect=err):
            with self.assertRaises(threads_api.ThreadsError) as ctx:
                threads_api.get_me("SECRET-TOKEN")
        self.assertNotIn("SECRET-TOKEN", str(ctx.exception))
        self.assertIsNone(ctx.exception.__cause__)

    def test_publish_two_steps(self):
        calls = []

        def fake_request(method, url, *, params=None, data=None, timeout=None):
            calls.append((method, url, data))
            resp = mock.Mock(status_code=200)
            resp.json.return_value = {"id": "container-1" if url.endswith("/threads") else "media-1"}
            return resp

        with mock.patch("threads_bot.threads_api.requests.request", side_effect=fake_request), \
                mock.patch("threads_bot.threads_api.time.sleep"):
            media_id = threads_api.publish_text("tok", "123", "本文", "AI活用")
        self.assertEqual(media_id, "media-1")
        self.assertEqual(calls[0][2]["media_type"], "TEXT")
        self.assertEqual(calls[0][2]["topic_tag"], "AI活用")
        self.assertEqual(calls[1][2]["creation_id"], "container-1")


def fake_response(text, stop_reason="end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
    )


class GeneratorTest(unittest.TestCase):
    def test_request_shape_and_text(self):
        client = mock.Mock()
        client.beta.messages.create.return_value = fake_response("  投稿本文  ")
        text = generate_post(client, load_config(), fmt="Q&A", recent_posts=["前の投稿"], now=NOW)
        self.assertEqual(text, "投稿本文")
        kwargs = client.beta.messages.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "claude-opus-5-5")
        self.assertEqual(kwargs["fallbacks"], "default")
        self.assertEqual(kwargs["betas"], [FALLBACK_BETA])
        self.assertEqual(kwargs["output_config"], {"effort": "medium"})
        self.assertIn("前の投稿", kwargs["messages"][0]["content"])

    def test_refusal_raises(self):
        client = mock.Mock()
        client.beta.messages.create.return_value = fake_response("", stop_reason="refusal")
        with self.assertRaises(GenerationError):
            generate_post(client, load_config(), fmt="Q&A", recent_posts=[], now=NOW)


class PostFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.history_path = Path(self.tmp.name) / "history.jsonl"
        patches = [
            mock.patch.object(post, "load_history", lambda: history.load_history(self.history_path)),
            mock.patch.object(post, "append_history", lambda e: history.append_history(e, self.history_path)),
            mock.patch.object(post.anthropic, "Anthropic"),
            mock.patch.object(post.threads_api, "get_me", return_value={"id": "123", "username": "tester"}),
            mock.patch.object(post.threads_api, "publish_text", return_value="media-1"),
            mock.patch.object(post.threads_api, "get_permalink", return_value="https://www.threads.net/@tester/post/x"),
            mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k", "THREADS_ACCESS_TOKEN": "t"}, clear=False),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def run_post(self, texts, dry_run):
        with mock.patch.object(post, "generate_post", side_effect=texts) as gen, \
                mock.patch.dict(os.environ, {"DRY_RUN": "true" if dry_run else "false"}):
            code = post.main()
        return code, gen

    def test_dry_run_does_not_publish(self):
        code, _ = self.run_post(["テストの投稿です"], dry_run=True)
        self.assertEqual(code, 0)
        post.threads_api.publish_text.assert_not_called()
        self.assertEqual(history.load_history(self.history_path), [])

    def test_real_run_publishes_and_records(self):
        code, _ = self.run_post(["本番の投稿です"], dry_run=False)
        self.assertEqual(code, 0)
        post.threads_api.publish_text.assert_called_once_with("t", "123", "本番の投稿です", "AI活用")
        saved = history.load_history(self.history_path)
        self.assertEqual(saved[0]["text"], "本番の投稿です")
        self.assertFalse(saved[0]["has_link"])

    def test_retries_when_check_fails(self):
        code, gen = self.run_post(["#ハッシュタグ入り", "直した投稿です"], dry_run=False)
        self.assertEqual(code, 0)
        self.assertEqual(gen.call_count, 2)
        self.assertTrue(gen.call_args_list[1].kwargs["feedback"])

    def test_gives_up_after_three_failures(self):
        code, gen = self.run_post(["#1", "#2", "#3"], dry_run=False)
        self.assertEqual(code, 1)
        self.assertEqual(gen.call_count, 3)
        post.threads_api.publish_text.assert_not_called()

    def test_link_every_two_posts(self):
        cfg = replace(load_config(), link_url="https://example.com/a", link_every=2)
        with mock.patch.object(post, "load_config", return_value=cfg):
            self.run_post(["一つ目の投稿です"], dry_run=False)
            self.run_post(["二つ目はまったく別の話題"], dry_run=False)
        saved = history.load_history(self.history_path)
        self.assertEqual([e["has_link"] for e in saved], [False, True])
        self.assertTrue(saved[1]["text"].startswith("【PR】"))
        self.assertTrue(saved[1]["text"].endswith("https://example.com/a"))
        self.assertLessEqual(len(saved[1]["text"]), 500)


class RefreshTest(unittest.TestCase):
    def test_refresh_saves_new_token(self):
        with mock.patch.dict(os.environ, {"THREADS_ACCESS_TOKEN": "old"}), \
                mock.patch.object(token_tool.threads_api, "refresh_long_lived", return_value="new"), \
                mock.patch.object(token_tool.threads_api, "get_me", return_value={"username": "u"}), \
                mock.patch.object(token_tool, "save_secret") as save:
            token_tool.cmd_refresh()
        save.assert_called_once_with("new")

    def test_refresh_too_early_is_only_a_warning(self):
        err = threads_api.ThreadsError("too early")
        with mock.patch.dict(os.environ, {"THREADS_ACCESS_TOKEN": "old", "THREADS_APP_SECRET": ""}), \
                mock.patch.object(token_tool.threads_api, "refresh_long_lived", side_effect=err), \
                mock.patch.object(token_tool.threads_api, "get_me", return_value={"username": "u"}), \
                mock.patch.object(token_tool, "save_secret") as save:
            token_tool.cmd_refresh()
        save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
