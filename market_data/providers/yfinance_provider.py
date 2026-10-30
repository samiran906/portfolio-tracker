"""Yahoo Finance provider for stock and ETF history and latest quotes."""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional
from zoneinfo import ZoneInfo

import yfinance as yf

from market_data.errors import MarketDataError
from market_data.models import MarketQuote, PriceBar


def _decimal(value) -> Optional[Decimal]:
    """Convert a finite, non-null provider value to Decimal."""
    if value is None:
        return None

    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None

    if not result.is_finite():
        return None

    return result


def _valid_ticker(symbol: str) -> str:
    """Validate a configured Yahoo Finance ticker without guessing suffixes."""
    if not isinstance(symbol, str):
        raise ValueError("Ticker symbol must be a string")

    ticker = symbol.strip()

    if not ticker or len(ticker) > 32:
        raise ValueError("Ticker symbol is empty or too long")

    if any(ch.isspace() for ch in ticker):
        raise ValueError("Ticker symbol must not contain whitespace")

    if not all(ch.isalnum() or ch in ".-^=" for ch in ticker):
        raise ValueError("Ticker symbol contains unsupported characters")

    return ticker


def _market_timezone(ticker) -> timezone:
    """Return the exchange timezone, falling back to UTC if unavailable."""
    try:
        zone_name = ticker.fast_info.get("timezone")
        if zone_name:
            return ZoneInfo(str(zone_name))
    except Exception:
        pass

    return timezone.utc


class YahooFinanceProvider:
    """Retrieve daily bars and the latest available quote using yfinance."""

    def get_history(
        self,
        symbol: str,
        start_date: date,
        end_date: Optional[date] = None,
        currency: Optional[str] = None,
    ) -> list[PriceBar]:
        """Return daily bars for start_date through end_date, inclusive."""
        ticker_symbol = _valid_ticker(symbol)

        if end_date is not None and end_date < start_date:
            raise ValueError("end_date must not precede start_date")

        # Yahoo's end parameter is exclusive.
        exclusive_end = (end_date or date.today()) + timedelta(days=1)

        try:
            ticker = yf.Ticker(ticker_symbol)
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
                f"Yahoo Finance history request failed for {ticker_symbol}"
            ) from exc

        if frame is None or frame.empty:
            return []

        resolved_currency = (currency or "").strip().upper()
        if not resolved_currency:
            try:
                resolved_currency = str(ticker.fast_info.get("currency") or "").upper()
            except Exception:
                resolved_currency = ""

        if len(resolved_currency) != 3:
            raise MarketDataError(
                f"Yahoo Finance did not provide a valid currency for {ticker_symbol}; "
                "pass the security's configured currency explicitly"
            )

        bars = []
        for index, row in frame.iterrows():
            try:
                bar_date = index.date()
            except AttributeError:
                bar_date = date.fromisoformat(str(index)[:10])

            close = _decimal(row.get("Close"))
            if close is None or close <= 0:
                continue

            bars.append(
                PriceBar(
                    price_date=bar_date,
                    close=close,
                    currency=resolved_currency,
                    open=_decimal(row.get("Open")),
                    high=_decimal(row.get("High")),
                    low=_decimal(row.get("Low")),
                )
            )

        return sorted(bars, key=lambda bar: bar.price_date)

    def get_latest_quote(
        self,
        symbol: str,
        currency: Optional[str] = None,
    ) -> MarketQuote:
        """Return the most recent available quote and its market timestamp."""
        ticker_symbol = _valid_ticker(symbol)

        try:
            ticker = yf.Ticker(ticker_symbol)
            fast_info = ticker.fast_info
            history = ticker.history(
                period="5d",
                interval="1d",
                auto_adjust=False,
                actions=False,
                raise_errors=True,
            )
        except Exception as exc:
            raise MarketDataError(
                f"Yahoo Finance quote request failed for {ticker_symbol}"
            ) from exc

        if history is None or history.empty:
            raise MarketDataError(
                f"No recent price data returned for {ticker_symbol}"
            )

        latest_index = history.index[-1]
        latest_row = history.iloc[-1]

        price = _decimal(latest_row.get("Close"))
        if price is None or price <= 0:
            raise MarketDataError(
                f"Latest close is invalid for {ticker_symbol}"
            )

        resolved_currency = (currency or "").strip().upper()
        if not resolved_currency:
            try:
                resolved_currency = str(fast_info.get("currency") or "").upper()
            except Exception:
                resolved_currency = ""

        if len(resolved_currency) != 3:
            raise MarketDataError(
                f"Yahoo Finance did not provide a valid currency for {ticker_symbol}; "
                "pass the security's configured currency explicitly"
            )

        try:
            market_tz = _market_timezone(ticker)
            if latest_index.tzinfo is not None:
                quote_time = latest_index.to_pydatetime().astimezone(timezone.utc)
            else:
                market_date = latest_index.date()
                quote_time = datetime.combine(
                    market_date, time(0, 0), tzinfo=market_tz
                ).astimezone(timezone.utc)
        except Exception as exc:
            raise MarketDataError(
                f"Could not determine quote timestamp for {ticker_symbol}"
            ) from exc

        # previous_close is optional metadata. A provider failure here must
        # not discard an otherwise valid latest daily close.
        try:
            previous_close = _decimal(fast_info.get("previous_close"))
        except Exception:
            previous_close = None

        return MarketQuote(
            price=price,
            quote_time=quote_time,
            currency=resolved_currency,
            open=_decimal(latest_row.get("Open")),
            high=_decimal(latest_row.get("High")),
            low=_decimal(latest_row.get("Low")),
            previous_close=previous_close,
        )
