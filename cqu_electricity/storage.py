from __future__ import annotations

import csv
from pathlib import Path

from .models import MeterReading


SNAPSHOT_FIELDS = (
    "captured_at",
    "room",
    "building",
    "balance_yuan",
    "meter_reading_kwh",
    "subsidy_kwh",
    "meter_address",
)


def _text(value: object | None) -> str:
    return "" if value is None else str(value)


class CsvStore:
    """将每次抓取的原始电表数据追加到一个 CSV 文件。"""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.snapshots_path = data_dir / "history.csv"

    def save(self, reading: MeterReading) -> dict[str, str]:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        row = {
            "captured_at": reading.captured_at.isoformat(timespec="seconds"),
            "room": reading.room,
            "building": reading.building,
            "balance_yuan": _text(reading.balance_yuan),
            "meter_reading_kwh": _text(reading.meter_reading_kwh),
            "subsidy_kwh": _text(reading.subsidy_kwh),
            "meter_address": _text(reading.meter_address),
        }
        is_new = not self.snapshots_path.exists() or self.snapshots_path.stat().st_size == 0
        with self.snapshots_path.open("a", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=SNAPSHOT_FIELDS)
            if is_new:
                writer.writeheader()
            writer.writerow(row)
        return row
