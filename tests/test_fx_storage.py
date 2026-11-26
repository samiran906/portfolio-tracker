"""Offline tests for FX rate persistence."""

import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

from market_data.fx_models import FxRateBar
from market_data.fx_storage import FxRateStorage


class FxRateStorageTests(unittest.TestCase):

    def setUp(self):
        self.connection = MagicMock()
        self.cursor = MagicMock()
        self.connection.__enter__.return_value = self.connection
        self.connection.cursor.return_value.__enter__.return_value = self.cursor
        self.storage = FxRateStorage(lambda: self.connection)

    def make_bar(self, day, close="92.60"):
        return FxRateBar(
            rate_date=date.fromisoformat(day),
            base_currency="USD",
            quote_currency="INR",
            open=Decimal("92.30"),
            high=Decimal("92.80"),
            low=Decimal("92.10"),
            close=Decimal(close),
        )

    def test_empty_history_does_not_open_connection(self):
        connection_factory = MagicMock()
        storage = FxRateStorage(connection_factory)

        self.assertEqual(storage.save_history([]), 0)
        connection_factory.assert_not_called()

    def test_history_uses_idempotent_upsert(self):
        bars = [
            self.make_bar("2026-11-24"),
            self.make_bar("2026-11-25"),
        ]

        count = self.storage.save_history(bars)

        self.assertEqual(count, 2)
        self.cursor.executemany.assert_called_once()

        sql, values = self.cursor.executemany.call_args.args

        self.assertIn("INSERT INTO fx_rates", sql)
        self.assertIn(
            "ON CONFLICT (base_currency, quote_currency, rate_date)",
            sql,
        )
        self.assertIn("fetched_at = NOW()", sql)
        self.assertEqual(len(values), 2)
        self.assertEqual(values[0][1:3], ("USD", "INR"))
        self.assertEqual(values[0][6], Decimal("92.60"))
        self.assertEqual(values[0][7], "YAHOO")

    def test_rejects_mixed_currency_pairs(self):
        bars = [
            self.make_bar("2026-11-24"),
            FxRateBar(
                rate_date=date(2026, 11, 25),
                base_currency="EUR",
                quote_currency="INR",
                close=Decimal("107.00"),
            ),
        ]

        with self.assertRaisesRegex(ValueError, "same currency pair"):
            self.storage.save_history(bars)

        self.cursor.executemany.assert_not_called()

    def test_rejects_non_fx_records(self):
        with self.assertRaises(TypeError):
            self.storage.save_history([object()])

        self.cursor.executemany.assert_not_called()

    def test_get_latest_rate_date(self):
        expected = date(2026, 11, 25)
        self.cursor.fetchone.return_value = {
            "latest_rate_date": expected
        }

        result = self.storage.get_latest_rate_date("usd", "inr")

        self.assertEqual(result, expected)
        self.cursor.execute.assert_called_once()

        sql, values = self.cursor.execute.call_args.args
        self.assertIn("MAX(rate_date)", sql)
        self.assertIn("FROM fx_rates", sql)
        self.assertEqual(values, ("USD", "INR"))

    def test_get_latest_rate_date_returns_none_for_empty_table(self):
        self.cursor.fetchone.return_value = {
            "latest_rate_date": None
        }

        self.assertIsNone(
            self.storage.get_latest_rate_date("USD", "INR")
        )

    def test_rejects_invalid_currency_pair(self):
        with self.assertRaises(ValueError):
            self.storage.get_latest_rate_date("USD", "USD")


if __name__ == "__main__":
    unittest.main()
