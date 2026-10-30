"""Offline tests for market-data provider selection and orchestration."""

import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

from market_data.models import MarketQuote, PriceBar
from market_data.errors import MarketDataError
from market_data.service import MarketDataService


class MarketDataServiceTests(unittest.TestCase):
    def setUp(self):
        self.storage = MagicMock()
        self.yahoo = MagicMock()
        self.mfapi = MagicMock()
        self.service = MarketDataService(
            storage=self.storage,
            yahoo_provider=self.yahoo,
            mfapi_provider=self.mfapi,
        )

    def test_stock_history_uses_broker_symbol_first(self):
        security = {
            "security_id": 1,
            "instrument_type": "STOCK",
            "symbol": "RELIANCE.NS",
            "broker_symbol": "RELIANCE",
            "currency": "INR",
        }
        self.yahoo.get_history.return_value = [
            PriceBar(date(2026, 10, 27), Decimal("100"), "INR")
        ]
        self.storage.save_history.return_value = 1

        count = self.service.refresh_history(
            security, date(2026, 10, 1), date(2026, 10, 27)
        )

        self.assertEqual(count, 1)
        self.yahoo.get_history.assert_called_once_with(
            "RELIANCE", date(2026, 10, 1), date(2026, 10, 27),
            currency="INR",
        )
        self.mfapi.get_history.assert_not_called()

    def test_stock_history_falls_back_to_security_symbol(self):
        security = {
            "security_id": 2,
            "instrument_type": "ETF",
            "symbol": "AAPL",
            "broker_symbol": None,
            "currency": "USD",
        }
        self.yahoo.get_history.return_value = []

        self.assertEqual(
            self.service.refresh_history(security, date(2026, 1, 1)), 0
        )
        self.yahoo.get_history.assert_called_once_with(
            "AAPL", date(2026, 1, 1), None, currency="USD"
        )

    def test_mutual_fund_uses_numeric_symbol_as_scheme_code(self):
        security = {
            "security_id": 3,
            "instrument_type": "MUTUAL_FUND",
            "symbol": "123456",
            "currency": "INR",
        }
        self.mfapi.get_history.return_value = []

        self.service.refresh_history(security, date(2026, 1, 1))

        self.mfapi.get_history.assert_called_once_with(
            "123456", date(2026, 1, 1), None
        )
        self.yahoo.get_history.assert_not_called()

    def test_missing_stock_symbol_is_rejected(self):
        security = {
            "security_id": 4,
            "instrument_type": "STOCK",
            "symbol": None,
            "broker_symbol": None,
            "currency": "INR",
        }

        with self.assertRaises(ValueError):
            self.service.refresh_history(security, date(2026, 1, 1))

    def test_invalid_mutual_fund_scheme_code_is_rejected(self):
        security = {
            "security_id": 5,
            "instrument_type": "MUTUAL_FUND",
            "symbol": "NOT_A_CODE",
            "currency": "INR",
        }

        with self.assertRaises(ValueError):
            self.service.refresh_history(security, date(2026, 1, 1))

    def test_unsupported_instrument_type_is_rejected(self):
        security = {
            "security_id": 6,
            "instrument_type": "PRECIOUS_METAL",
            "symbol": "GOLD",
            "currency": "INR",
        }

        with self.assertRaises(ValueError):
            self.service.refresh_history(security, date(2026, 1, 1))

    def test_quote_failure_preserves_existing_stored_quote(self):
        security = {
            "security_id": 7,
            "instrument_type": "STOCK",
            "symbol": "AAPL",
            "currency": "USD",
        }
        self.yahoo.get_latest_quote.side_effect = MarketDataError("offline")

        result = self.service.refresh_quote(security)

        self.assertFalse(result)
        self.storage.save_quote.assert_not_called()

    def test_successful_quote_is_saved(self):
        security = {
            "security_id": 8,
            "instrument_type": "STOCK",
            "symbol": "AAPL",
            "currency": "USD",
        }
        quote = MarketQuote(
            price=Decimal("200"),
            quote_time=__import__("datetime").datetime(
                2026, 10, 27, tzinfo=__import__("datetime").timezone.utc
            ),
            currency="USD",
        )
        self.yahoo.get_latest_quote.return_value = quote

        self.assertTrue(self.service.refresh_quote(security))
        self.storage.save_quote.assert_called_once_with(8, quote)

    def test_mutual_fund_quote_uses_nav_date(self):
        security = {
            "security_id": 9,
            "instrument_type": "MUTUAL_FUND",
            "symbol": "123456",
            "currency": "INR",
        }
        nav = PriceBar(date(2026, 10, 27), Decimal("25.75"), "INR")
        self.mfapi.get_latest_nav.return_value = nav

        self.assertTrue(self.service.refresh_quote(security))
        self.mfapi.get_latest_nav.assert_called_once_with("123456")
        saved_quote = self.storage.save_quote.call_args.args[1]
        self.assertEqual(saved_quote.price, Decimal("25.75"))
        self.assertEqual(saved_quote.quote_time.date(), date(2026, 10, 27))


if __name__ == "__main__":
    unittest.main()


class StructuredRefreshResultTests(unittest.TestCase):
    def setUp(self):
        self.storage = MagicMock()
        self.yahoo = MagicMock()
        self.mfapi = MagicMock()
        self.service = MarketDataService(
            storage=self.storage,
            yahoo_provider=self.yahoo,
            mfapi_provider=self.mfapi,
        )
        self.security = {
            "security_id": 20,
            "instrument_type": "STOCK",
            "symbol": "AAPL",
            "currency": "USD",
        }

    def test_history_success_reports_records_written(self):
        self.yahoo.get_history.return_value = [
            PriceBar(date(2026, 10, 27), Decimal("200"), "USD")
        ]
        self.storage.save_history.return_value = 1

        result = self.service.refresh_history_result(
            self.security, date(2026, 10, 1), date(2026, 10, 27)
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.records_written, 1)
        self.assertTrue(result.succeeded)
        self.assertIsNone(result.error)

    def test_empty_history_reports_no_data(self):
        self.yahoo.get_history.return_value = []

        result = self.service.refresh_history_result(
            self.security, date(2026, 10, 1)
        )

        self.assertEqual(result.status, "no_data")
        self.assertEqual(result.records_written, 0)
        self.assertFalse(result.succeeded)

    def test_history_provider_failure_reports_failed(self):
        self.yahoo.get_history.side_effect = MarketDataError("offline")

        result = self.service.refresh_history_result(
            self.security, date(2026, 10, 1)
        )

        self.assertEqual(result.status, "failed")
        self.assertIn("offline", result.error)
        self.storage.save_history.assert_not_called()

    def test_quote_failure_reports_failed(self):
        self.yahoo.get_latest_quote.side_effect = MarketDataError("offline")

        result = self.service.refresh_quote_result(self.security)

        self.assertEqual(result.status, "failed")
        self.assertIn("offline", result.error)
        self.storage.save_quote.assert_not_called()

    def test_invalid_security_id_is_reported_without_raising(self):
        security = {**self.security, "security_id": "not-an-id"}

        result = self.service.refresh_quote_result(security)

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.security_id, 0)
        self.assertIsNotNone(result.error)
        self.storage.save_quote.assert_not_called()
