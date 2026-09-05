from __future__ import annotations

from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger


def daily_trigger(time: str, timezone: ZoneInfo) -> CronTrigger:
    """根据已校验的 HH:MM 创建每日触发器。"""
    hour, minute = map(int, time.split(":"))
    return CronTrigger(hour=hour, minute=minute, timezone=timezone)


def email_trigger(schedule: str, timezone: ZoneInfo) -> CronTrigger:
    """根据已校验的 HH:MM@星期 创建邮件触发器。"""
    time, weekdays = schedule.split("@")
    hour, minute = map(int, time.split(":"))
    # APScheduler 的数字星期从周一开始，使用名称避免与配置的编号混淆。
    day_names = ("sun", "mon", "tue", "wed", "thu", "fri", "sat", "sun")
    return CronTrigger(
        hour=hour,
        minute=minute,
        day_of_week=",".join(day_names[int(day)] for day in weekdays.split(",")),
        timezone=timezone,
    )
