from datetime import datetime
from zoneinfo import ZoneInfo


# 全项目统一使用中国标准时间，不通过手动增加 8 小时换算。
SHANGHAI_TIMEZONE = ZoneInfo("Asia/Shanghai")


def now_in_shanghai() -> datetime:
    """返回带有 Asia/Shanghai 时区信息的当前时间。"""
    return datetime.now(SHANGHAI_TIMEZONE)


def ensure_shanghai_timezone(value: datetime) -> datetime:
    """确保 API 返回的时间明确带有 Asia/Shanghai 时区信息。"""
    if value.tzinfo is None:
        # SQLite DATETIME 读取后可能丢失偏移；新数据保存的墙上时间就是北京时间。
        return value.replace(tzinfo=SHANGHAI_TIMEZONE)
    return value.astimezone(SHANGHAI_TIMEZONE)
