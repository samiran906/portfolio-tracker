
"""Orchestration for historical foreign-exchange rate refreshes."""

import calendar
from datetime import date, timedelta

from market_data.fx_storage import FxRateStorage
from market_data.providers.yahoo_fx_provider import YahooFinanceFxProvider


class FxRateService:
    """Fetch and persist historical FX rates."""

    def __init__(self, storage: FxRateStorage, provider=None):
        self.storage = storage
        self.provider = provider or YahooFinanceFxProvider()

    def refresh_history(
        self,
        start_date: date,
        end_date: date | None = None,
    ) -> int:
        """Fetch and store rates for the requested inclusive date range."""

        target_end = end_date or date.today()

        if target_end < start_date:
            raise ValueError("end_date must not precede start_date")

        bars = self.provider.get_history(start_date, target_end)

        if not bars:
            return 0

        return self.storage.save_history(bars)

    @staticmethod
    def _years_before(target_date: date, years: int) -> date:
        """Subtract calendar years, handling leap-day boundaries."""
        target_year = target_date.year - years
        last_day = calendar.monthrange(
            target_year, target_date.month
        )[1]

        return target_date.replace(
            year=target_year,
            day=min(target_date.day, last_day),
        )

    def refresh_initial_history(self, years: int = 10) -> int:
        """Load initial history, defaulting to ten years."""

        if years < 1:
            raise ValueError("years must be at least 1")

        end_date = date.today()
        start_date = self._years_before(end_date, years)

        return self.refresh_history(start_date, end_date)

    def refresh_recent_history(
        self,
        lookback_days: int = 5,
        end_date: date | None = None,
    ) -> int:
        """Refresh a recent window, including its end date."""

        if lookback_days < 1:
            raise ValueError("lookback_days must be at least 1")

        target_end = end_date or date.today()
        start_date = target_end - timedelta(days=lookback_days - 1)

        return self.refresh_history(start_date, target_end)

    def refresh_incremental_history(
        self,
        overlap_days: int = 5,
        initial_years: int = 10,
        end_date: date | None = None,
    ) -> int:
        """
        Refresh from an overlap before the latest stored date.

        If no history exists, load the initial historical period.
        """

        if overlap_days < 1:
            raise ValueError("overlap_days must be at least 1")

        if initial_years < 1:
            raise ValueError("initial_years must be at least 1")

        target_end = end_date or date.today()

        latest_date = self.storage.get_latest_rate_date(
            base_currency="USD",
            quote_currency="INR",
        )

        if latest_date is None:
            start_date = self._years_before(
                target_end,
                initial_years,
            )
        else:
            if latest_date > target_end:
                raise ValueError(
                    "Latest stored FX rate date is after the requested end date"
                )

            start_date = latest_date - timedelta(days=overlap_days)

        return self.refresh_history(start_date, target_end)
