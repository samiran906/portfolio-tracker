"""Tests for the individual-security market-data Flask endpoints."""

import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

from flask import Flask

from market_data.flask_routes import create_market_data_blueprint


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.sql = None
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, sql, params=None):
        self.sql = sql
        self.params = params

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, rows):
        self.fake_cursor = FakeCursor(rows)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def cursor(self):
        return self.fake_cursor


class MarketDataFlaskRouteTests(unittest.TestCase):

    def setUp(self):
        self.security = {
            "security_id": 1,
            "name": "Test Security",
            "symbol": "TEST",
            "instrument_type": "STOCK",
            "currency": "INR",
            "account_security_id": 10,
            "broker_symbol": "TEST.NS",
            "account_id": 5,
        }

        self.rows = [self.security]
        self.connection = FakeConnection(self.rows)
        self.connection_factory = Mock(return_value=self.connection)

        self.service = Mock()

        app = Flask(__name__)
        app.register_blueprint(
            create_market_data_blueprint(
                self.connection_factory,
                self.service,
            )
        )
        app.testing = True
        self.client = app.test_client()

    @staticmethod
    def result(status="success", records_written=1, error=None):
        return SimpleNamespace(
            status=status,
            records_written=records_written,
            error=error,
        )

    def test_history_success(self):
        self.service.refresh_history_result.return_value = self.result(
            records_written=10
        )

        response = self.client.post(
            "/api/market-data/securities/1/history",
            json={
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["status"], "success")
        self.assertEqual(response.json["records_written"], 10)

        self.service.refresh_history_result.assert_called_once_with(
            self.security,
            date(2026, 1, 1),
            date(2026, 1, 31),
        )

    def test_history_without_end_date(self):
        self.service.refresh_history_result.return_value = self.result()

        response = self.client.post(
            "/api/market-data/securities/1/history",
            json={"start_date": "2026-01-01"},
        )

        self.assertEqual(response.status_code, 200)

        self.service.refresh_history_result.assert_called_once_with(
            self.security,
            date(2026, 1, 1),
            None,
        )

    def test_history_no_data_returns_successful_http_response(self):
        self.service.refresh_history_result.return_value = self.result(
            status="no_data",
            records_written=0,
        )

        response = self.client.post(
            "/api/market-data/securities/1/history",
            json={"start_date": "2026-01-01"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["status"], "no_data")
        self.assertEqual(response.json["records_written"], 0)

    def test_history_requires_start_date(self):
        response = self.client.post(
            "/api/market-data/securities/1/history",
            json={},
        )

        self.assertEqual(response.status_code, 400)
        self.service.refresh_history_result.assert_not_called()

    def test_history_rejects_invalid_start_date(self):
        response = self.client.post(
            "/api/market-data/securities/1/history",
            json={"start_date": "2026-02-30"},
        )

        self.assertEqual(response.status_code, 400)
        self.service.refresh_history_result.assert_not_called()

    def test_history_rejects_end_date_before_start_date(self):
        response = self.client.post(
            "/api/market-data/securities/1/history",
            json={
                "start_date": "2026-02-10",
                "end_date": "2026-02-01",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.service.refresh_history_result.assert_not_called()

    def test_history_requires_json_body(self):
        response = self.client.post(
            "/api/market-data/securities/1/history",
        )

        self.assertEqual(response.status_code, 400)
        self.service.refresh_history_result.assert_not_called()

    def test_quote_success(self):
        self.service.refresh_quote_result.return_value = self.result()

        response = self.client.post(
            "/api/market-data/securities/1/quote",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["operation"], "quote")
        self.assertEqual(response.json["status"], "success")

        self.service.refresh_quote_result.assert_called_once_with(
            self.security
        )

    def test_provider_failure_returns_502(self):
        self.service.refresh_quote_result.return_value = self.result(
            status="failed",
            records_written=0,
            error="Provider unavailable",
        )

        response = self.client.post(
            "/api/market-data/securities/1/quote",
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json["status"], "failed")
        self.assertEqual(response.json["error"], "Provider unavailable")

    def test_inactive_or_missing_security_returns_404(self):
        self.connection = FakeConnection([])

        self.connection_factory.return_value = self.connection

        response = self.client.post(
            "/api/market-data/securities/999/quote",
        )

        self.assertEqual(response.status_code, 404)
        self.service.refresh_quote_result.assert_not_called()

    def test_multiple_active_account_associations_return_409(self):
        self.connection = FakeConnection([
            self.security,
            dict(self.security, account_id=6, account_security_id=11),
        ])

        self.connection_factory.return_value = self.connection

        response = self.client.post(
            "/api/market-data/securities/1/quote",
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn(
            "cannot determine which broker symbol to use",
            response.json["error"],
        )
        self.service.refresh_quote_result.assert_not_called()

    def test_history_rejects_invalid_end_date(self):
        response = self.client.post(
            "/api/market-data/securities/1/history",
            json={
                "start_date": "2026-01-01",
                "end_date": "2026-02-30",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.service.refresh_history_result.assert_not_called()

    def test_history_rejects_non_string_end_date(self):
        response = self.client.post(
            "/api/market-data/securities/1/history",
            json={
                "start_date": "2026-01-01",
                "end_date": 20260201,
            },
        )

        self.assertEqual(response.status_code, 400)
        self.service.refresh_history_result.assert_not_called()

    def test_history_provider_failure_returns_502(self):
        self.service.refresh_history_result.return_value = self.result(
            status="failed",
            records_written=0,
            error="Provider unavailable",
        )

        response = self.client.post(
            "/api/market-data/securities/1/history",
            json={"start_date": "2026-01-01"},
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json["status"], "failed")
        self.assertEqual(response.json["error"], "Provider unavailable")

    def test_unsupported_instrument_history_returns_422(self):
        self.security["instrument_type"] = "PRECIOUS_METAL"

        response = self.client.post(
            "/api/market-data/securities/1/history",
            json={"start_date": "2026-01-01"},
        )

        self.assertEqual(response.status_code, 422)
        self.service.refresh_history_result.assert_not_called()

    def test_unsupported_instrument_returns_422(self):
        self.security["instrument_type"] = "PRECIOUS_METAL"

        response = self.client.post(
            "/api/market-data/securities/1/quote",
        )

        self.assertEqual(response.status_code, 422)
        self.service.refresh_quote_result.assert_not_called()


if __name__ == "__main__":
    unittest.main()
