"""Offline tests for market-data batch planning."""

import unittest
from types import SimpleNamespace
from datetime import date
from unittest.mock import MagicMock

from market_data.batch import MarketDataBatchPlanner


class MarketDataBatchPlannerTests(unittest.TestCase):

    def setUp(self):
        self.storage = MagicMock()
        self.planner = MarketDataBatchPlanner(self.storage)

    def security(self, security_id, **overrides):
        row = {
            "security_id": security_id,
            "name": f"Security {security_id}",
            "symbol": f"TEST{security_id}",
            "instrument_type": "STOCK",
            "currency": "INR",
            "account_security_id": security_id + 100,
            "broker_symbol": None,
            "account_id": 1,
            "account_name": "Zerodha",
            "active_association_count": 1,
            "first_transaction_date": None,
        }
        row.update(overrides)
        return row

    def test_new_security_without_transactions_gets_ten_years(self):
        self.storage.get_active_market_data_securities.return_value = [
            self.security(1)
        ]
        self.storage.get_latest_price_dates.return_value = {}

        plan = self.planner.create_plan(date(2026, 11, 10))

        self.assertEqual(len(plan.planned), 1)
        item = plan.planned[0]

        self.assertEqual(item.start_date, date(2016, 11, 10))
        self.assertEqual(item.end_date, date(2026, 11, 10))
        self.assertEqual(item.reason, "initial_load_default_period")

    def test_new_security_uses_earliest_transaction_date(self):
        self.storage.get_active_market_data_securities.return_value = [
            self.security(
                1,
                first_transaction_date=date(2022, 5, 12),
            )
        ]
        self.storage.get_latest_price_dates.return_value = {}

        plan = self.planner.create_plan(date(2026, 11, 10))

        self.assertEqual(
            plan.planned[0].start_date,
            date(2022, 5, 12),
        )
        self.assertEqual(
            plan.planned[0].reason,
            "initial_load_from_first_transaction",
        )

    def test_existing_security_uses_five_day_overlap(self):
        self.storage.get_active_market_data_securities.return_value = [
            self.security(1)
        ]
        self.storage.get_latest_price_dates.return_value = {
            1: date(2026, 11, 6)
        }

        plan = self.planner.create_plan(date(2026, 11, 10))

        self.assertEqual(
            plan.planned[0].start_date,
            date(2026, 11, 1),
        )
        self.assertEqual(
            plan.planned[0].reason,
            "incremental_refresh",
        )

    def test_multiple_active_associations_are_skipped(self):
        self.storage.get_active_market_data_securities.return_value = [
            self.security(1, active_association_count=2),
            self.security(
                1,
                account_security_id=102,
                account_name="INDmoney",
                active_association_count=2,
            ),
        ]
        self.storage.get_latest_price_dates.return_value = {
            1: date(2026, 11, 6)
        }

        plan = self.planner.create_plan(date(2026, 11, 10))

        self.assertEqual(plan.planned, [])
        self.assertEqual(len(plan.skipped), 1)
        self.assertEqual(plan.skipped[0]["security_id"], 1)

    def test_empty_security_list_returns_empty_plan(self):
        self.storage.get_active_market_data_securities.return_value = []

        plan = self.planner.create_plan(date(2026, 11, 10))

        self.assertEqual(plan.planned, [])
        self.assertEqual(plan.skipped, [])
        self.storage.get_latest_price_dates.assert_not_called()

    def test_invalid_configuration_is_rejected(self):
        with self.assertRaises(ValueError):
            MarketDataBatchPlanner(self.storage, initial_history_years=0)

        with self.assertRaises(ValueError):
            MarketDataBatchPlanner(self.storage, overlap_days=-1)

    def test_leap_day_year_subtraction(self):
        self.assertEqual(
            self.planner._years_ago(date(2024, 2, 29), 10),
            date(2014, 2, 28),
        )


class MarketDataBatchRunnerTests(unittest.TestCase):

    def setUp(self):
        from market_data.batch import MarketDataBatchRunner

        self.service = MagicMock()
        self.runner = MarketDataBatchRunner(self.service)

    @staticmethod
    def item(security_id):
        from market_data.batch import HistoryRefreshPlan

        return HistoryRefreshPlan(
            security_id=security_id,
            security={"security_id": security_id},
            start_date=date(2026, 11, 1),
            end_date=date(2026, 11, 10),
            reason="incremental_refresh",
        )

    @staticmethod
    def refresh_result(status="success", records_written=5, **kwargs):
        return SimpleNamespace(
            status=status,
            records_written=records_written,
            provider=kwargs.get("provider", "Yahoo Finance"),
            fallback_reason=kwargs.get("fallback_reason"),
            error=kwargs.get("error"),
        )

    def test_executes_all_planned_securities(self):
        from market_data.batch import BatchPlan

        self.service.refresh_history_result.side_effect = [
            self.refresh_result(records_written=5),
            self.refresh_result(records_written=8, provider="NSE"),
        ]

        plan = BatchPlan(
            planned=[self.item(1), self.item(2)],
            skipped=[],
        )

        report = self.runner.execute(plan)

        self.assertEqual(len(report.results), 2)
        self.assertEqual(report.succeeded, 2)
        self.assertEqual(report.failed, 0)
        self.assertEqual(report.records_written, 13)

        self.assertEqual(
            self.service.refresh_history_result.call_count,
            2,
        )

    def test_failure_does_not_stop_remaining_securities(self):
        from market_data.batch import BatchPlan

        self.service.refresh_history_result.side_effect = [
            self.refresh_result(
                status="failed",
                records_written=0,
                error="Simulated provider failure",
            ),
            self.refresh_result(records_written=7),
        ]

        plan = BatchPlan(
            planned=[self.item(1), self.item(2)],
            skipped=[],
        )

        report = self.runner.execute(plan)

        self.assertEqual(report.failed, 1)
        self.assertEqual(report.succeeded, 1)
        self.assertEqual(report.records_written, 7)
        self.assertEqual(
            self.service.refresh_history_result.call_count,
            2,
        )

    def test_no_data_is_reported_separately(self):
        from market_data.batch import BatchPlan

        self.service.refresh_history_result.return_value = (
            self.refresh_result(status="no_data", records_written=0)
        )

        report = self.runner.execute(
            BatchPlan(planned=[self.item(1)], skipped=[])
        )

        self.assertEqual(report.no_data, 1)
        self.assertEqual(report.failed, 0)
        self.assertEqual(report.records_written, 0)

    def test_unexpected_exception_does_not_stop_batch(self):
        from market_data.batch import BatchPlan

        self.service.refresh_history_result.side_effect = [
            RuntimeError("Unexpected test exception"),
            self.refresh_result(records_written=3),
        ]

        report = self.runner.execute(
            BatchPlan(
                planned=[self.item(1), self.item(2)],
                skipped=[],
            )
        )

        self.assertEqual(report.failed, 1)
        self.assertEqual(report.succeeded, 1)
        self.assertEqual(
            report.results[0].error,
            "Unexpected test exception",
        )

    def test_skipped_securities_are_preserved(self):
        from market_data.batch import BatchPlan

        skipped = [
            {
                "security_id": 9,
                "status": "skipped",
                "reason": "Multiple active portfolio account associations",
            }
        ]

        report = self.runner.execute(
            BatchPlan(planned=[], skipped=skipped)
        )

        self.assertEqual(report.skipped, skipped)
        self.service.refresh_history_result.assert_not_called()

    def test_empty_batch_returns_empty_report(self):
        from market_data.batch import BatchPlan

        report = self.runner.execute(
            BatchPlan(planned=[], skipped=[])
        )

        self.assertEqual(report.results, [])
        self.assertEqual(report.records_written, 0)
        self.service.refresh_history_result.assert_not_called()


if __name__ == "__main__":
    unittest.main()
