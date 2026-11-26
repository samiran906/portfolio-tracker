"""Tests for selecting one security in the market-data batch CLI."""

import unittest
from contextlib import redirect_stdout
from datetime import date
from io import StringIO
from unittest.mock import patch

from market_data.batch import BatchPlan, HistoryRefreshPlan
from market_data.batch_cli import (
    run_fx_refresh,
    run_optional_fx_refresh,
    select_security_plan,
)


class SelectSecurityPlanTests(unittest.TestCase):

    @staticmethod
    def item(security_id, reason):
        return HistoryRefreshPlan(
            security_id=security_id,
            security={
                "security_id": security_id,
                "name": f"Security {security_id}",
                "symbol": f"S{security_id}",
                "account_name": "Zerodha",
            },
            start_date=date(2020, 1, 1),
            end_date=date(2026, 11, 23),
            reason=reason,
        )

    def test_selects_only_requested_initial_load(self):
        plan = BatchPlan(
            planned=[
                self.item(10, "initial_load_default_period"),
                self.item(11, "initial_load_from_first_transaction"),
            ],
            skipped=[],
        )

        selected = select_security_plan(plan, 11)

        self.assertEqual(
            [item.security_id for item in selected.planned],
            [11],
        )
        self.assertEqual(selected.skipped, [])

    def test_skips_when_history_already_exists(self):
        plan = BatchPlan(
            planned=[self.item(10, "incremental_refresh")],
            skipped=[],
        )

        selected = select_security_plan(plan, 10)

        self.assertEqual(selected.planned, [])
        self.assertEqual(len(selected.skipped), 1)
        self.assertEqual(selected.skipped[0]["security_id"], 10)
        self.assertIn("already exists", selected.skipped[0]["reason"])

    def test_reports_security_not_in_market_data_plan(self):
        plan = BatchPlan(planned=[], skipped=[])

        selected = select_security_plan(plan, 999)

        self.assertEqual(selected.planned, [])
        self.assertEqual(selected.skipped[0]["security_id"], 999)
        self.assertEqual(selected.skipped[0]["status"], "skipped")


class FxRefreshCliTests(unittest.TestCase):

    @patch("market_data.batch_cli.create_fx_service")
    def test_fx_refresh_runs_incremental_service(self, create_service):
        service = create_service.return_value
        service.refresh_incremental_history.return_value = 4
        service.storage.get_latest_rate_date.return_value = date(
            2026, 11, 25
        )

        run_fx_refresh()

        service.refresh_incremental_history.assert_called_once_with()
        service.storage.get_latest_rate_date.assert_called_once_with(
            base_currency="USD",
            quote_currency="INR",
        )

    @patch("market_data.batch_cli.create_fx_service")
    def test_fx_exception_is_caught(self, create_service):
        create_service.side_effect = RuntimeError("Provider unavailable")
        output = StringIO()

        with redirect_stdout(output):
            run_fx_refresh()

        self.assertIn("FX REFRESH FAILED", output.getvalue())
        self.assertIn("Provider unavailable", output.getvalue())

    @patch("market_data.batch_cli.run_fx_refresh")
    def test_fx_is_not_run_without_flag(self, run_fx):
        run_optional_fx_refresh(
            include_fx=False,
            security_id=None,
        )

        run_fx.assert_not_called()

    @patch("market_data.batch_cli.run_fx_refresh")
    def test_fx_is_skipped_for_individual_security_refresh(self, run_fx):
        run_optional_fx_refresh(
            include_fx=True,
            security_id=10,
        )

        run_fx.assert_not_called()

    @patch("market_data.batch_cli.run_fx_refresh")
    def test_fx_runs_for_enabled_full_batch(self, run_fx):
        run_optional_fx_refresh(
            include_fx=True,
            security_id=None,
        )

        run_fx.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
