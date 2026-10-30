"""Normalized models shared by all market-data providers."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class PriceBar:
    """One historical daily price record."""

    price_date: date
    close: Decimal
    currency: str
    open: Optional[Decimal] = None
    high: Optional[Decimal] = None
    low: Optional[Decimal] = None

    def __post_init__(self):
        if not isinstance(self.price_date, date):
            raise TypeError("price_date must be a date")
        if self.close <= 0:
            raise ValueError("close must be greater than zero")
        if len(self.currency.strip()) != 3:
            raise ValueError("currency must be a three-character code")
        object.__setattr__(self, "currency", self.currency.strip().upper())


@dataclass(frozen=True)
class MarketQuote:
    """Latest available quote, separate from historical daily prices."""

    price: Decimal
    quote_time: datetime
    currency: str
    open: Optional[Decimal] = None
    high: Optional[Decimal] = None
    low: Optional[Decimal] = None
    previous_close: Optional[Decimal] = None

    def __post_init__(self):
        if not isinstance(self.price, Decimal) or not self.price.is_finite() or self.price <= 0:
            raise ValueError("price must be a finite value greater than zero")
        if not isinstance(self.quote_time, datetime):
            raise TypeError("quote_time must be a datetime")
        if self.quote_time.tzinfo is None or self.quote_time.utcoffset() is None:
            raise ValueError("quote_time must be timezone-aware")
        if not isinstance(self.currency, str) or len(self.currency.strip()) != 3:
            raise ValueError("currency must be a three-character code")

        for field_name in ("open", "high", "low", "previous_close"):
            value = getattr(self, field_name)
            if value is not None and (
                not isinstance(value, Decimal) or not value.is_finite() or value <= 0
            ):
                raise ValueError(f"{field_name} must be a finite value greater than zero")

        object.__setattr__(self, "currency", self.currency.strip().upper())
