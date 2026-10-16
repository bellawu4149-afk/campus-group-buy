import os


DEFAULT_WECHAT_APP_ID = "wxf12a28100536f06f"
AUTH_TOKEN_ALGORITHM = "HS256"
AUTH_TOKEN_EXPIRE_SECONDS = 7 * 24 * 60 * 60


class ConfigurationError(RuntimeError):
    """Required server-side configuration is missing."""


def get_wechat_app_id() -> str:
    return os.environ.get("WECHAT_APP_ID", DEFAULT_WECHAT_APP_ID).strip()


def get_wechat_app_secret() -> str:
    value = os.environ.get("WECHAT_APP_SECRET", "").strip()
    if not value:
        raise ConfigurationError("微信登录服务尚未配置")
    return value


def get_auth_token_secret() -> str:
    value = os.environ.get("AUTH_TOKEN_SECRET", "").strip()
    if not value:
        raise ConfigurationError("认证服务尚未配置")
    return value
