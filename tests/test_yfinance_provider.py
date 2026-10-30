"""Offline tests for the Yahoo Finance provider."""

import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pandas as pd

from market_data.models import MarketQuote, PriceBar
from market_data.errors import MarketDataError
from market_data.providers.yfinance_provider import (
    MarketDataError,
    YahooFinanceProvider,
    _valid_ticker,
)


class TickerValidationTests(unittest.TestCase):
    def test_accepts_common_tickers(self):
        self.assertEqual(_valid_ticker("RELIANCE.NS"), "RELIANCE.NS")
        self.assertEqual(_valid_ticker("AAPL"), "AAPL")
        self.assertEqual(_valid_ticker("BRK-B"), "BRK-B")

    def test_rejects_blank_or_malformed_tickers(self):
        for value in ("", "  ", "TWO WORDS", "AAPL;DROP", "../AAPL"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    _valid_ticker(value)


class YahooHistoryTests(unittest.TestCase):
    @patch("market_data.providers.yfinance_provider.yf.Ticker")
    def test_history_normalizes_daily_bars(self, ticker_factory):
        ticker = MagicMock()
        ticker_factory.return_value = ticker
        ticker.fast_info = {"currency": "INR"}
        ticker.history.return_value = pd.DataFrame(
            {
                "Open": [100.0, 102.0],
                "High": [105.0, 106.0],
                "Low": [99.0, 101.0],
                "Close": [103.25, 104.50],
            },
            index=pd.to_datetime(["2026-10-26", "2026-10-27"]),
        )

        bars = YahooFinanceProvider().get_history(
            "RELIANCE.NS",
            date(2026, 10, 26),
            date(2026, 10, 27),
        )

        self.assertEqual(len(bars), 2)
        self.assertIsInstance(bars[0], PriceBar)
        self.assertEqual(bars[0].price_date, date(2026, 10, 26))
        self.assertEqual(bars[0].close, Decimal("103.25"))
        self.assertEqual(bars[0].currency, "INR")
        self.assertEqual(bars[1].close, Decimal("104.5"))

        _, kwargs = ticker.history.call_args
        self.assertEqual(kwargs["end"], "2026-10-28")

    @patch("market_data.providers.yfinance_provider.yf.Ticker")
    def test_empty_history_returns_empty_list(self, ticker_factory):
        ticker = MagicMock()
        ticker_factory.return_value = ticker
        ticker.history.return_value = pd.DataFrame()

        result = YahooFinanceProvider().get_history(
            "AAPL",
            date(2026, 10, 1),
            date(2026, 10, 2),
            currency="USD",
        )

        self.assertEqual(result, [])

    @patch("market_data.providers.yfinance_provider.yf.Ticker")
    def test_provider_exception_is_wrapped(self, ticker_factory):
        ticker_factory.return_value.history.side_effect = TimeoutError("offline")

        with self.assertRaises(MarketDataError):
            YahooFinanceProvider().get_history(
                "AAPL",
                date(2026, 10, 1),
                currency="USD",
            )

    def test_rejects_end_date_before_start_date(self):
        with self.assertRaises(ValueError):
            YahooFinanceProvider().get_history(
                "AAPL",
                date(2026, 10, 2),
                date(2026, 10, 1),
                currency="USD",
            )


class YahooQuoteTests(unittest.TestCase):
    @patch("market_data.providers.yfinance_provider.yf.Ticker")
    def test_latest_quote_uses_latest_daily_close(self, ticker_factory):
        ticker = MagicMock()
        ticker_factory.return_value = ticker
        ticker.fast_info = {
            "currency": "USD",
            "previous_close": 198.5,
            "timezone": "America/New_York",
        }
        ticker.history.return_value = pd.DataFrame(
            {
                "Open": [198.0],
                "High": [201.0],
                "Low": [197.0],
                "Close": [200.25],
            },
            index=pd.DatetimeIndex(["2026-10-26"]),
        )

        quote = YahooFinanceProvider().get_latest_quote("AAPL")

        self.assertIsInstance(quote, MarketQuote)
        self.assertEqual(quote.price, Decimal("200.25"))
        self.assertEqual(quote.currency, "USD")
        self.assertEqual(quote.previous_close, Decimal("198.5"))
        self.assertIsNotNone(quote.quote_time.tzinfo)
        self.assertEqual(quote.quote_time, datetime(
            2026, 10, 26, 4, 0, tzinfo=timezone.utc
        ))

    @patch("market_data.providers.yfinance_provider.yf.Ticker")
    def test_empty_quote_history_is_an_error(self, ticker_factory):
        ticker = MagicMock()
        ticker_factory.return_value = ticker
        ticker.history.return_value = pd.DataFrame()

        with self.assertRaises(MarketDataError):
            YahooFinanceProvider().get_latest_quote("AAPL", currency="USD")


    @patch("market_data.providers.yfinance_provider.yf.Ticker")
    def test_quote_survives_previous_close_lookup_failure(self, ticker_factory):
        ticker = MagicMock()
        ticker_factory.return_value = ticker
        class FailingPreviousClose(dict):
            def get(self, key, default=None):
                if key == "previous_close":
                    raise RuntimeError("optional field unavailable")
                return super().get(key, default)

        # The close is valid; only the optional previous-close field fails.
        ticker.fast_info = FailingPreviousClose({
            "currency": "USD",
            "timezone": "America/New_York",
        })
        ticker.history.return_value = pd.DataFrame(
            {"Open": [198.0], "High": [201.0], "Low": [197.0], "Close": [200.25]},
            index=pd.DatetimeIndex(["2026-10-26"]),
        )

        quote = YahooFinanceProvider().get_latest_quote("AAPL")

        self.assertEqual(quote.price, Decimal("200.25"))
        self.assertIsNone(quote.previous_close)


if __name__ == "__main__":
    unittest.main()
