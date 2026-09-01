from __future__ import annotations

import argparse
import signal
import sys
from collections.abc import Callable
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from loguru import logger

from .client import CquElectricityClient, CquError
from .chart import ChartError, draw_history_chart
from .config import ConfigError, Settings
from .storage import CsvStore


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="重庆大学宿舍电费监控")
    parser.add_argument(
        "command", choices=("once", "daemon", "plot"), help="单次抓取、定时常驻或生成图表"
    )
    parser.add_argument("--env-file", default=".env", help="环境变量文件，默认 .env")
    parser.add_argument("--output", help="图表输出路径，默认 DATA_DIR/history.png")
    return parser


def _configure_logging(level: str) -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        level=level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
        colorize=sys.stderr.isatty(),
        backtrace=True,
        diagnose=False,
    )


def _job(settings: Settings) -> Callable[[], None]:
    store = CsvStore(settings.data_dir)

    def run() -> None:
        try:
            reading = CquElectricityClient(settings).fetch()
            store.save(reading)
            logger.info(
                "抓取成功：房间={} 余额={} 元 电表读数={} kWh",
                reading.room,
                reading.balance_yuan,
                reading.meter_reading_kwh,
            )
        except Exception:
            logger.exception("电费抓取失败")

    return run


def main() -> int:
    args = _parser().parse_args()
    try:
        settings = Settings.from_env(args.env_file)
    except ConfigError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 2
    _configure_logging(settings.log_level)

    if args.command == "plot":
        output_path = (
            settings.data_dir / "history.png"
            if args.output is None
            else Path(args.output)
        )
        try:
            result_path = draw_history_chart(
                settings.data_dir / "history.csv", output_path, settings.room
            )
        except ChartError as exc:
            logger.error("制图失败：{}", exc)
            return 1
        logger.info("图表已生成：{}", result_path.resolve())
        return 0

    job = _job(settings)

    if args.command == "once":
        try:
            reading = CquElectricityClient(settings).fetch()
            CsvStore(settings.data_dir).save(reading)
        except CquError as exc:
            logger.error("抓取失败：{}", exc)
            return 1
        except Exception:
            logger.exception("抓取失败")
            return 1
        logger.info(
            "抓取成功：房间={} 余额={} 元 电表读数={} kWh",
            reading.room,
            reading.balance_yuan,
            reading.meter_reading_kwh,
        )
        return 0

    scheduler = BlockingScheduler(timezone=settings.timezone)
    for scheduled_time in settings.schedule_times:
        scheduler.add_job(
            job,
            "cron",
            hour=scheduled_time.hour,
            minute=scheduled_time.minute,
            id=f"capture-{scheduled_time:%H%M}",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
    signal.signal(signal.SIGTERM, lambda *_: scheduler.shutdown(wait=False))
    logger.info(
        "后台监控已启动，抓取时间：{}（{}）",
        ", ".join(t.strftime("%H:%M") for t in settings.schedule_times),
        settings.timezone.key,
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("后台监控已停止")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
