
"""Offline tests for FX rate refresh orchestration."""

import unittest
from datetime import date
from unittest.mock import MagicMock

from market_data.fx_service import FxRateService


class FxRateServiceTests(unittest.TestCase):

    def setUp(self):
        self.storage = MagicMock()
        self.provider = MagicMock()
        self.service = FxRateService(self.storage, self.provider)

    def test_refresh_history_fetches_and_saves_rates(self):
        bars = [MagicMock(), MagicMock()]
        self.provider.get_history.return_value = bars
        self.storage.save_history.return_value = 2

        count = self.service.refresh_history(
            date(2026, 11, 1),
            date(2026, 11, 25),
        )

        self.assertEqual(count, 2)
        self.provider.get_history.assert_called_once_with(
            date(2026, 11, 1),
            date(2026, 11, 25),
        )
        self.storage.save_history.assert_called_once_with(bars)

    def test_empty_provider_response_does_not_write(self):
        self.provider.get_history.return_value = []

        count = self.service.refresh_history(
            date(2026, 11, 1),
            date(2026, 11, 25),
        )

        self.assertEqual(count, 0)
        self.storage.save_history.assert_not_called()

    def test_rejects_invalid_date_range(self):
        with self.assertRaises(ValueError):
            self.service.refresh_history(
                date(2026, 11, 25),
                date(2026, 11, 1),
            )

        self.provider.get_history.assert_not_called()

    def test_recent_history_uses_requested_lookback(self):
        self.provider.get_history.return_value = []

        self.service.refresh_recent_history(
            lookback_days=5,
            end_date=date(2026, 11, 25),
        )

        self.provider.get_history.assert_called_once_with(
            date(2026, 11, 21),
            date(2026, 11, 25),
        )

    def test_rejects_zero_lookback(self):
        with self.assertRaises(ValueError):
            self.service.refresh_recent_history(lookback_days=0)

        self.provider.get_history.assert_not_called()

    def test_incremental_refresh_uses_overlap_before_latest_date(self):
        self.storage.get_latest_rate_date.return_value = date(2026, 11, 25)
        self.provider.get_history.return_value = []

        count = self.service.refresh_incremental_history(
            overlap_days=5,
            end_date=date(2026, 11, 25),
        )

        self.assertEqual(count, 0)

        self.storage.get_latest_rate_date.assert_called_once_with(
            base_currency="USD",
            quote_currency="INR",
        )
        self.provider.get_history.assert_called_once_with(
            date(2026, 11, 20),
            date(2026, 11, 25),
        )

    def test_incremental_refresh_falls_back_to_initial_history(self):
        self.storage.get_latest_rate_date.return_value = None
        self.provider.get_history.return_value = []

        count = self.service.refresh_incremental_history(
            initial_years=10,
            end_date=date(2026, 11, 25),
        )

        self.assertEqual(count, 0)
        self.provider.get_history.assert_called_once_with(
            date(2016, 11, 25),
            date(2026, 11, 25),
        )

    def test_incremental_refresh_rejects_zero_overlap(self):
        with self.assertRaises(ValueError):
            self.service.refresh_incremental_history(
                overlap_days=0,
                end_date=date(2026, 11, 25),
            )

        self.storage.get_latest_rate_date.assert_not_called()
        self.provider.get_history.assert_not_called()

    def test_incremental_refresh_rejects_future_latest_date(self):
        self.storage.get_latest_rate_date.return_value = date(2026, 11, 26)

        with self.assertRaises(ValueError):
            self.service.refresh_incremental_history(
                end_date=date(2026, 11, 25),
            )

        self.provider.get_history.assert_not_called()

    def test_years_before_handles_leap_day(self):
        result = FxRateService._years_before(
            date(2024, 2, 29),
            1,
        )

        self.assertEqual(result, date(2023, 2, 28))


if __name__ == "__main__":
    unittest.main()
