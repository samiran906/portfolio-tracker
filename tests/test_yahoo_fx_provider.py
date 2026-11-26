"""Offline tests for the Yahoo Finance FX provider."""

import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pandas as pd

from market_data.errors import MarketDataError
from market_data.fx_models import FxRateBar
from market_data.providers.yahoo_fx_provider import (
    YahooFinanceFxProvider,
    YAHOO_FX_TICKER,
)


class FxRateBarTests(unittest.TestCase):

    def test_normalizes_currency_codes(self):
        bar = FxRateBar(
            rate_date=date(2026, 11, 25),
            base_currency="usd",
            quote_currency="inr",
            close=Decimal("92.60"),
        )

        self.assertEqual(bar.base_currency, "USD")
        self.assertEqual(bar.quote_currency, "INR")

    def test_rejects_non_positive_rate(self):
        with self.assertRaises(ValueError):
            FxRateBar(
                rate_date=date(2026, 11, 25),
                base_currency="USD",
                quote_currency="INR",
                close=Decimal("0"),
            )

    def test_rejects_identical_currencies(self):
        with self.assertRaises(ValueError):
            FxRateBar(
                rate_date=date(2026, 11, 25),
                base_currency="USD",
                quote_currency="USD",
                close=Decimal("92.60"),
            )


class YahooFinanceFxProviderTests(unittest.TestCase):

    @patch("market_data.providers.yahoo_fx_provider.yf.Ticker")
    def test_history_normalizes_daily_rates(self, ticker_factory):
        ticker = MagicMock()
        ticker_factory.return_value = ticker

        ticker.history.return_value = pd.DataFrame(
            {
                "Open": [92.10, 92.30],
                "High": [92.50, 92.80],
                "Low": [91.90, 92.20],
                "Close": [92.40, 92.60],
            },
            index=pd.to_datetime(["2026-11-24", "2026-11-25"]),
        )

        bars = YahooFinanceFxProvider().get_history(
            date(2026, 11, 24),
            date(2026, 11, 25),
        )

        self.assertEqual(len(bars), 2)
        self.assertIsInstance(bars[0], FxRateBar)
        self.assertEqual(bars[0].rate_date, date(2026, 11, 24))
        self.assertEqual(bars[0].base_currency, "USD")
        self.assertEqual(bars[0].quote_currency, "INR")
        self.assertEqual(bars[0].close, Decimal("92.4"))
        self.assertEqual(bars[1].close, Decimal("92.6"))

        ticker_factory.assert_called_once_with(YAHOO_FX_TICKER)

        _, kwargs = ticker.history.call_args
        self.assertEqual(kwargs["start"], "2026-11-24")
        self.assertEqual(kwargs["end"], "2026-11-26")
        self.assertEqual(kwargs["interval"], "1d")

    @patch("market_data.providers.yahoo_fx_provider.yf.Ticker")
    def test_empty_history_returns_empty_list(self, ticker_factory):
        ticker = MagicMock()
        ticker_factory.return_value = ticker
        ticker.history.return_value = pd.DataFrame()

        result = YahooFinanceFxProvider().get_history(
            date(2026, 11, 24),
            date(2026, 11, 25),
        )

        self.assertEqual(result, [])

    @patch("market_data.providers.yahoo_fx_provider.yf.Ticker")
    def test_provider_exception_is_wrapped(self, ticker_factory):
        ticker_factory.return_value.history.side_effect = TimeoutError("offline")

        with self.assertRaises(MarketDataError):
            YahooFinanceFxProvider().get_history(
                date(2026, 11, 24),
                date(2026, 11, 25),
            )

    def test_rejects_end_date_before_start_date(self):
        with self.assertRaises(ValueError):
            YahooFinanceFxProvider().get_history(
                date(2026, 11, 25),
                date(2026, 11, 24),
            )


if __name__ == "__main__":
    unittest.main()
