from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class MeterReading:
    captured_at: datetime
    room: str
    building: str
    balance_yuan: Decimal
    meter_reading_kwh: Decimal
    subsidy_kwh: Decimal | None = None
    meter_address: str | None = None

