"""Offline tests for account-aware market-data provider selection."""

import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

from market_data.errors import MarketDataError
from market_data.models import MarketQuote, PriceBar
from market_data.service import MarketDataService


class MarketDataServiceTests(unittest.TestCase):
    def setUp(self):
        self.storage = MagicMock()
        self.yahoo = MagicMock()
        self.mfapi = MagicMock()
        self.nse = MagicMock()

        self.service = MarketDataService(
            storage=self.storage,
            yahoo_provider=self.yahoo,
            mfapi_provider=self.mfapi,
            nse_provider=self.nse,
        )

    def zerodha_security(self, **overrides):
        security = {
            "security_id": 1,
            "account_name": "Zerodha",
            "instrument_type": "STOCK",
            "symbol": "RELIANCE.NS",
            "broker_symbol": "RELIANCE",
            "currency": "INR",
        }
        security.update(overrides)
        return security

    def indmoney_security(self, **overrides):
        security = {
            "security_id": 2,
            "account_name": "INDmoney",
            "instrument_type": "STOCK",
            "symbol": "AAPL",
            "broker_symbol": "AAPL",
            "currency": "USD",
        }
        security.update(overrides)
        return security

    def paytm_security(self, **overrides):
        security = {
            "security_id": 3,
            "account_name": "Paytm Money",
            "instrument_type": "MUTUAL_FUND",
            "symbol": "123456",
            "broker_symbol": None,
            "currency": "INR",
        }
        security.update(overrides)
        return security

    def sample_bar(self, currency="INR"):
        return PriceBar(
            date(2026, 10, 27),
            Decimal("100"),
            currency,
        )

    def sample_quote(self, currency="INR"):
        return MarketQuote(
            price=Decimal("100"),
            quote_time=datetime(2026, 10, 27, tzinfo=timezone.utc),
            currency=currency,
        )

    # ---------------------------------------------------------
    # Zerodha: NSE primary provider
    # ---------------------------------------------------------

    def test_zerodha_history_uses_nse_first(self):
        security = self.zerodha_security()
        self.nse.get_history.return_value = [self.sample_bar()]
        self.storage.save_history.return_value = 1

        result = self.service.refresh_history_result(
            security, date(2026, 10, 1), date(2026, 10, 27)
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.provider, "NSE")
        self.assertEqual(result.records_written, 1)

        self.nse.get_history.assert_called_once_with(
            "RELIANCE",
            date(2026, 10, 1),
            date(2026, 10, 27),
            currency="INR",
            series="EQ",
        )
        self.yahoo.get_history.assert_not_called()
        self.mfapi.get_history.assert_not_called()

    def test_zerodha_sgb_history_uses_gb_series(self):
        security = self.zerodha_security(
            symbol="SGBFEB32IV",
            broker_symbol="SGBFEB32IV",
        )
        self.nse.get_history.return_value = [self.sample_bar()]

        result = self.service.refresh_history_result(
            security, date(2026, 10, 1)
        )

        self.assertEqual(result.provider, "NSE")
        self.nse.get_history.assert_called_once_with(
            "SGBFEB32IV",
            date(2026, 10, 1),
            None,
            currency="INR",
            series="GB",
        )
        self.yahoo.get_history.assert_not_called()

    def test_zerodha_history_falls_back_to_yahoo_when_nse_returns_no_data(self):
        security = self.zerodha_security()
        self.nse.get_history.return_value = []
        self.yahoo.get_history.return_value = [self.sample_bar()]
        self.storage.save_history.return_value = 1

        result = self.service.refresh_history_result(
            security, date(2026, 10, 1)
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.provider, "Yahoo Finance")
        self.assertIn("no historical data", result.fallback_reason)

        self.yahoo.get_history.assert_called_once_with(
            "RELIANCE.NS",
            date(2026, 10, 1),
            None,
            currency="INR",
        )

    def test_zerodha_history_falls_back_to_yahoo_when_nse_fails(self):
        security = self.zerodha_security()
        self.nse.get_history.side_effect = MarketDataError("NSE offline")
        self.yahoo.get_history.return_value = [self.sample_bar()]
        self.storage.save_history.return_value = 1

        result = self.service.refresh_history_result(
            security, date(2026, 10, 1)
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.provider, "Yahoo Finance")
        self.assertIn("NSE offline", result.fallback_reason)

    def test_zerodha_history_uses_security_symbol_for_yahoo_fallback(self):
        security = self.zerodha_security(
            symbol="RELIANCE.NS",
            broker_symbol="RELIANCE",
        )
        self.nse.get_history.return_value = []
        self.yahoo.get_history.return_value = [self.sample_bar()]

        self.service.refresh_history_result(security, date(2026, 10, 1))

        args = self.yahoo.get_history.call_args
        self.assertEqual(args.args[0], "RELIANCE.NS")

    def test_zerodha_history_reports_failure_when_both_providers_fail(self):
        security = self.zerodha_security()
        self.nse.get_history.side_effect = MarketDataError("NSE offline")
        self.yahoo.get_history.side_effect = MarketDataError("Yahoo offline")

        result = self.service.refresh_history_result(
            security, date(2026, 10, 1)
        )

        self.assertEqual(result.status, "failed")
        self.assertIn("NSE offline", result.error)
        self.assertIn("Yahoo Finance fallback failed", result.error)
        self.assertIn("Yahoo offline", result.error)
        self.storage.save_history.assert_not_called()

    def test_zerodha_quote_uses_nse_first(self):
        security = self.zerodha_security()
        quote = self.sample_quote()
        self.nse.get_latest_quote.return_value = quote

        result = self.service.refresh_quote_result(security)

        self.assertEqual(result.status, "success")
        self.assertEqual(result.provider, "NSE")
        self.storage.save_quote.assert_called_once_with(1, quote)
        self.yahoo.get_latest_quote.assert_not_called()

    def test_zerodha_quote_falls_back_to_yahoo_when_nse_fails(self):
        security = self.zerodha_security()
        quote = self.sample_quote()

        self.nse.get_latest_quote.side_effect = MarketDataError("NSE offline")
        self.yahoo.get_latest_quote.return_value = quote

        result = self.service.refresh_quote_result(security)

        self.assertEqual(result.status, "success")
        self.assertEqual(result.provider, "Yahoo Finance")
        self.assertIn("NSE offline", result.fallback_reason)
        self.storage.save_quote.assert_called_once_with(1, quote)

    def test_zerodha_quote_failure_preserves_existing_quote(self):
        security = self.zerodha_security()
        self.nse.get_latest_quote.side_effect = MarketDataError("NSE offline")
        self.yahoo.get_latest_quote.side_effect = MarketDataError("Yahoo offline")

        result = self.service.refresh_quote_result(security)

        self.assertEqual(result.status, "failed")
        self.storage.save_quote.assert_not_called()

    # ---------------------------------------------------------
    # INDmoney: Yahoo Finance only
    # ---------------------------------------------------------

    def test_indmoney_history_uses_yahoo_only(self):
        security = self.indmoney_security()
        self.yahoo.get_history.return_value = [self.sample_bar("USD")]
        self.storage.save_history.return_value = 1

        result = self.service.refresh_history_result(
            security, date(2026, 10, 1)
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.provider, "Yahoo Finance")

        self.yahoo.get_history.assert_called_once_with(
            "AAPL",
            date(2026, 10, 1),
            None,
            currency="USD",
        )
        self.nse.get_history.assert_not_called()
        self.mfapi.get_history.assert_not_called()

    def test_indmoney_uses_broker_symbol_before_security_symbol(self):
        security = self.indmoney_security(
            symbol="APPLE",
            broker_symbol="AAPL",
        )
        self.yahoo.get_history.return_value = []

        self.service.refresh_history_result(security, date(2026, 10, 1))

        self.assertEqual(
            self.yahoo.get_history.call_args.args[0],
            "AAPL",
        )

    def test_indmoney_quote_uses_yahoo_only(self):
        security = self.indmoney_security()
        quote = self.sample_quote("USD")
        self.yahoo.get_latest_quote.return_value = quote

        result = self.service.refresh_quote_result(security)

        self.assertEqual(result.status, "success")
        self.assertEqual(result.provider, "Yahoo Finance")
        self.storage.save_quote.assert_called_once_with(2, quote)
        self.nse.get_latest_quote.assert_not_called()

    # ---------------------------------------------------------
    # Paytm Money: MFapi only
    # ---------------------------------------------------------

    def test_paytm_mutual_fund_history_uses_mfapi(self):
        security = self.paytm_security()
        self.mfapi.get_history.return_value = [self.sample_bar()]
        self.storage.save_history.return_value = 1

        result = self.service.refresh_history_result(
            security, date(2026, 10, 1)
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.provider, "MFapi")
        self.mfapi.get_history.assert_called_once_with(
            "123456", date(2026, 10, 1), None
        )
        self.yahoo.get_history.assert_not_called()
        self.nse.get_history.assert_not_called()

    def test_paytm_mutual_fund_quote_uses_nav_date(self):
        security = self.paytm_security()
        nav = PriceBar(
            date(2026, 10, 27),
            Decimal("25.75"),
            "INR",
        )
        self.mfapi.get_latest_nav.return_value = nav

        result = self.service.refresh_quote_result(security)

        self.assertEqual(result.status, "success")
        self.assertEqual(result.provider, "MFapi")
        self.mfapi.get_latest_nav.assert_called_once_with("123456")

        saved_quote = self.storage.save_quote.call_args.args[1]
        self.assertEqual(saved_quote.price, Decimal("25.75"))
        self.assertEqual(saved_quote.quote_time.date(), date(2026, 10, 27))

    # ---------------------------------------------------------
    # Validation
    # ---------------------------------------------------------

    def test_zerodha_rejects_mutual_fund(self):
        security = self.zerodha_security(instrument_type="MUTUAL_FUND")

        with self.assertRaises(ValueError):
            self.service.refresh_history(security, date(2026, 1, 1))

    def test_indmoney_rejects_mutual_fund(self):
        security = self.indmoney_security(instrument_type="MUTUAL_FUND")

        with self.assertRaises(ValueError):
            self.service.refresh_history(security, date(2026, 1, 1))

    def test_paytm_money_rejects_stock(self):
        security = self.paytm_security(instrument_type="STOCK")

        with self.assertRaises(ValueError):
            self.service.refresh_history(security, date(2026, 1, 1))

    def test_unsupported_account_is_rejected(self):
        security = self.zerodha_security(account_name="Kotak Bank")

        with self.assertRaises(ValueError):
            self.service.refresh_history(security, date(2026, 1, 1))

    def test_missing_account_name_is_rejected(self):
        security = self.zerodha_security(account_name=None)

        with self.assertRaises(ValueError):
            self.service.refresh_history(security, date(2026, 1, 1))

    def test_invalid_mutual_fund_scheme_code_is_rejected(self):
        security = self.paytm_security(symbol="NOT_A_CODE")

        with self.assertRaises(ValueError):
            self.service.refresh_history(security, date(2026, 1, 1))

    def test_missing_currency_is_rejected(self):
        security = self.zerodha_security(currency=None)

        with self.assertRaises(ValueError):
            self.service.refresh_history(security, date(2026, 1, 1))

    def test_missing_zerodha_nse_symbol_is_rejected(self):
        security = self.zerodha_security(
            symbol=None,
            broker_symbol=None,
        )

        with self.assertRaises(ValueError):
            self.service.refresh_history(security, date(2026, 1, 1))


class StructuredRefreshResultTests(unittest.TestCase):
    def setUp(self):
        self.storage = MagicMock()
        self.yahoo = MagicMock()
        self.mfapi = MagicMock()
        self.nse = MagicMock()

        self.service = MarketDataService(
            storage=self.storage,
            yahoo_provider=self.yahoo,
            mfapi_provider=self.mfapi,
            nse_provider=self.nse,
        )

        self.security = {
            "security_id": 20,
            "account_name": "INDmoney",
            "instrument_type": "STOCK",
            "symbol": "AAPL",
            "broker_symbol": "AAPL",
            "currency": "USD",
        }

    def test_history_success_reports_records_written_and_provider(self):
        self.yahoo.get_history.return_value = [
            PriceBar(date(2026, 10, 27), Decimal("200"), "USD")
        ]
        self.storage.save_history.return_value = 1

        result = self.service.refresh_history_result(
            self.security, date(2026, 10, 1), date(2026, 10, 27)
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.records_written, 1)
        self.assertEqual(result.provider, "Yahoo Finance")
        self.assertTrue(result.succeeded)
        self.assertIsNone(result.error)

    def test_empty_history_reports_no_data(self):
        self.yahoo.get_history.return_value = []

        result = self.service.refresh_history_result(
            self.security, date(2026, 10, 1)
        )

        self.assertEqual(result.status, "no_data")
        self.assertEqual(result.records_written, 0)
        self.assertEqual(result.provider, "Yahoo Finance")
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


if __name__ == "__main__":
    unittest.main()