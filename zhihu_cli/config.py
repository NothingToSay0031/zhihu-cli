"""Configuration and path management for zhihu-cli."""

from __future__ import annotations

from pathlib import Path

# Application directories
CONFIG_DIR = Path.home() / ".zhihu-cli"
COOKIE_FILE = CONFIG_DIR / "cookies.json"
# QR code image path for AI Agent (e.g. OpenClaw) to send to user for scan login
QRCODE_IMAGE_PATH = CONFIG_DIR / "login_qrcode.png"

# Required cookies for API requests (z_c0 = auth token; _xsrf = CSRF; d_c0 = device)
REQUIRED_COOKIES = frozenset({"z_c0", "_xsrf", "d_c0"})

# Zhihu URLs
ZHIHU_BASE_URL = "https://www.zhihu.com"
ZHIHU_API_V4 = "https://www.zhihu.com/api/v4"
ZHIHU_API_V3 = "https://www.zhihu.com/api/v3"
ZHIHU_ZHUANLAN_API = "https://zhuanlan.zhihu.com/api"
ZHIHU_IMAGE_API = "https://api.zhihu.com/images"
ZHIHU_CONTENT_PUBLISH_URL = f"{ZHIHU_API_V4}/content/publish"
ZHIHU_CONTENT_DRAFTS_URL = f"{ZHIHU_API_V4}/content/drafts"
ZHIHU_OSS_UPLOAD_URL = "https://zhihu-pics-upload.zhimg.com"
ZHIHU_LOGIN_URL = "https://www.zhihu.com/signin"
# QR code login (no Playwright): get token/link, then poll scan_info
ZHIHU_QRCODE_API = f"{ZHIHU_API_V3}/account/api/login/qrcode"
# 防 CAPTCHA / 验证码（v2 登录用）
ZHIHU_OAUTH_CAPTCHA = f"{ZHIHU_API_V3}/oauth/captcha/v2?type=captcha_sign_in"

# HTTP defaults
DEFAULT_TIMEOUT = 15
# Zhihu draft PATCH returns HTTP 554 on very large HTML (~1.7MB observed).
MAX_PART_CHARS = 80_000
MAX_PART_HTML_BYTES = 350_000
ZHIHU_TITLE_MAX = 100
# Article draft PATCH/PUT: Zhihu sanitizes the full HTML before responding.
# A ~2MB body with thousands of formula images routinely exceeds 15s.
WRITE_TIMEOUT = 60
WRITE_TIMEOUT_MAX = 300
WRITE_RETRY_COUNT = 2


def timeout_for_write(content: str = "") -> tuple[float, float]:
    """Return ``(connect, read)`` timeout seconds for article writes.

    Read timeout scales with payload size so large Markdown articles do not
    fail with ``Read timed out. (read timeout=15)`` on draft update.
    """
    nbytes = len(content.encode("utf-8")) if content else 0
    read = min(WRITE_TIMEOUT_MAX, max(WRITE_TIMEOUT, nbytes / 10_000))
    return (float(DEFAULT_TIMEOUT), float(read))

# 全局统一 Chrome 版本号，UA / sec-ch-ua / sec-fetch-* 均从此派生，避免指纹矛盾
CHROME_VERSION = "145"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    f"Chrome/{CHROME_VERSION}.0.0.0 Safari/537.36"
)


def get_browser_headers() -> dict[str, str]:
    """返回与浏览器一致的请求头（UA + sec-ch-ua 统一为 Chrome/{CHROME_VERSION}）。"""
    return {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": f"{ZHIHU_BASE_URL}/",
        "sec-ch-ua": (
            f'"Not:A-Brand";v="99", '
            f'"Google Chrome";v="{CHROME_VERSION}", '
            f'"Chromium";v="{CHROME_VERSION}"'
        ),
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    }
