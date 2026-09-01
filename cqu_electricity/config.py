from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
import os


class ConfigError(ValueError):
    """环境变量缺失或格式不正确。"""


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(f"缺少环境变量 {name}，请参考 .env.example 配置 .env")
    return value


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} 必须是整数，当前值为 {raw!r}") from exc
    if value <= 0:
        raise ConfigError(f"{name} 必须大于 0")
    return value


def _boolean(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, str(default)).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} 必须是 true 或 false，当前值为 {raw!r}")


def _cron_expressions(raw: str, name: str, timezone: ZoneInfo) -> tuple[str, ...]:
    expressions = tuple(dict.fromkeys(item.strip() for item in raw.split(";") if item.strip()))
    if not expressions:
        raise ConfigError(f"{name} 至少需要一个 Cron 表达式")
    for expression in expressions:
        try:
            CronTrigger.from_crontab(expression, timezone=timezone)
        except ValueError as exc:
            raise ConfigError(
                f"{name} 中的 {expression!r} 无效，应使用五段 Cron 表达式"
            ) from exc
    return expressions


@dataclass(frozen=True, slots=True)
class Settings:
    account: str
    password: str
    room: str
    building: str | None
    schedule_cron: tuple[str, ...]
    timezone: ZoneInfo
    data_dir: Path
    request_timeout: int
    login_retries: int
    log_level: str
    email_enabled: bool
    email_schedule_cron: tuple[str, ...]
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    smtp_from: str
    smtp_to: tuple[str, ...]
    smtp_use_ssl: bool
    smtp_starttls: bool
    smtp_timeout: int
    email_subject_prefix: str
    portal_url: str
    electricity_url: str
    fee_item_id: str

    @classmethod
    def from_env(cls, env_file: str | Path = ".env") -> "Settings":
        load_dotenv(env_file, override=False)
        timezone_name = os.getenv("TIMEZONE", "Asia/Shanghai").strip()
        try:
            timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ConfigError(f"未知时区 TIMEZONE={timezone_name!r}") from exc

        return cls(
            account=_required("CQU_ACCOUNT"),
            password=_required("CQU_PASSWORD"),
            room=_required("CQU_ROOM").upper(),
            building=os.getenv("CQU_BUILDING", "").strip() or None,
            schedule_cron=_cron_expressions(
                os.getenv("SCHEDULE_CRON", "0 0,12 * * *"),
                "SCHEDULE_CRON",
                timezone,
            ),
            timezone=timezone,
            data_dir=Path(os.getenv("DATA_DIR", ".")).expanduser(),
            request_timeout=_positive_int("REQUEST_TIMEOUT", 20),
            login_retries=_positive_int("LOGIN_RETRIES", 8),
            log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
            email_enabled=_boolean("EMAIL_ENABLED", False),
            email_schedule_cron=_cron_expressions(
                os.getenv("EMAIL_SCHEDULE_CRON", "0 8 * * *"),
                "EMAIL_SCHEDULE_CRON",
                timezone,
            ),
            smtp_host=os.getenv("SMTP_HOST", "").strip(),
            smtp_port=_positive_int("SMTP_PORT", 465),
            smtp_username=os.getenv("SMTP_USERNAME", "").strip(),
            smtp_password=os.getenv("SMTP_PASSWORD", ""),
            smtp_from=os.getenv("SMTP_FROM", "").strip(),
            smtp_to=tuple(
                address.strip()
                for address in os.getenv("SMTP_TO", "").split(",")
                if address.strip()
            ),
            smtp_use_ssl=_boolean("SMTP_USE_SSL", True),
            smtp_starttls=_boolean("SMTP_STARTTLS", False),
            smtp_timeout=_positive_int("SMTP_TIMEOUT", 20),
            email_subject_prefix=os.getenv(
                "EMAIL_SUBJECT_PREFIX", "重庆大学电费监控"
            ).strip(),
            portal_url=os.getenv("PORTAL_URL", "http://card.cqu.edu.cn").rstrip("/"),
            electricity_url=os.getenv(
                "ELECTRICITY_URL",
                "http://card.cqu.edu.cn:8080/charge/feeitem/singleItem?feeitemid=182",
            ).strip(),
            fee_item_id=os.getenv("FEE_ITEM_ID", "182").strip(),
        )
