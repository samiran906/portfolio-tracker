import unittest
from datetime import datetime
from decimal import Decimal

from market_data.models import MarketQuote


class MarketQuoteValidationTests(unittest.TestCase):
    def test_rejects_naive_quote_timestamp(self):
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            MarketQuote(
                price=Decimal("10"),
                quote_time=datetime(2026, 10, 28),
                currency="INR",
            )

    def test_rejects_invalid_optional_price(self):
        with self.assertRaisesRegex(ValueError, "previous_close"):
            MarketQuote(
                price=Decimal("10"),
                quote_time=datetime.fromisoformat("2026-10-28T00:00:00+00:00"),
                currency="INR",
                previous_close=Decimal("0"),
            )


if __name__ == "__main__":
    unittest.main()
