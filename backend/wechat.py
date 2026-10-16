import json
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from .config import get_wechat_app_id, get_wechat_app_secret


CODE2SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"
CODE2SESSION_TIMEOUT_SECONDS = 5.0


class WeChatExchangeError(RuntimeError):
    """A safe, client-facing description of a code2Session failure."""


def exchange_code_for_openid(code: str) -> str:
    query = urlencode(
        {
            "appid": get_wechat_app_id(),
            "secret": get_wechat_app_secret(),
            "js_code": code,
            "grant_type": "authorization_code",
        }
    )
    try:
        with urlopen(
            f"{CODE2SESSION_URL}?{query}",
            timeout=CODE2SESSION_TIMEOUT_SECONDS,
        ) as response:
            raw_body = response.read()
    except (HTTPError, URLError, TimeoutError, socket.timeout) as exc:
        raise WeChatExchangeError("微信登录服务暂时不可用") from exc

    try:
        payload = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
        raise WeChatExchangeError("微信登录服务返回异常") from exc

    if not isinstance(payload, dict):
        raise WeChatExchangeError("微信登录服务返回异常")
    if payload.get("errcode") not in (None, 0):
        raise WeChatExchangeError("微信登录凭证无效或已过期")
    openid = payload.get("openid")
    if not isinstance(openid, str) or not openid.strip():
        raise WeChatExchangeError("微信登录响应缺少用户标识")
    return openid.strip()
