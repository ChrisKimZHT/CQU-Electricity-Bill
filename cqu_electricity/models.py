from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


DEFAULT_ELECTRICITY_PRICE = Decimal("0.54")


def total_balance_yuan(
    balance_yuan: Decimal,
    subsidy_kwh: Decimal | None,
    electricity_price: Decimal = DEFAULT_ELECTRICITY_PRICE,
) -> Decimal:
    """将剩余补助电量折算为金额后，与真实余额合计。"""
    return balance_yuan + (subsidy_kwh or Decimal("0")) * electricity_price


@dataclass(frozen=True, slots=True)
class MeterReading:
    captured_at: datetime
    room: str
    building: str
    balance_yuan: Decimal
    meter_reading_kwh: Decimal
    subsidy_kwh: Decimal | None = None
    meter_address: str | None = None

    def total_balance_yuan(
        self, electricity_price: Decimal = DEFAULT_ELECTRICITY_PRICE
    ) -> Decimal:
        return total_balance_yuan(self.balance_yuan, self.subsidy_kwh, electricity_price)
