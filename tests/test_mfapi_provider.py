"""Offline tests for the MFapi.in NAV provider."""

import json
import unittest
from datetime import date
from io import BytesIO
from unittest.mock import patch
from urllib.error import URLError

from market_data.models import PriceBar
from market_data.providers.mfapi_provider import MFapiProvider
from market_data.errors import MarketDataError


def fake_response(payload):
    response = BytesIO(json.dumps(payload).encode("utf-8"))
    response.__enter__ = lambda: response
    response.__exit__ = lambda *args: None
    return response


class MFapiProviderTests(unittest.TestCase):
    @patch("market_data.providers.mfapi_provider.urlopen")
    def test_history_normalizes_navs_and_sorts_dates(self, urlopen):
        urlopen.return_value = fake_response({
            "meta": {"scheme_code": 12345},
            "data": [
                {"date": "27-10-2026", "nav": "125.50"},
                {"date": "26-10-2026", "nav": "124.25"},
            ],
        })

        # MFapi dates are conventionally DD-MM-YYYY.
        bars = MFapiProvider().get_history(
            "12345",
            date(2026, 10, 26),
            date(2026, 10, 27),
        )

        self.assertEqual(len(bars), 2)
        self.assertTrue(all(isinstance(bar, PriceBar) for bar in bars))
        self.assertEqual(bars[0].price_date, date(2026, 10, 26))
        self.assertEqual(str(bars[0].close), "124.25")
        self.assertEqual(bars[0].currency, "INR")
        self.assertEqual(bars[1].price_date, date(2026, 10, 27))

    def test_rejects_invalid_scheme_codes(self):
        provider = MFapiProvider()
        for code in ("", "ABC123", "123;DROP", "../123"):
            with self.subTest(code=code):
                with self.assertRaises(ValueError):
                    provider.get_history(code, date(2026, 1, 1))

    @patch("market_data.providers.mfapi_provider.urlopen")
    def test_invalid_nav_raises_market_data_error(self, urlopen):
        urlopen.return_value = fake_response({
            "data": [{"date": "27-10-2026", "nav": "0"}],
        })

        with self.assertRaises(MarketDataError):
            MFapiProvider().get_history(
                "12345",
                date(2026, 10, 1),
            )

    @patch("market_data.providers.mfapi_provider.urlopen")
    def test_network_failure_is_wrapped(self, urlopen):
        urlopen.side_effect = URLError("offline")

        with self.assertRaises(MarketDataError):
            MFapiProvider().get_history(
                "12345",
                date(2026, 10, 1),
            )

    @patch("market_data.providers.mfapi_provider.urlopen")
    def test_latest_nav_uses_dedicated_endpoint(self, urlopen):
        urlopen.return_value = fake_response({
            "meta": {"scheme_code": 12345},
            "data": [{"date": "27-10-2026", "nav": "125.50"}],
            "status": "SUCCESS",
        })

        latest = MFapiProvider().get_latest_nav("12345")

        self.assertEqual(latest.price_date, date(2026, 10, 27))
        self.assertEqual(str(latest.close), "125.50")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.mfapi.in/mf/12345/latest")

    @patch("market_data.providers.mfapi_provider.urlopen")
    def test_latest_nav_rejects_empty_response(self, urlopen):
        urlopen.return_value = fake_response({
            "data": [],
            "status": "SUCCESS",
        })

        from market_data.errors import MarketDataError
        with self.assertRaises(MarketDataError):
            MFapiProvider().get_latest_nav("12345")

    @patch("market_data.providers.mfapi_provider.urlopen")
    def test_latest_nav_wraps_network_failure(self, urlopen):
        urlopen.side_effect = URLError("offline")

        from market_data.errors import MarketDataError
        with self.assertRaises(MarketDataError):
            MFapiProvider().get_latest_nav("12345")


if __name__ == "__main__":
    unittest.main()
