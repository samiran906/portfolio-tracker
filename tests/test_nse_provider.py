"""Offline tests for the NSE India market-data provider."""

import tempfile
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

from market_data.errors import MarketDataError
from market_data.models import MarketQuote, PriceBar
from market_data.providers.nse_provider import (
    NSEProvider,
    _parse_date,
    _parse_quote_time,
    _validate_series,
    _validate_symbol,
)


class NSEValidationTests(unittest.TestCase):

    def test_accepts_common_symbols(self):
        self.assertEqual(_validate_symbol("RELIANCE"), "RELIANCE")
        self.assertEqual(_validate_symbol("GOLDBEES"), "GOLDBEES")
        self.assertEqual(_validate_symbol("SGBFEB32IV"), "SGBFEB32IV")

    def test_rejects_invalid_symbols(self):
        for symbol in ("", "TWO WORDS", "AAPL;DROP", "../RELIANCE"):
            with self.subTest(symbol=symbol):
                with self.assertRaises(ValueError):
                    _validate_symbol(symbol)

    def test_accepts_supported_series(self):
        self.assertEqual(_validate_series("EQ"), "EQ")
        self.assertEqual(_validate_series("gb"), "GB")

    def test_rejects_unsupported_series(self):
        with self.assertRaises(ValueError):
            _validate_series("BE")

    def test_parses_historical_date(self):
        self.assertEqual(
            _parse_date("27-Oct-2026"),
            date(2026, 10, 27),
        )

    def test_parses_quote_timestamp_as_utc(self):
        result = _parse_quote_time("09-Nov-2026 15:30:00")

        self.assertEqual(
            result,
            datetime(2026, 11, 9, 10, 0, tzinfo=timezone.utc),
        )


class NSEHistoryTests(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.provider = NSEProvider(cache_dir=self.temp_dir.name)

    @patch("market_data.providers.nse_provider.NSE")
    def test_history_normalizes_sgb_records(self, nse_factory):
        client = MagicMock()
        nse_factory.return_value.__enter__.return_value = client

        client.fetch_equity_historical_data.return_value = [
            {
                "mTIMESTAMP": "27-Oct-2026",
                "chOpeningPrice": "100.00",
                "chTradeHighPrice": "105.00",
                "chTradeLowPrice": "99.00",
                "chClosingPrice": "103.25",
            },
            {
                "mTIMESTAMP": "28-Oct-2026",
                "chOpeningPrice": "103.00",
                "chTradeHighPrice": "107.00",
                "chTradeLowPrice": "102.00",
                "chClosingPrice": "106.50",
            },
        ]

        bars = self.provider.get_history(
            "SGBFEB32IV",
            date(2026, 10, 27),
            date(2026, 10, 28),
            currency="INR",
            series="GB",
        )

        self.assertEqual(len(bars), 2)
        self.assertIsInstance(bars[0], PriceBar)
        self.assertEqual(bars[0].price_date, date(2026, 10, 27))
        self.assertEqual(bars[0].close, Decimal("103.25"))
        self.assertEqual(bars[0].open, Decimal("100.00"))
        self.assertEqual(bars[0].high, Decimal("105.00"))
        self.assertEqual(bars[0].low, Decimal("99.00"))
        self.assertEqual(bars[0].currency, "INR")

        client.fetch_equity_historical_data.assert_called_once_with(
            "SGBFEB32IV",
            from_date=date(2026, 10, 27),
            to_date=date(2026, 10, 28),
            series="gb",
        )

    @patch("market_data.providers.nse_provider.NSE")
    def test_history_filters_records_outside_requested_dates(self, nse_factory):
        client = MagicMock()
        nse_factory.return_value.__enter__.return_value = client

        client.fetch_equity_historical_data.return_value = [
            {
                "mTIMESTAMP": "26-Oct-2026",
                "chClosingPrice": "100",
            },
            {
                "mTIMESTAMP": "27-Oct-2026",
                "chClosingPrice": "101",
            },
            {
                "mTIMESTAMP": "28-Oct-2026",
                "chClosingPrice": "102",
            },
        ]

        bars = self.provider.get_history(
            "RELIANCE",
            date(2026, 10, 27),
            date(2026, 10, 27),
        )

        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0].price_date, date(2026, 10, 27))

    @patch("market_data.providers.nse_provider.NSE")
    def test_history_skips_invalid_closing_prices(self, nse_factory):
        client = MagicMock()
        nse_factory.return_value.__enter__.return_value = client

        client.fetch_equity_historical_data.return_value = [
            {
                "mTIMESTAMP": "27-Oct-2026",
                "chClosingPrice": "0",
            },
            {
                "mTIMESTAMP": "28-Oct-2026",
                "chClosingPrice": "105.50",
            },
        ]

        bars = self.provider.get_history(
            "GOLDBEES",
            date(2026, 10, 27),
            date(2026, 10, 28),
        )

        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0].close, Decimal("105.50"))

    @patch("market_data.providers.nse_provider.NSE")
    def test_empty_history_returns_empty_list(self, nse_factory):
        client = MagicMock()
        nse_factory.return_value.__enter__.return_value = client
        client.fetch_equity_historical_data.return_value = []

        bars = self.provider.get_history(
            "RELIANCE",
            date(2026, 10, 27),
        )

        self.assertEqual(bars, [])

    @patch("market_data.providers.nse_provider.NSE")
    def test_history_api_failure_is_wrapped(self, nse_factory):
        client = MagicMock()
        nse_factory.return_value.__enter__.return_value = client
        client.fetch_equity_historical_data.side_effect = TimeoutError("offline")

        with self.assertRaises(MarketDataError):
            self.provider.get_history(
                "RELIANCE",
                date(2026, 10, 27),
            )

    def test_rejects_end_date_before_start_date(self):
        with self.assertRaises(ValueError):
            self.provider.get_history(
                "RELIANCE",
                date(2026, 10, 28),
                date(2026, 10, 27),
            )

    def test_rejects_non_inr_currency(self):
        with self.assertRaises(ValueError):
            self.provider.get_history(
                "RELIANCE",
                date(2026, 10, 27),
                currency="USD",
            )


class NSEQuoteTests(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.provider = NSEProvider(cache_dir=self.temp_dir.name)

    @patch("market_data.providers.nse_provider.NSE")
    def test_latest_quote_uses_order_book_last_price(self, nse_factory):
        client = MagicMock()
        nse_factory.return_value.__enter__.return_value = client

        client.quote.return_value = {
            "orderBook": {
                "lastPrice": "2500.75",
            },
            "metaData": {
                "lastPrice": "9999.99",
                "open": "2480.00",
                "dayHigh": "2510.00",
                "dayLow": "2475.00",
                "previousClose": "2490.00",
            },
            "lastUpdateTime": "09-Nov-2026 15:30:00",
        }

        quote = self.provider.get_latest_quote(
            "RELIANCE",
            currency="INR",
            series="EQ",
        )

        self.assertIsInstance(quote, MarketQuote)
        self.assertEqual(quote.price, Decimal("2500.75"))
        self.assertEqual(quote.currency, "INR")
        self.assertEqual(quote.open, Decimal("2480.00"))
        self.assertEqual(quote.high, Decimal("2510.00"))
        self.assertEqual(quote.low, Decimal("2475.00"))
        self.assertEqual(quote.previous_close, Decimal("2490.00"))
        self.assertEqual(
            quote.quote_time,
            datetime(2026, 11, 9, 10, 0, tzinfo=timezone.utc),
        )

        client.quote.assert_called_once_with("RELIANCE", series="EQ")

    @patch("market_data.providers.nse_provider.NSE")
    def test_sgb_quote_uses_gb_series(self, nse_factory):
        client = MagicMock()
        nse_factory.return_value.__enter__.return_value = client

        client.quote.return_value = {
            "orderBook": {"lastPrice": "12500.00"},
            "metaData": {
                "open": "12450.00",
                "dayHigh": "12550.00",
                "dayLow": "12400.00",
                "previousClose": "12425.00",
            },
            "lastUpdateTime": "09-Nov-2026 15:30:00",
        }

        quote = self.provider.get_latest_quote(
            "SGBFEB32IV",
            currency="INR",
            series="GB",
        )

        self.assertEqual(quote.price, Decimal("12500.00"))
        client.quote.assert_called_once_with("SGBFEB32IV", series="GB")

    @patch("market_data.providers.nse_provider.NSE")
    def test_missing_last_price_is_an_error(self, nse_factory):
        client = MagicMock()
        nse_factory.return_value.__enter__.return_value = client

        client.quote.return_value = {
            "orderBook": {"lastPrice": None},
            "metaData": {"lastPrice": "100.00"},
            "lastUpdateTime": "09-Nov-2026 15:30:00",
        }

        with self.assertRaises(MarketDataError):
            self.provider.get_latest_quote("RELIANCE")

    @patch("market_data.providers.nse_provider.NSE")
    def test_missing_timestamp_is_an_error(self, nse_factory):
        client = MagicMock()
        nse_factory.return_value.__enter__.return_value = client

        client.quote.return_value = {
            "orderBook": {"lastPrice": "100.00"},
            "metaData": {},
        }

        with self.assertRaises(MarketDataError):
            self.provider.get_latest_quote("RELIANCE")

    @patch("market_data.providers.nse_provider.NSE")
    def test_quote_api_failure_is_wrapped(self, nse_factory):
        client = MagicMock()
        nse_factory.return_value.__enter__.return_value = client
        client.quote.side_effect = TimeoutError("offline")

        with self.assertRaises(MarketDataError):
            self.provider.get_latest_quote("RELIANCE")

    def test_rejects_non_inr_currency(self):
        with self.assertRaises(ValueError):
            self.provider.get_latest_quote(
                "RELIANCE",
                currency="USD",
            )


if __name__ == "__main__":
    unittest.main()
