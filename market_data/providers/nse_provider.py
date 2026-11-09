"""NSE India provider for stocks, ETFs, and Sovereign Gold Bonds."""

import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from nse import NSE

from market_data.errors import MarketDataError
from market_data.models import MarketQuote, PriceBar


INDIA_TZ = ZoneInfo("Asia/Kolkata")
CACHE_DIR = Path("/tmp/portfolio-nse-cache")

SUPPORTED_SERIES = {"EQ", "GB"}


def _validate_symbol(symbol: str) -> str:
    if not isinstance(symbol, str):
        raise ValueError("NSE symbol must be a string")

    symbol = symbol.strip().upper()

    if not re.fullmatch(r"[A-Z0-9&._-]{1,40}", symbol):
        raise ValueError("Invalid NSE symbol")

    return symbol


def _validate_series(series: str) -> str:
    if not isinstance(series, str):
        raise ValueError("NSE series must be a string")

    series = series.strip().upper()

    if series not in SUPPORTED_SERIES:
        raise ValueError(f"Unsupported NSE series: {series}")

    return series


def _decimal(value) -> Optional[Decimal]:
    if value is None:
        return None

    try:
        result = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError, TypeError, AttributeError):
        return None

    if not result.is_finite() or result <= 0:
        return None

    return result


def _parse_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    if not isinstance(value, str):
        raise MarketDataError("NSE returned an invalid historical date")

    value = value.strip()

    for fmt in ("%d-%b-%Y", "%d-%b-%Y %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue

    raise MarketDataError(f"Unrecognized NSE historical date: {value}")


def _parse_quote_time(value) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise MarketDataError("NSE quote is missing its market timestamp")

    value = value.strip()

    for fmt in (
        "%d-%b-%Y %H:%M:%S",
        "%d-%b-%Y %H:%M",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            local_time = datetime.strptime(value, fmt).replace(tzinfo=INDIA_TZ)
            return local_time.astimezone(timezone.utc)
        except ValueError:
            continue

    raise MarketDataError(f"Unrecognized NSE quote timestamp: {value}")


class NSEProvider:
    """Retrieve NSE daily history and latest available exchange quotes."""

    def __init__(self, cache_dir: str | Path = CACHE_DIR):
        self.cache_dir = Path(cache_dir)

    def get_history(
        self,
        symbol: str,
        start_date: date,
        end_date: Optional[date] = None,
        currency: Optional[str] = None,
        series: str = "EQ",
    ) -> list[PriceBar]:
        symbol = _validate_symbol(symbol)
        series = _validate_series(series)

        if not isinstance(start_date, date):
            raise ValueError("start_date must be a date")

        if end_date is not None and end_date < start_date:
            raise ValueError("end_date must not precede start_date")

        if currency is not None and currency.strip().upper() != "INR":
            raise ValueError("NSE prices must use INR")

        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

            with NSE(download_folder=self.cache_dir) as nse:
                rows = nse.fetch_equity_historical_data(
                    symbol,
                    from_date=start_date,
                    to_date=end_date or date.today(),
                    series=series.lower(),
                )
        except Exception as exc:
            raise MarketDataError(
                f"NSE history request failed for {symbol} ({series})"
            ) from exc

        if not isinstance(rows, list):
            raise MarketDataError("NSE history response has an unexpected format")

        bars_by_date = {}

        for row in rows:
            if not isinstance(row, dict):
                continue

            # NSE responses can use either capitalization.
            raw_date = row.get("mTIMESTAMP") or row.get("mtimestamp")
            bar_date = _parse_date(raw_date)

            if bar_date < start_date or (end_date and bar_date > end_date):
                continue

            close = _decimal(row.get("chClosingPrice"))

            if close is None:
                continue

            bars_by_date[bar_date] = PriceBar(
                price_date=bar_date,
                close=close,
                currency="INR",
                open=_decimal(row.get("chOpeningPrice")),
                high=_decimal(row.get("chTradeHighPrice")),
                low=_decimal(row.get("chTradeLowPrice")),
            )

        return [bars_by_date[day] for day in sorted(bars_by_date)]

    def get_latest_quote(
        self,
        symbol: str,
        currency: Optional[str] = None,
        series: str = "EQ",
    ) -> MarketQuote:
        symbol = _validate_symbol(symbol)
        series = _validate_series(series)

        if currency is not None and currency.strip().upper() != "INR":
            raise ValueError("NSE prices must use INR")

        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

            with NSE(download_folder=self.cache_dir) as nse:
                payload = nse.quote(symbol, series=series)
        except Exception as exc:
            raise MarketDataError(
                f"NSE quote request failed for {symbol} ({series})"
            ) from exc

        if not isinstance(payload, dict):
            raise MarketDataError("NSE quote response has an unexpected format")

        order_book = payload.get("orderBook") or {}
        metadata = payload.get("metaData") or {}

        if not isinstance(order_book, dict) or not isinstance(metadata, dict):
            raise MarketDataError("NSE quote metadata has an unexpected format")

        price = _decimal(order_book.get("lastPrice"))

        if price is None:
            raise MarketDataError(
                f"NSE returned no valid last traded price for {symbol}"
            )

        return MarketQuote(
            price=price,
            quote_time=_parse_quote_time(payload.get("lastUpdateTime")),
            currency="INR",
            open=_decimal(metadata.get("open")),
            high=_decimal(metadata.get("dayHigh")),
            low=_decimal(metadata.get("dayLow")),
            previous_close=_decimal(metadata.get("previousClose")),
        )
