"""Normalized models for historical foreign-exchange rates."""

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class FxRateBar:
    """One daily FX rate, expressed as quote currency per base currency."""

    rate_date: date
    base_currency: str
    quote_currency: str
    close: Decimal
    open: Optional[Decimal] = None
    high: Optional[Decimal] = None
    low: Optional[Decimal] = None

    def __post_init__(self):
        if not isinstance(self.rate_date, date) or isinstance(
            self.rate_date, datetime
        ):
            raise TypeError("rate_date must be a date")

        for field_name in ("base_currency", "quote_currency"):
            value = getattr(self, field_name)

            if not isinstance(value, str):
                raise TypeError(f"{field_name} must be a string")

            normalized = value.strip().upper()

            if not re.fullmatch(r"[A-Z]{3}", normalized):
                raise ValueError(
                    f"{field_name} must be a three-character currency code"
                )

            object.__setattr__(self, field_name, normalized)

        if self.base_currency == self.quote_currency:
            raise ValueError("base_currency and quote_currency must differ")

        for field_name in ("close", "open", "high", "low"):
            value = getattr(self, field_name)

            if value is None and field_name != "close":
                continue

            if (
                not isinstance(value, Decimal)
                or not value.is_finite()
                or value <= 0
            ):
                raise ValueError(
                    f"{field_name} must be a finite Decimal greater than zero"
                )

        if (
            self.high is not None
            and self.low is not None
            and self.high < self.low
        ):
            raise ValueError("high must not be lower than low")
