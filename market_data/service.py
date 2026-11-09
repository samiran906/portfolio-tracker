"""Account-aware provider selection and market-data refresh orchestration."""

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from market_data.errors import MarketDataError
from market_data.models import MarketQuote
from market_data.providers.mfapi_provider import MFapiProvider
from market_data.providers.nse_provider import NSEProvider
from market_data.providers.yfinance_provider import YahooFinanceProvider
from market_data.storage import MarketDataStorage

logger = logging.getLogger(__name__)

RefreshStatus = Literal["success", "no_data", "failed"]

ZERODHA = "zerodha"
INDMONEY = "indmoney"
PAYTM_MONEY = "paytm money"


@dataclass(frozen=True)
class RefreshResult:
    """Refresh outcome, including the provider used."""

    security_id: int
    operation: str
    status: RefreshStatus
    records_written: int = 0
    error: str | None = None
    provider: str | None = None
    fallback_reason: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == "success"


class MarketDataService:
    """Refresh market data using the provider assigned to each account."""

    def __init__(
        self,
        storage: MarketDataStorage,
        yahoo_provider=None,
        mfapi_provider=None,
        nse_provider=None,
    ):
        self.storage = storage
        self.yahoo = yahoo_provider or YahooFinanceProvider()
        self.mfapi = mfapi_provider or MFapiProvider()
        self.nse = nse_provider or NSEProvider()

    @staticmethod
    def _account_name(security: dict) -> str:
        name = str(security.get("account_name") or "").strip().casefold()
        if not name:
            raise ValueError("Missing portfolio account name")
        return name

    @staticmethod
    def _instrument_type(security: dict) -> str:
        return str(security.get("instrument_type") or "").strip().upper()

    @staticmethod
    def _currency(security: dict) -> str:
        currency = str(security.get("currency") or "").strip().upper()
        if len(currency) != 3:
            raise ValueError("Security currency must be configured")
        return currency

    @staticmethod
    def _symbol(value, description: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Missing {description}")
        return value.strip()

    @staticmethod
    def _nse_series(symbol: str) -> str:
        return "GB" if symbol.upper().startswith("SGB") else "EQ"

    def _provider_route(self, security: dict) -> dict:
        """Validate the account/instrument combination and resolve identifiers."""
        account = self._account_name(security)
        instrument = self._instrument_type(security)
        symbol = security.get("symbol")
        broker_symbol = security.get("broker_symbol")

        if account == ZERODHA:
            if instrument not in {"STOCK", "ETF"}:
                raise ValueError(
                    f"Zerodha market-data refresh does not support {instrument}"
                )

            nse_symbol = self._symbol(
                broker_symbol or symbol, "Zerodha NSE symbol"
            )
            yahoo_symbol = self._symbol(
                symbol, "Yahoo Finance fallback ticker"
            )

            return {
                "provider": "NSE",
                "nse_symbol": nse_symbol,
                "yahoo_symbol": yahoo_symbol,
                "series": self._nse_series(nse_symbol),
                "currency": self._currency(security),
            }

        if account == INDMONEY:
            if instrument not in {"STOCK", "ETF"}:
                raise ValueError(
                    f"INDmoney market-data refresh does not support {instrument}"
                )

            return {
                "provider": "Yahoo Finance",
                "yahoo_symbol": self._symbol(
                    broker_symbol or symbol, "Yahoo Finance ticker"
                ),
                "currency": self._currency(security),
            }

        if account == PAYTM_MONEY:
            if instrument != "MUTUAL_FUND":
                raise ValueError(
                    f"Paytm Money market-data refresh does not support {instrument}"
                )

            if symbol is None or not str(symbol).strip().isdigit():
                raise ValueError("Missing or invalid MFapi scheme code")

            return {
                "provider": "MFapi",
                "scheme_code": str(symbol).strip(),
            }

        raise ValueError(
            f"Unsupported market-data account: {security.get('account_name')!r}"
        )

    def _fetch_history(self, security, start_date, end_date):
        route = self._provider_route(security)

        if route["provider"] == "MFapi":
            bars = self.mfapi.get_history(
                route["scheme_code"], start_date, end_date
            )
            return bars, "MFapi", None

        if route["provider"] == "Yahoo Finance":
            bars = self.yahoo.get_history(
                route["yahoo_symbol"],
                start_date,
                end_date,
                currency=route["currency"],
            )
            return bars, "Yahoo Finance", None

        nse_error = None

        try:
            bars = self.nse.get_history(
                route["nse_symbol"],
                start_date,
                end_date,
                currency=route["currency"],
                series=route["series"],
            )
            if bars:
                return bars, "NSE", None
            nse_error = "NSE returned no historical data"
        except Exception as exc:
            nse_error = str(exc)

        try:
            bars = self.yahoo.get_history(
                route["yahoo_symbol"],
                start_date,
                end_date,
                currency=route["currency"],
            )
            return bars, "Yahoo Finance", nse_error
        except Exception as exc:
            raise MarketDataError(
                f"NSE failed: {nse_error}; Yahoo Finance fallback failed: {exc}"
            ) from exc

    def refresh_history(
        self,
        security: dict,
        start_date: date,
        end_date: date | None = None,
    ) -> int:
        """Fetch and store history; return records submitted for upsert."""
        security_id = int(security["security_id"])
        bars, _, _ = self._fetch_history(security, start_date, end_date)

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
        """Refresh history and return provider and fallback details."""
        security_id = _safe_security_id(security)

        try:
            if security_id <= 0:
                raise ValueError("security_id must be positive")

            bars, provider, fallback_reason = self._fetch_history(
                security, start_date, end_date
            )
            count = (
                self.storage.save_history(security_id, bars)
                if bars else 0
            )

            return RefreshResult(
                security_id=security_id,
                operation="history",
                status="success" if count else "no_data",
                records_written=count,
                provider=provider,
                fallback_reason=fallback_reason,
            )

        except Exception as exc:
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

    def _fetch_quote(self, security):
        route = self._provider_route(security)

        if route["provider"] == "MFapi":
            nav = self.mfapi.get_latest_nav(route["scheme_code"])
            quote = MarketQuote(
                price=nav.close,
                quote_time=datetime.combine(
                    nav.price_date, time.min, tzinfo=timezone.utc
                ),
                currency=nav.currency,
            )
            return quote, "MFapi", None

        if route["provider"] == "Yahoo Finance":
            quote = self.yahoo.get_latest_quote(
                route["yahoo_symbol"],
                currency=route["currency"],
            )
            return quote, "Yahoo Finance", None

        nse_error = None

        try:
            quote = self.nse.get_latest_quote(
                route["nse_symbol"],
                currency=route["currency"],
                series=route["series"],
            )
            return quote, "NSE", None
        except Exception as exc:
            nse_error = str(exc)

        try:
            quote = self.yahoo.get_latest_quote(
                route["yahoo_symbol"],
                currency=route["currency"],
            )
            return quote, "Yahoo Finance", nse_error
        except Exception as exc:
            raise MarketDataError(
                f"NSE failed: {nse_error}; Yahoo Finance fallback failed: {exc}"
            ) from exc

    def refresh_quote_result(self, security: dict) -> RefreshResult:
        """Refresh a quote without overwriting stored data on provider failure."""
        security_id = _safe_security_id(security)

        try:
            if security_id <= 0:
                raise ValueError("security_id must be positive")

            quote, provider, fallback_reason = self._fetch_quote(security)
            self.storage.save_quote(security_id, quote)

            return RefreshResult(
                security_id=security_id,
                operation="quote",
                status="success",
                records_written=1,
                provider=provider,
                fallback_reason=fallback_reason,
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
    """Return a usable security ID for reporting malformed input."""
    try:
        return int(security.get("security_id", 0))
    except (TypeError, ValueError, AttributeError):
        return 0
