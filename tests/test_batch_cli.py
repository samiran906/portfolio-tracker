"""Tests for selecting one security in the market-data batch CLI."""

import unittest
from datetime import date

from market_data.batch import BatchPlan, HistoryRefreshPlan
from market_data.batch_cli import select_security_plan


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


if __name__ == "__main__":
    unittest.main()
