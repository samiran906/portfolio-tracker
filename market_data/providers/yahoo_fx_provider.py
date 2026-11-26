"""Yahoo Finance provider for historical foreign-exchange rates."""

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional

import yfinance as yf

from market_data.errors import MarketDataError
from market_data.fx_models import FxRateBar


YAHOO_FX_TICKER = "USDINR=X"
BASE_CURRENCY = "USD"
QUOTE_CURRENCY = "INR"


def _decimal(value) -> Optional[Decimal]:
    """Convert a finite provider value to Decimal."""
    if value is None:
        return None

    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None

    if not result.is_finite():
        return None

    return result


def _positive_decimal(value) -> Optional[Decimal]:
    """Return a positive Decimal, otherwise None."""
    result = _decimal(value)

    if result is None or result <= 0:
        return None

    return result


class YahooFinanceFxProvider:
    """Retrieve daily USD/INR rates from Yahoo Finance."""

    def get_history(
        self,
        start_date: date,
        end_date: Optional[date] = None,
    ) -> list[FxRateBar]:
        """Return daily USD/INR bars, including both requested dates."""

        if not isinstance(start_date, date):
            raise TypeError("start_date must be a date")

        if end_date is not None and not isinstance(end_date, date):
            raise TypeError("end_date must be a date")

        if end_date is not None and end_date < start_date:
            raise ValueError("end_date must not precede start_date")

        # Yahoo Finance treats its end parameter as exclusive.
        exclusive_end = (end_date or date.today()) + timedelta(days=1)

        try:
            ticker = yf.Ticker(YAHOO_FX_TICKER)
            frame = ticker.history(
                start=start_date.isoformat(),
                end=exclusive_end.isoformat(),
                interval="1d",
                auto_adjust=False,
                actions=False,
                raise_errors=True,
            )
        except Exception as exc:
            raise MarketDataError(
                f"Yahoo Finance FX history request failed for {YAHOO_FX_TICKER}"
            ) from exc

        if frame is None or frame.empty:
            return []

        bars = []

        for index, row in frame.iterrows():
            try:
                try:
                    rate_date = index.date()
                except AttributeError:
                    rate_date = date.fromisoformat(str(index)[:10])

                close = _positive_decimal(row.get("Close"))

                if close is None:
                    continue

                bar = FxRateBar(
                    rate_date=rate_date,
                    base_currency=BASE_CURRENCY,
                    quote_currency=QUOTE_CURRENCY,
                    open=_positive_decimal(row.get("Open")),
                    high=_positive_decimal(row.get("High")),
                    low=_positive_decimal(row.get("Low")),
                    close=close,
                )

                bars.append(bar)

            except (TypeError, ValueError):
                # Ignore malformed individual records rather than failing
                # an otherwise usable historical response.
                continue

        return sorted(bars, key=lambda bar: bar.rate_date)
