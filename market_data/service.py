"""Provider selection and market-data refresh orchestration."""

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from market_data.errors import MarketDataError
from market_data.models import MarketQuote
from market_data.providers.mfapi_provider import MFapiProvider
from market_data.providers.yfinance_provider import YahooFinanceProvider
from market_data.storage import MarketDataStorage

logger = logging.getLogger(__name__)

RefreshStatus = Literal["success", "no_data", "failed"]


@dataclass(frozen=True)
class RefreshResult:
    """Refresh outcome; records_written counts records submitted for upsert."""

    security_id: int
    operation: str
    status: RefreshStatus
    records_written: int = 0
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == "success"


class MarketDataService:
    """Refresh market data without coupling callers to a specific provider."""

    def __init__(
        self,
        storage: MarketDataStorage,
        yahoo_provider=None,
        mfapi_provider=None,
    ):
        self.storage = storage
        self.yahoo = yahoo_provider or YahooFinanceProvider()
        self.mfapi = mfapi_provider or MFapiProvider()

    @staticmethod
    def _identifier(security: dict) -> str:
        instrument_type = str(security.get("instrument_type") or "").upper()
        symbol = security.get("symbol")

        if instrument_type in ("STOCK", "ETF"):
            identifier = security.get("broker_symbol") or symbol
            if not isinstance(identifier, str) or not identifier.strip():
                raise ValueError("Missing Yahoo Finance ticker")
            return identifier.strip()

        if instrument_type == "MUTUAL_FUND":
            if symbol is None or not str(symbol).strip().isdigit():
                raise ValueError("Missing or invalid MFapi scheme code")
            return str(symbol).strip()

        raise ValueError(
            f"Unsupported instrument type: {instrument_type or 'UNKNOWN'}"
        )

    def refresh_history(
        self,
        security: dict,
        start_date: date,
        end_date: date | None = None,
    ) -> int:
        """Fetch and store history; return the number of records submitted for upsert."""
        security_id = int(security["security_id"])
        instrument_type = str(security.get("instrument_type") or "").upper()
        identifier = self._identifier(security)

        if instrument_type in ("STOCK", "ETF"):
            currency = str(security.get("currency") or "").strip().upper()
            if len(currency) != 3:
                raise ValueError("Security currency must be configured")
            bars = self.yahoo.get_history(
                identifier, start_date, end_date, currency=currency
            )
        else:
            bars = self.mfapi.get_history(identifier, start_date, end_date)

        if not bars:
            logger.info(
                "No historical prices returned for security_id=%s",
                security_id,
            )
            return 0

        return self.storage.save_history(security_id, bars)

    def refresh_history_result(
        self,
        security: dict,
        start_date: date,
        end_date: date | None = None,
    ) -> RefreshResult:
        """Refresh history and return an explicit per-security outcome."""
        try:
            security_id = int(security["security_id"])
            count = self.refresh_history(security, start_date, end_date)
            return RefreshResult(
                security_id=security_id,
                operation="history",
                status="success" if count else "no_data",
                records_written=count,
            )
        except Exception as exc:
            security_id = _safe_security_id(security)
            logger.warning(
                "Market-data history refresh failed for security_id=%s: %s",
                security_id,
                exc,
            )
            return RefreshResult(
                security_id=security_id,
                operation="history",
                status="failed",
                error=str(exc),
            )

    def _refresh_quote_result(self, security: dict) -> RefreshResult:
        security_id = _safe_security_id(security)

        try:
            if security_id <= 0:
                raise ValueError("security_id must be positive")

            instrument_type = str(
                security.get("instrument_type") or ""
            ).upper()
            identifier = self._identifier(security)

            if instrument_type in ("STOCK", "ETF"):
                currency = str(
                    security.get("currency") or ""
                ).strip().upper()
                if len(currency) != 3:
                    raise ValueError("Security currency must be configured")
                quote = self.yahoo.get_latest_quote(
                    identifier, currency=currency
                )
            elif instrument_type == "MUTUAL_FUND":
                nav = self.mfapi.get_latest_nav(identifier)
                # This is the NAV's published valuation date, not fetch time.
                quote = MarketQuote(
                    price=nav.close,
                    quote_time=datetime.combine(
                        nav.price_date,
                        time.min,
                        tzinfo=timezone.utc,
                    ),
                    currency=nav.currency,
                )
            else:
                raise ValueError(
                    f"Unsupported instrument type: "
                    f"{instrument_type or 'UNKNOWN'}"
                )

            self.storage.save_quote(security_id, quote)
            return RefreshResult(
                security_id=security_id,
                operation="quote",
                status="success",
                records_written=1,
            )

        except Exception as exc:
            logger.warning(
                "Market-data quote refresh failed for security_id=%s: %s",
                security_id,
                exc,
            )
            return RefreshResult(
                security_id=security_id,
                operation="quote",
                status="failed",
                error=str(exc),
            )

    def refresh_quote_result(self, security: dict) -> RefreshResult:
        """Refresh a quote and return success or failure details."""
        return self._refresh_quote_result(security)

    def refresh_quote(self, security: dict) -> bool:
        """Backward-compatible boolean result for quote refreshes."""
        return self.refresh_quote_result(security).succeeded

    def refresh_recent_history(
        self,
        security: dict,
        lookback_days: int = 14,
        end_date: date | None = None,
    ) -> int:
        """Refresh a recent history window, including the end date."""
        if lookback_days < 1:
            raise ValueError("lookback_days must be at least 1")
        target_date = end_date or date.today()
        return self.refresh_history(
            security,
            start_date=target_date - timedelta(days=lookback_days - 1),
            end_date=target_date,
        )


def _safe_security_id(security: dict) -> int:
    """Return a usable security ID for reporting even on malformed input."""
    try:
        return int(security.get("security_id", 0))
    except (TypeError, ValueError, AttributeError):
        return 0
