"""Tests for zhihu_cli.config module."""

from pathlib import Path

from zhihu_cli.config import (
    CONFIG_DIR,
    COOKIE_FILE,
    DEFAULT_TIMEOUT,
    DEFAULT_USER_AGENT,
    MAX_PART_CHARS,
    REQUIRED_COOKIES,
    WRITE_TIMEOUT,
    WRITE_TIMEOUT_MAX,
    ZHIHU_API_V3,
    ZHIHU_API_V4,
    ZHIHU_BASE_URL,
    ZHIHU_LOGIN_URL,
    get_browser_headers,
    timeout_for_write,
)


class TestConfigConstants:
    def test_config_dir_is_under_home(self):
        assert CONFIG_DIR == Path.home() / ".zhihu-cli"

    def test_cookie_file_is_under_config_dir(self):
        assert COOKIE_FILE == CONFIG_DIR / "cookies.json"

    def test_required_cookies_contains_z_c0_xsrf_d_c0(self):
        assert REQUIRED_COOKIES == frozenset({"z_c0", "_xsrf", "d_c0"})

    def test_required_cookies_is_frozenset(self):
        assert isinstance(REQUIRED_COOKIES, frozenset)

    def test_api_urls(self):
        assert ZHIHU_BASE_URL == "https://www.zhihu.com"
        assert ZHIHU_API_V4.startswith(ZHIHU_BASE_URL)
        assert "/api/v4" in ZHIHU_API_V4
        assert "/api/v3" in ZHIHU_API_V3

    def test_login_url(self):
        assert ZHIHU_BASE_URL in ZHIHU_LOGIN_URL
        assert "signin" in ZHIHU_LOGIN_URL

    def test_default_timeout_is_positive(self):
        assert DEFAULT_TIMEOUT > 0

    def test_write_timeout_floor_exceeds_default(self):
        connect, read = timeout_for_write("")
        assert connect == DEFAULT_TIMEOUT
        assert read == WRITE_TIMEOUT
        assert read > DEFAULT_TIMEOUT

    def test_write_timeout_scales_with_payload(self):
        _, small = timeout_for_write("x")
        _, large = timeout_for_write("x" * 2_000_000)
        assert large > small
        assert large <= WRITE_TIMEOUT_MAX

    def test_max_part_chars_is_positive(self):
        assert MAX_PART_CHARS > 0

    def test_default_headers_has_required_keys(self):
        headers = get_browser_headers()
        assert "User-Agent" in headers
        assert "Referer" in headers
        assert "Accept" in headers

    def test_default_user_agent_is_chromium(self):
        assert "Chrome" in DEFAULT_USER_AGENT
        assert "Mozilla" in DEFAULT_USER_AGENT
