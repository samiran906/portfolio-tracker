"""Offline tests for market-data persistence."""

import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

from market_data.models import MarketQuote, PriceBar
from market_data.storage import MarketDataStorage


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.connection = MagicMock()
        self.cursor = MagicMock()
        self.connection.__enter__.return_value = self.connection
        self.connection.cursor.return_value.__enter__.return_value = self.cursor
        self.storage = MarketDataStorage(lambda: self.connection)

    def test_empty_history_does_not_open_database_connection(self):
        connection_factory = MagicMock()
        storage = MarketDataStorage(connection_factory)

        self.assertEqual(storage.save_history(1, []), 0)
        connection_factory.assert_not_called()

    def test_history_uses_idempotent_upsert(self):
        bars = [
            PriceBar(
                price_date=date(2026, 10, 26),
                close=Decimal("123.45"),
                currency="INR",
            ),
            PriceBar(
                price_date=date(2026, 10, 27),
                close=Decimal("124.50"),
                currency="INR",
            ),
        ]

        count = self.storage.save_history(7, bars)

        self.assertEqual(count, 2)
        self.cursor.executemany.assert_called_once()
        sql, values = self.cursor.executemany.call_args.args
        self.assertIn("ON CONFLICT (security_id, price_date)", sql)
        self.assertEqual(len(values), 2)
        self.assertEqual(values[0][0], 7)
        self.assertEqual(values[0][1], date(2026, 10, 26))

    def test_quote_upsert_does_not_write_daily_history(self):
        quote = MarketQuote(
            price=Decimal("200.25"),
            quote_time=datetime(2026, 10, 27, 14, 0, tzinfo=timezone.utc),
            currency="USD",
            previous_close=Decimal("198.50"),
        )

        self.storage.save_quote(9, quote)

        self.cursor.execute.assert_called_once()
        sql, values = self.cursor.execute.call_args.args
        self.assertIn("ON CONFLICT (security_id)", sql)
        self.assertIn("quote_time", sql)
        self.assertIn("updated_at = NOW()", sql)
        self.assertNotIn("security_prices", sql)
        self.assertEqual(values[0], 9)
        self.assertEqual(values[1], Decimal("200.25"))

    def test_rejects_invalid_security_id(self):
        with self.assertRaises(ValueError):
            self.storage.save_history(0, [])

        quote = MarketQuote(
            price=Decimal("10"),
            quote_time=datetime(2026, 10, 27, tzinfo=timezone.utc),
            currency="INR",
        )
        with self.assertRaises(ValueError):
            self.storage.save_quote(-1, quote)


if __name__ == "__main__":
    unittest.main()
