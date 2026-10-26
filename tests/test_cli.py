"""Tests for CLI commands via Click's CliRunner."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from zhihu_cli import __version__
from zhihu_cli.cli import cli

# Patch target — ZhihuClient is lazy-imported inside function bodies via
# ``from ..client import ZhihuClient``, so we patch the *source* module.
_CLIENT_PATCH = "zhihu_cli.client.ZhihuClient"


@pytest.fixture()
def runner():
    return CliRunner()


def _make_mock_client(**method_returns):
    """Build a MagicMock that works as a context-manager ZhihuClient."""
    mock = MagicMock()
    for method, retval in method_returns.items():
        getattr(mock, method).return_value = retval
    mock.__enter__ = MagicMock(return_value=mock)
    mock.__exit__ = MagicMock(return_value=False)
    return mock


# ── CLI group ──────────────────────────────────────────────────────────────────


class TestCliGroup:
    def test_help(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "zhihu-cli" in result.output
        assert "login" in result.output
        assert "search" in result.output

    def test_version(self, runner):
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.output

    def test_all_commands_registered(self, runner):
        result = runner.invoke(cli, ["--help"])
        expected = [
            "login", "logout", "status", "whoami",
            "search", "hot", "question", "answer", "answers",
            "feed", "topic",
            "user", "user-answers", "user-articles",
            "followers", "following",
            "vote", "follow-question",
            "publish-md", "publish-dir",
            "collections", "notifications",
        ]
        for cmd in expected:
            assert cmd in result.output, f"Command '{cmd}' not found in help output"


# ── Auth commands ──────────────────────────────────────────────────────────────


class TestStatusCommand:
    def test_status_not_authenticated(self, runner, tmp_config_dir):
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 1
        assert "Not authenticated" in result.output

    def test_status_authenticated(self, runner, saved_cookies):
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "Authenticated" in result.output


class TestLogoutCommand:
    def test_logout_removes_cookies(self, runner, saved_cookies):
        result = runner.invoke(cli, ["logout"])
        assert result.exit_code == 0
        assert "Logged out" in result.output

    def test_logout_no_cookies(self, runner, tmp_config_dir):
        result = runner.invoke(cli, ["logout"])
        assert result.exit_code == 0
        assert "No saved credentials" in result.output


class TestLoginCommand:
    def test_login_with_valid_cookie(self, runner, tmp_config_dir):
        result = runner.invoke(cli, [
            "login", "--cookie", "z_c0=test_abc; _xsrf=x1; d_c0=d1",
        ])
        assert result.exit_code == 0
        assert "Cookie saved" in result.output

    def test_login_with_invalid_cookie(self, runner, tmp_config_dir):
        result = runner.invoke(cli, ["login", "--cookie", "_xsrf=only_this"])
        assert result.exit_code == 1
        assert "z_c0" in result.output

    def test_login_help(self, runner):
        result = runner.invoke(cli, ["login", "--help"])
        assert result.exit_code == 0
        assert "--qrcode" in result.output
        assert "--cookie" in result.output


class TestWhoamiCommand:
    def test_whoami_not_authenticated(self, runner, tmp_config_dir):
        result = runner.invoke(cli, ["whoami"])
        assert result.exit_code == 1
        assert "Not authenticated" in result.output

    def test_whoami_shows_profile(self, runner, saved_cookies, mock_user_info):
        mc = _make_mock_client(get_self_info=mock_user_info)
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["whoami"])
            assert result.exit_code == 0
            assert "TestUser" in result.output

    def test_whoami_json(self, runner, saved_cookies, mock_user_info):
        mc = _make_mock_client(get_self_info=mock_user_info)
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["whoami", "--json"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["name"] == "TestUser"
            assert data["answer_count"] == 42


# ── Content commands ───────────────────────────────────────────────────────────


class TestSearchCommand:
    def test_search_not_authenticated(self, runner, tmp_config_dir):
        result = runner.invoke(cli, ["search", "Python"])
        assert result.exit_code == 1

    def test_search_displays_results(self, runner, saved_cookies, mock_search_result):
        mc = _make_mock_client(search=mock_search_result)
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["search", "Python"])
            assert result.exit_code == 0
            assert "Python" in result.output

    def test_search_json(self, runner, saved_cookies, mock_search_result):
        mc = _make_mock_client(search=mock_search_result)
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["search", "Python", "--json"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert "data" in data

    def test_search_no_results(self, runner, saved_cookies):
        mc = _make_mock_client(search={"data": []})
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["search", "nonexistent_xyz"])
            assert result.exit_code == 0
            assert "No results" in result.output

    def test_search_help(self, runner):
        result = runner.invoke(cli, ["search", "--help"])
        assert result.exit_code == 0
        assert "--type" in result.output
        assert "--limit" in result.output


class TestHotCommand:
    def test_hot_displays_table(self, runner, saved_cookies, mock_hot_list):
        mc = _make_mock_client(get_hot_list=mock_hot_list)
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["hot", "--limit", "2"])
            assert result.exit_code == 0
            assert "Hot question 1" in result.output
            assert "Hot question 2" in result.output

    def test_hot_json(self, runner, saved_cookies, mock_hot_list):
        mc = _make_mock_client(get_hot_list=mock_hot_list)
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["hot", "--json"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert "data" in data


class TestQuestionCommand:
    def test_question_displays(self, runner, saved_cookies):
        q_data = {
            "title": "Test Question Title",
            "detail": "Some detail",
            "answer_count": 5,
            "follower_count": 10,
            "visit_count": 100,
        }
        mc = _make_mock_client(get_question=q_data)
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["question", "12345"])
            assert result.exit_code == 0
            assert "Test Question Title" in result.output


class TestAnswerCommand:
    def test_answer_displays(self, runner, saved_cookies):
        ans_data = {
            "content": "<p>This is the answer</p>",
            "author": {"name": "Author1"},
            "voteup_count": 42,
            "comment_count": 3,
        }
        mc = _make_mock_client(get_answer=ans_data)
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["answer", "67890"])
            assert result.exit_code == 0
            assert "Author1" in result.output


# ── User commands ──────────────────────────────────────────────────────────────


class TestUserCommand:
    def test_user_displays_profile(self, runner, saved_cookies, mock_user_info):
        mc = _make_mock_client(get_user_profile=mock_user_info)
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["user", "test-user"])
            assert result.exit_code == 0
            assert "TestUser" in result.output


class TestUserAnswersCommand:
    def test_user_answers_empty(self, runner, saved_cookies):
        mc = _make_mock_client(get_user_answers={"data": []})
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["user-answers", "test-user"])
            assert result.exit_code == 0
            assert "No answers" in result.output

    def test_user_answers_with_data(self, runner, saved_cookies):
        answers = {
            "data": [
                {
                    "question": {"title": "Q1"},
                    "voteup_count": 10,
                },
            ],
        }
        mc = _make_mock_client(get_user_answers=answers)
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["user-answers", "test-user"])
            assert result.exit_code == 0
            assert "Q1" in result.output


# ── Interact commands ──────────────────────────────────────────────────────────


class TestVoteCommand:
    def test_vote_up(self, runner, saved_cookies):
        mc = _make_mock_client(vote_up=True)
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["vote", "12345"])
            assert result.exit_code == 0
            assert "Upvoted" in result.output

    def test_vote_neutral(self, runner, saved_cookies):
        mc = _make_mock_client(vote_neutral=True)
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["vote", "--neutral", "12345"])
            assert result.exit_code == 0
            assert "Cancelled" in result.output


class TestFollowQuestionCommand:
    def test_follow(self, runner, saved_cookies):
        mc = _make_mock_client(follow_question=True)
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["follow-question", "99999"])
            assert result.exit_code == 0
            assert "Followed" in result.output

    def test_unfollow(self, runner, saved_cookies):
        mc = _make_mock_client(unfollow_question=True)
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["follow-question", "--unfollow", "99999"])
            assert result.exit_code == 0
            assert "Unfollowed" in result.output


class TestCollectionsCommand:
    def test_collections_empty(self, runner, saved_cookies):
        mc = _make_mock_client(get_collections={"data": []})
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["collections"])
            assert result.exit_code == 0
            assert "No collections" in result.output


class TestNotificationsCommand:
    def test_notifications_empty(self, runner, saved_cookies):
        mc = _make_mock_client(get_notifications={"data": []})
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["notifications"])
            assert result.exit_code == 0
            assert "No notifications" in result.output

    def test_notifications_with_data(self, runner, saved_cookies):
        notif_data = {
            "data": [
                {"content": {"text": "Someone liked your answer"}},
            ],
        }
        mc = _make_mock_client(get_notifications=notif_data)
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["notifications"])
            assert result.exit_code == 0
            assert "Notifications" in result.output


class TestAskCommand:
    def test_ask_success(self, runner, saved_cookies):
        mc = _make_mock_client(create_question={"id": 123456})
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["ask", "What is Python?"])
            assert result.exit_code == 0
            assert "123456" in result.output

    def test_ask_with_detail_and_topics(self, runner, saved_cookies):
        mc = _make_mock_client(create_question={"id": 789})
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(
                cli, ["ask", "Title", "-d", "Detail text", "-t", "100", "-t", "200"]
            )
            assert result.exit_code == 0
            assert "789" in result.output

    def test_ask_no_id_returned(self, runner, saved_cookies):
        mc = _make_mock_client(create_question={})
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["ask", "Q"])
            assert result.exit_code == 0
            assert "may have been created" in result.output

    def test_ask_error(self, runner, saved_cookies):
        mc = _make_mock_client()
        mc.create_question.side_effect = Exception("API error")
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["ask", "Q"])
            assert result.exit_code != 0


class TestPinCommand:
    def test_pin_success(self, runner, saved_cookies):
        mc = _make_mock_client(create_pin={"id": 999})
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["pin", "Hello world"])
            assert result.exit_code == 0
            assert "999" in result.output

    def test_pin_no_id_returned(self, runner, saved_cookies):
        mc = _make_mock_client(create_pin={})
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["pin", "Text"])
            assert result.exit_code == 0
            assert "may have been created" in result.output

    def test_pin_error(self, runner, saved_cookies):
        mc = _make_mock_client()
        mc.create_pin.side_effect = Exception("API error")
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["pin", "Text"])
            assert result.exit_code != 0


class TestArticleCommand:
    def test_article_success(self, runner, saved_cookies):
        mc = _make_mock_client(create_article={"id": "art123"})
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["article", "Title", "Body text"])
            assert result.exit_code == 0
            assert "art123" in result.output

    def test_article_no_id_returned(self, runner, saved_cookies):
        mc = _make_mock_client(create_article={})
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["article", "Title", "Body"])
            assert result.exit_code == 0
            assert "may have been published" in result.output

    def test_article_with_topics(self, runner, saved_cookies):
        mc = _make_mock_client(create_article={"id": "art456"})
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(
                cli, ["article", "T", "B", "-t", "100", "-t", "200"]
            )
            assert result.exit_code == 0
            assert "art456" in result.output

    def test_article_error(self, runner, saved_cookies):
        mc = _make_mock_client()
        mc.create_article.side_effect = Exception("API error")
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["article", "T", "B"])
            assert result.exit_code != 0


class TestImageOptions:
    _SAMPLE_INFO = {
        "src": "https://pic-private.zhihu.com/v2-abc~q75.jpg?auth=x",
        "original_src": "https://pic-private.zhihu.com/v2-abc~q75.jpg?auth=y",
        "watermark": "watermark",
        "watermark_src": "",
    }

    def test_pin_with_image(self, runner, saved_cookies, tmp_path):
        img = tmp_path / "photo.jpg"
        img.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 50)
        mc = _make_mock_client(
            upload_image=self._SAMPLE_INFO,
            create_pin={"id": "pin_img_1"},
        )
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["pin", "Hello", "-i", str(img)])
            assert result.exit_code == 0
            assert "pin_img_1" in result.output
            mc.upload_image.assert_called_once_with(str(img), source="pin")
            mc.create_pin.assert_called_once_with(
                title="Hello", content="", image_infos=[self._SAMPLE_INFO]
            )

    def test_ask_with_image(self, runner, saved_cookies, tmp_path):
        img = tmp_path / "photo.jpg"
        img.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 50)
        mc = _make_mock_client(
            upload_image=self._SAMPLE_INFO,
            create_question={"id": 12345},
        )
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["ask", "What?", "-i", str(img)])
            assert result.exit_code == 0
            assert "12345" in result.output
            mc.upload_image.assert_called_once()

    def test_article_with_image(self, runner, saved_cookies, tmp_path):
        img = tmp_path / "photo.jpg"
        img.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 50)
        mc = _make_mock_client(
            upload_image=self._SAMPLE_INFO,
            create_article={"id": "art_img_1"},
        )
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["article", "Title", "Body", "-i", str(img)])
            assert result.exit_code == 0
            assert "art_img_1" in result.output
            mc.upload_image.assert_called_once()


class TestPublishMdCommand:
    def test_publish_md_single_part(self, runner, saved_cookies, tmp_path):
        md = tmp_path / "hello.md"
        md.write_text("# Hi\n\nbody\n", encoding="utf-8")
        mc = _make_mock_client(create_article={"id": "art1"})
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["publish-md", str(md)])
        assert result.exit_code == 0, result.output
        assert "art1" in result.output
        mc.create_article.assert_called_once()
        title = mc.create_article.call_args.kwargs["title"]
        assert title == "hello"
        assert "Part" not in title

    def test_publish_md_splits_large_file(
        self, runner, saved_cookies, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("zhihu_cli.config.MAX_PART_CHARS", 40)
        md = tmp_path / "series.md"
        md.write_text(
            "# A\n\n" + ("a" * 30) + "\n# B\n\n" + ("b" * 30) + "\n",
            encoding="utf-8",
        )
        mc = _make_mock_client()
        mc.create_article.side_effect = [{"id": "p1"}, {"id": "p2"}]
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["publish-md", str(md)])
        assert result.exit_code == 0, result.output
        assert mc.create_article.call_count == 2
        titles = [c.kwargs["title"] for c in mc.create_article.call_args_list]
        assert titles == ["series（Part 1/2）", "series（Part 2/2）"]
        assert "p1" in result.output and "p2" in result.output
        published = json.loads(
            (saved_cookies[0] / "published.json").read_text(encoding="utf-8")
        )
        rec = published[str(md)]
        assert rec["article_id"] == "p1"
        assert [p["article_id"] for p in rec["parts"]] == ["p1", "p2"]

    def test_publish_md_skips_unchanged(self, runner, saved_cookies, tmp_path):
        md = tmp_path / "hello.md"
        md.write_text("# Hi\n\nbody\n", encoding="utf-8")
        mc = _make_mock_client(create_article={"id": "art1"})
        with patch(_CLIENT_PATCH, return_value=mc):
            first = runner.invoke(cli, ["publish-md", str(md)])
            second = runner.invoke(cli, ["publish-md", str(md)])
        assert first.exit_code == 0, first.output
        assert second.exit_code == 0, second.output
        assert "Already published" in second.output
        mc.create_article.assert_called_once()

    def test_publish_md_no_split_keeps_one_article(
        self, runner, saved_cookies, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("zhihu_cli.config.MAX_PART_CHARS", 40)
        md = tmp_path / "series.md"
        md.write_text(
            "# A\n\n" + ("a" * 30) + "\n# B\n\n" + ("b" * 30) + "\n",
            encoding="utf-8",
        )
        mc = _make_mock_client(create_article={"id": "whole"})
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["publish-md", str(md), "--no-split"])
        assert result.exit_code == 0, result.output
        mc.create_article.assert_called_once()
        title = mc.create_article.call_args.kwargs["title"]
        assert title == "series"
        assert "single article" in result.output

    _IMAGE_INFO = {
        "src": "https://pic-private.zhihu.com/v2-fig~q75.png?auth=x",
        "original_src": "https://pic-private.zhihu.com/v2-fig~q75.png?auth=y",
        "watermark": "watermark",
        "watermark_src": "",
    }

    def _image_md(self, tmp_path):
        img = tmp_path / "fig.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)
        md = tmp_path / "with-image.md"
        md.write_text("# Hi\n\n![fig](fig.png)\n", encoding="utf-8")
        return md

    def _two_image_md(self, tmp_path):
        for name in ("fig1.png", "fig2.png"):
            (tmp_path / name).write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)
        md = tmp_path / "with-two-images.md"
        md.write_text(
            "# Hi\n\n![first](fig1.png)\n\n![second](fig2.png)\n",
            encoding="utf-8",
        )
        return md

    def test_publish_md_retries_failed_image(
        self, runner, saved_cookies, tmp_path
    ):
        md = self._image_md(tmp_path)
        mc = _make_mock_client(create_article={"id": "art_img"})
        mc.upload_image.side_effect = [
            RuntimeError("Image processing timed out"),
            RuntimeError("Image processing timed out"),
            self._IMAGE_INFO,
        ]
        with patch(_CLIENT_PATCH, return_value=mc), \
             patch("zhihu_cli.commands.publish.time.sleep") as mock_sleep:
            result = runner.invoke(cli, ["publish-md", str(md), "--no-split"])
        assert result.exit_code == 0, result.output
        assert mc.upload_image.call_count == 3
        assert mock_sleep.call_count == 2
        mc.create_article.assert_called_once()
        content = mc.create_article.call_args.kwargs["content"]
        assert self._IMAGE_INFO["src"] in content

    def test_publish_md_leaves_out_failed_image_and_continues(
        self, runner, saved_cookies, tmp_path
    ):
        md = self._two_image_md(tmp_path)
        mc = _make_mock_client(create_article={"id": "art_img"})
        mc.upload_image.side_effect = [RuntimeError("boom")] * 3 + [
            self._IMAGE_INFO
        ]
        with patch(_CLIENT_PATCH, return_value=mc), \
             patch("zhihu_cli.commands.publish.time.sleep") as mock_sleep:
            result = runner.invoke(cli, ["publish-md", str(md), "--no-split"])
        assert result.exit_code == 0, result.output
        called = [Path(call.args[0]).name for call in mc.upload_image.call_args_list]
        assert called == ["fig1.png", "fig1.png", "fig1.png", "fig2.png"]
        assert mock_sleep.call_count == 2
        mc.create_article.assert_called_once()
        content = mc.create_article.call_args.kwargs["content"]
        assert self._IMAGE_INFO["src"] in content
        assert content.count("<img") == 1
        assert "left out" in result.output
        assert "fig1.png" in result.output
        assert "still be updated" in result.output

    def test_publish_md_updates_when_all_images_fail(
        self, runner, saved_cookies, tmp_path
    ):
        md = self._image_md(tmp_path)
        mc = _make_mock_client(create_article={"id": "art_img"})
        mc.upload_image.side_effect = RuntimeError("boom")
        with patch(_CLIENT_PATCH, return_value=mc), \
             patch("zhihu_cli.commands.publish.time.sleep"):
            result = runner.invoke(cli, ["publish-md", str(md), "--no-split"])
        assert result.exit_code == 0, result.output
        assert mc.upload_image.call_count == 3
        mc.create_article.assert_called_once()
        content = mc.create_article.call_args.kwargs["content"]
        assert "<img" not in content
        assert "fig" in content
        assert "still be updated" in result.output


# ── update-md command ──────────────────────────────────────────────────────────


def _two_part_md(md):
    md.write_text("# A\n\n" + ("a" * 30) + "\n# B\n\n" + ("b" * 30) + "\n", encoding="utf-8")


def _seed_published(config_dir, key: str, ids: list[str]) -> None:
    """Write a publish record for ``key`` covering one article per ID."""
    base = Path(key).stem
    parts = [
        {"title": f"{base}（Part {i}/{len(ids)}）", "article_id": aid}
        for i, aid in enumerate(ids, 1)
    ]
    record = {"sha256": "old", "article_id": ids[0], "title": base, "parts": parts}
    (config_dir / "published.json").write_text(
        json.dumps({key: record}, ensure_ascii=False), encoding="utf-8"
    )


class TestUpdateMdCommand:
    def test_update_md_updates_every_part(
        self, runner, saved_cookies, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("zhihu_cli.config.MAX_PART_CHARS", 40)
        md = tmp_path / "series.md"
        _two_part_md(md)
        _seed_published(saved_cookies[0], str(md), ["p1", "p2"])
        mc = _make_mock_client(update_article={}, delete_article=True)
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["update-md", str(md)])
        assert result.exit_code == 0, result.output
        mc.create_article.assert_not_called()
        ids = [c.kwargs["article_id"] for c in mc.update_article.call_args_list]
        assert ids == ["p1", "p2"]
        mc.delete_article.assert_not_called()

    def test_update_md_creates_new_parts(
        self, runner, saved_cookies, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("zhihu_cli.config.MAX_PART_CHARS", 40)
        md = tmp_path / "series.md"
        _two_part_md(md)
        _seed_published(saved_cookies[0], str(md), ["p1"])
        mc = _make_mock_client(update_article={}, delete_article=True)
        mc.create_article.side_effect = [{"id": "new2"}]
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["update-md", str(md)])
        assert result.exit_code == 0, result.output
        assert mc.update_article.call_count == 1
        mc.create_article.assert_called_once()
        assert "new2" in result.output

    def test_update_md_deletes_surplus_parts(
        self, runner, saved_cookies, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("zhihu_cli.config.MAX_PART_CHARS", 40)
        md = tmp_path / "series.md"
        md.write_text("# A\n\nsmall\n", encoding="utf-8")
        _seed_published(saved_cookies[0], str(md), ["p1", "p2", "p3"])
        mc = _make_mock_client(update_article={}, delete_article=True)
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["update-md", str(md), "-y"])
        assert result.exit_code == 0, result.output
        mc.update_article.assert_called_once()
        deleted = [c.args[0] for c in mc.delete_article.call_args_list]
        assert deleted == ["p2", "p3"]

    def test_update_md_keeps_surplus_when_declined(
        self, runner, saved_cookies, tmp_path
    ):
        md = tmp_path / "series.md"
        md.write_text("# A\n\nsmall\n", encoding="utf-8")
        _seed_published(saved_cookies[0], str(md), ["p1", "p2"])
        mc = _make_mock_client(update_article={}, delete_article=True)
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["update-md", str(md)], input="n\n")
        assert result.exit_code != 0
        mc.update_article.assert_not_called()
        mc.delete_article.assert_not_called()

    def test_update_md_keep_extra_leaves_tail(
        self, runner, saved_cookies, tmp_path
    ):
        md = tmp_path / "series.md"
        md.write_text("# A\n\nsmall\n", encoding="utf-8")
        _seed_published(saved_cookies[0], str(md), ["p1", "p2"])
        mc = _make_mock_client(update_article={}, delete_article=True)
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["update-md", str(md), "--keep-extra"])
        assert result.exit_code == 0, result.output
        mc.delete_article.assert_not_called()

    def test_update_md_collapses_series_with_no_split(
        self, runner, saved_cookies, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("zhihu_cli.config.MAX_PART_CHARS", 40)
        md = tmp_path / "series.md"
        _two_part_md(md)
        _seed_published(saved_cookies[0], str(md), ["p1", "p2", "p3"])
        mc = _make_mock_client(update_article={}, delete_article=True)
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["update-md", str(md), "--no-split", "-y"])
        assert result.exit_code == 0, result.output
        mc.update_article.assert_called_once()
        assert mc.update_article.call_args.kwargs["title"] == "series"
        deleted = [c.args[0] for c in mc.delete_article.call_args_list]
        assert deleted == ["p2", "p3"]

    def test_update_md_accepts_repeated_article_ids(
        self, runner, saved_cookies, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("zhihu_cli.config.MAX_PART_CHARS", 40)
        md = tmp_path / "series.md"
        _two_part_md(md)
        mc = _make_mock_client(update_article={}, delete_article=True)
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(
                cli, ["update-md", str(md), "--article-id", "x1", "--article-id", "x2"]
            )
        assert result.exit_code == 0, result.output
        ids = [c.kwargs["article_id"] for c in mc.update_article.call_args_list]
        assert ids == ["x1", "x2"]

    def test_update_md_finds_record_after_folder_move(
        self, runner, saved_cookies, tmp_path, monkeypatch
    ):
        """A moved file must update the old series instead of duplicating it."""
        monkeypatch.setattr("zhihu_cli.config.MAX_PART_CHARS", 40)
        md = tmp_path / "new_folder" / "series.md"
        md.parent.mkdir()
        _two_part_md(md)
        _seed_published(saved_cookies[0], str(tmp_path / "old_folder" / "series.md"), ["p1", "p2"])
        mc = _make_mock_client(update_article={}, delete_article=True)
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["update-md", str(md)])
        assert result.exit_code == 0, result.output
        assert "同名记录" in result.output
        ids = [c.kwargs["article_id"] for c in mc.update_article.call_args_list]
        assert ids == ["p1", "p2"]
        published = json.loads(
            (saved_cookies[0] / "published.json").read_text(encoding="utf-8")
        )
        assert list(published) == [str(md)]

    def test_update_md_without_record_needs_id(self, runner, saved_cookies, tmp_path):
        md = tmp_path / "brand-new.md"
        md.write_text("# A\n\nbody\n", encoding="utf-8")
        mc = _make_mock_client(update_article={})
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["update-md", str(md)])
        assert result.exit_code == 1
        assert "--article-id" in result.output
        mc.update_article.assert_not_called()


class TestPublishMdDuplicateGuard:
    def test_publish_md_warns_about_same_stem_record(
        self, runner, saved_cookies, tmp_path
    ):
        md = tmp_path / "moved" / "series.md"
        md.parent.mkdir()
        md.write_text("# A\n\nbody\n", encoding="utf-8")
        _seed_published(saved_cookies[0], str(tmp_path / "origin" / "series.md"), ["p1"])
        mc = _make_mock_client(create_article={"id": "art1"})
        with patch(_CLIENT_PATCH, return_value=mc):
            result = runner.invoke(cli, ["publish-md", str(md)])
        assert result.exit_code == 0, result.output
        assert "update-md" in result.output

