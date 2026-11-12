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
from threads_bot.generator import FALLBACK_BETA, GenerationError, build_system_prompt, generate_post
from threads_bot.validate import find_problems

NOW = datetime(2026, 11, 12, 8, 0)

# チェックに合格する長さ・行数の投稿例（互いに似ていないもの）
POST_A = """知らなかった‼️
寝る前のスマホが眠りの質に関係するという話を、ネットでよく見かけます。
画面を見ていると頭が冴えてしまい、なかなか寝つけない人も多いそうです。
私も最近は、布団に入る少し前にスマホを置くようにしています。
皆さんは寝る前にどんなことをして過ごしていますか？"""

POST_B = """毎日歩いている人って、やっぱり元気な印象がありませんか？
ウォーキングを続けている人の話を調べてみると、まずは近所を少し歩くことから始めた人が多いようです。
いきなり頑張りすぎないのが続けるコツなんですね🐢
私も買い物のときは、ひと駅分歩くようにしてみます。"""

POST_C = """水分補給って、喉が渇いてからでいいと思っていませんか？
調べてみると、年齢を重ねると喉の渇きを感じにくくなることがあるそうです。
なるほど、だから意識してこまめに飲むことが大事なんですね。
私は机の上にコップを置いて、気づいたら一口飲むようにしています。
体調で気になることがある人は、お医者さんにも相談してみてください。"""


class ConfigTest(unittest.TestCase):
    def test_bundled_config_loads(self):
        cfg = load_config()
        self.assertFalse(cfg.enabled)
        self.assertEqual(cfg.topic_tag, "健康")
        self.assertEqual(cfg.model, "claude-opus-5-5")
        self.assertEqual(cfg.link_every, 0)
        self.assertGreaterEqual(len(cfg.topics), 10)
        # 切り口と話題の数が互いに素なら、組み合わせが毎回ずれていく
        from math import gcd
        self.assertEqual(gcd(len(cfg.formats), len(cfg.topics)), 1)

    def test_sample_posts_pass_bundled_rules(self):
        cfg = load_config()
        for text in (POST_A, POST_B, POST_C):
            problems = find_problems(
                text,
                max_chars=cfg.max_chars,
                min_chars=cfg.min_chars,
                min_lines=cfg.min_lines,
                max_lines=cfg.max_lines,
                ng_words=cfg.ng_words,
                recent_posts=cfg.style_examples,
            )
            self.assertEqual(problems, [], text)


class ValidateTest(unittest.TestCase):
    def check(self, text, recent=(), **kw):
        args = dict(max_chars=40, ng_words=["治る"], recent_posts=recent)
        args.update(kw)
        return find_problems(text, **args)

    def test_ok(self):
        self.assertEqual(self.check("短くて普通の投稿です"), [])

    def test_too_long_and_too_short(self):
        self.assertTrue(any("長すぎる" in p for p in self.check("あ" * 41)))
        self.assertTrue(any("短すぎる" in p for p in self.check("あ" * 5, min_chars=10)))

    def test_line_count(self):
        self.assertTrue(any("少なすぎる" in p for p in self.check("一行だけ", min_lines=4)))
        self.assertTrue(any("多すぎる" in p for p in self.check("あ\nい\nう", max_lines=2)))
        self.assertEqual(self.check("あ\n\nい\n\nう\n\nえ", min_lines=4, max_lines=4), [])

    def test_url_hashtag_ng(self):
        problems = self.check("これで治る #健康 https://x")
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
            media_id = threads_api.publish_text("tok", "123", "本文", "健康")
        self.assertEqual(media_id, "media-1")
        self.assertEqual(calls[0][2]["media_type"], "TEXT")
        self.assertEqual(calls[0][2]["topic_tag"], "健康")
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
        text = generate_post(
            client, load_config(), fmt="Q&A", topic="睡眠", recent_posts=["前の投稿"], now=NOW
        )
        self.assertEqual(text, "投稿本文")
        kwargs = client.beta.messages.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "claude-opus-5-5")
        self.assertEqual(kwargs["fallbacks"], "default")
        self.assertEqual(kwargs["betas"], [FALLBACK_BETA])
        self.assertEqual(kwargs["output_config"], {"effort": "medium"})
        user_prompt = kwargs["messages"][0]["content"]
        self.assertIn("前の投稿", user_prompt)
        self.assertIn("睡眠", user_prompt)

    def test_system_prompt_has_style_and_health_rules(self):
        prompt = build_system_prompt(load_config())
        self.assertIn("52歳", prompt)
        self.assertIn("<example>", prompt)
        self.assertIn("薬機法", prompt)
        self.assertIn("4〜6行", prompt)

    def test_refusal_raises(self):
        client = mock.Mock()
        client.beta.messages.create.return_value = fake_response("", stop_reason="refusal")
        with self.assertRaises(GenerationError):
            generate_post(client, load_config(), fmt="Q&A", topic="睡眠", recent_posts=[], now=NOW)


class PostFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.history_path = Path(self.tmp.name) / "history.jsonl"
        env = {"ANTHROPIC_API_KEY": "k", "THREADS_ACCESS_TOKEN": "t", "GITHUB_EVENT_NAME": "workflow_dispatch"}
        patches = [
            mock.patch.object(post, "load_history", lambda: history.load_history(self.history_path)),
            mock.patch.object(post, "append_history", lambda e: history.append_history(e, self.history_path)),
            mock.patch.object(post.anthropic, "Anthropic"),
            mock.patch.object(post.threads_api, "get_me", return_value={"id": "123", "username": "tester"}),
            mock.patch.object(post.threads_api, "publish_text", return_value="media-1"),
            mock.patch.object(post.threads_api, "get_permalink", return_value="https://www.threads.net/@tester/post/x"),
            mock.patch.dict(os.environ, env, clear=False),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def run_post(self, texts, dry_run, event="workflow_dispatch"):
        env = {"DRY_RUN": "true" if dry_run else "false", "GITHUB_EVENT_NAME": event}
        with mock.patch.object(post, "generate_post", side_effect=texts) as gen, \
                mock.patch.dict(os.environ, env):
            code = post.main()
        return code, gen

    def test_dry_run_does_not_publish(self):
        code, _ = self.run_post([POST_A], dry_run=True)
        self.assertEqual(code, 0)
        post.threads_api.publish_text.assert_not_called()
        self.assertEqual(history.load_history(self.history_path), [])

    def test_real_run_publishes_and_records(self):
        code, gen = self.run_post([POST_A], dry_run=False)
        self.assertEqual(code, 0)
        post.threads_api.publish_text.assert_called_once_with("t", "123", POST_A, "健康")
        saved = history.load_history(self.history_path)
        self.assertEqual(saved[0]["text"], POST_A)
        self.assertEqual(saved[0]["topic"], gen.call_args.kwargs["topic"])
        self.assertFalse(saved[0]["has_link"])

    def test_topic_and_format_rotate(self):
        self.run_post([POST_A], dry_run=False)
        self.run_post([POST_B], dry_run=False)
        saved = history.load_history(self.history_path)
        cfg = load_config()
        self.assertEqual([e["topic"] for e in saved], list(cfg.topics[:2]))
        self.assertEqual([e["format"] for e in saved], list(cfg.formats[:2]))

    def test_retries_when_check_fails(self):
        code, gen = self.run_post(["#短すぎ", POST_B], dry_run=False)
        self.assertEqual(code, 0)
        self.assertEqual(gen.call_count, 2)
        self.assertTrue(gen.call_args_list[1].kwargs["feedback"])

    def test_gives_up_after_three_failures(self):
        code, gen = self.run_post(["短い1", "短い2", "短い3"], dry_run=False)
        self.assertEqual(code, 1)
        self.assertEqual(gen.call_count, 3)
        post.threads_api.publish_text.assert_not_called()

    def test_schedule_skips_when_disabled(self):
        code, gen = self.run_post([POST_A], dry_run=False, event="schedule")
        self.assertEqual(code, 0)
        gen.assert_not_called()
        post.threads_api.publish_text.assert_not_called()

    def test_schedule_posts_when_enabled(self):
        cfg = replace(load_config(), enabled=True)
        with mock.patch.object(post, "load_config", return_value=cfg):
            code, _ = self.run_post([POST_C], dry_run=False, event="schedule")
        self.assertEqual(code, 0)
        post.threads_api.publish_text.assert_called_once()

    def test_link_every_two_posts(self):
        cfg = replace(load_config(), link_url="https://example.com/a", link_every=2)
        with mock.patch.object(post, "load_config", return_value=cfg):
            self.run_post([POST_A], dry_run=False)
            self.run_post([POST_B], dry_run=False)
        saved = history.load_history(self.history_path)
        self.assertEqual([e["has_link"] for e in saved], [False, True])
        self.assertTrue(saved[1]["text"].startswith("【PR】"))
        self.assertTrue(saved[1]["text"].endswith("https://example.com/a"))
        self.assertLessEqual(len(saved[1]["text"]), 500)


class TokenToolTest(unittest.TestCase):
    def test_auth_url_uses_app_id_and_config_redirect(self):
        with mock.patch.dict(os.environ, {"THREADS_APP_ID": "987", "THREADS_REDIRECT_URI": ""}):
            url = threads_api.build_authorize_url(token_tool.app_id(), token_tool.redirect_uri())
        self.assertIn("client_id=987", url)
        self.assertIn("redirect_uri=https%3A%2F%2Fgithub.com%2Fasumorita%2Fauto-scheduler%2F", url)
        self.assertIn("threads_content_publish", url)

    def test_missing_app_id_is_a_clear_error(self):
        with mock.patch.dict(os.environ, {"THREADS_APP_ID": ""}):
            with self.assertRaises(token_tool.SetupError):
                token_tool.app_id()

    def test_refresh_saves_new_token(self):
        with mock.patch.dict(os.environ, {"THREADS_ACCESS_TOKEN": "old"}), \
                mock.patch.object(token_tool.threads_api, "refresh_long_lived", return_value="new"), \
                mock.patch.object(token_tool.threads_api, "get_me", return_value={"username": "u"}), \
                mock.patch.object(token_tool, "save_secret") as save:
            token_tool.cmd_refresh()
        save.assert_called_once_with("new")

    def test_refresh_without_token_does_nothing(self):
        with mock.patch.dict(os.environ, {"THREADS_ACCESS_TOKEN": ""}), \
                mock.patch.object(token_tool.threads_api, "refresh_long_lived") as refresh, \
                mock.patch.object(token_tool, "save_secret") as save:
            token_tool.cmd_refresh()
        refresh.assert_not_called()
        save.assert_not_called()

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
