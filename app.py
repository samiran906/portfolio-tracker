"""Read-only Flask API for the portfolio tracker reporting layer."""

from datetime import date, datetime
from decimal import Decimal
import logging
import os

from flask import Flask, jsonify, render_template
from psycopg import Error as PsycopgError
from psycopg import connect
from psycopg.rows import dict_row


def _json_safe(value):
    """Preserve money/rate precision and format dates consistently in JSON."""
    if isinstance(value, Decimal):
        return str(value)

    if isinstance(value, (date, datetime)):
        return value.isoformat()

    if isinstance(value, dict):
        return {
            key: _json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [
            _json_safe(item)
            for item in value
        ]

    return value


def _database_url():
    database_url = os.environ.get("DATABASE_URL")

    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    return database_url


def _fetch_all(sql):
    with connect(
        _database_url(),
        row_factory=dict_row
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql)
            return cursor.fetchall()


def _fetch_one(sql):
    rows = _fetch_all(sql)
    return rows[0] if rows else None


def create_app():
    app = Flask(__name__)

    @app.get("/")
    def dashboard():
        return render_template("index.html")

    @app.errorhandler(RuntimeError)
    def handle_configuration_error(error):
        app.logger.warning(
            "API configuration error: %s",
            error
        )

        return jsonify({
            "error": "service is not configured"
        }), 503

    @app.errorhandler(PsycopgError)
    def handle_database_error(error):
        app.logger.exception(
            "Database query failed"
        )

        return jsonify({
            "error": "database query failed"
        }), 503

    @app.get("/health")
    def health():
        row = _fetch_one(
            """
            SELECT
                get_current_portfolio_valuation_date()
                AS valuation_date;
            """
        )

        return jsonify(
            _json_safe({
                "status": "ok",
                **(row or {})
            })
        )

    @app.get("/api")
    def api_index():
        return jsonify(
            {
                "endpoints": [
                    "/health",
                    "/api/portfolio/summary",
                    "/api/accounts",
                    "/api/classifications",
                    "/api/portfolio-groups",
                    "/api/securities",
                    "/api/reconciliation",
                    "/api/dashboard",
                ]
            }
        )

    @app.get("/api/portfolio/summary")
    def portfolio_summary():
        row = _fetch_one(
            """
            SELECT
                ps.*,
                prs.portfolio_xirr_percent
            FROM portfolio_summary ps
            CROSS JOIN portfolio_return_summary prs;
            """
        )

        return jsonify(
            _json_safe(row or {})
        )

    @app.get("/api/accounts")
    def accounts():
        rows = _fetch_all(
            """
            SELECT
                a.*,
                ar.account_xirr_percent
            FROM account_summary a
            LEFT JOIN account_return_summary ar
                ON ar.account_id = a.account_id
               AND ar.valuation_date = a.valuation_date
            ORDER BY a.account_name;
            """
        )

        return jsonify(
            _json_safe(rows)
        )

    @app.get("/api/classifications")
    def classifications():
        rows = _fetch_all(
            """
            SELECT
                c.*,
                cr.classification_xirr_percent
            FROM classification_summary c
            LEFT JOIN classification_return_summary cr
                ON cr.classification_id = c.classification_id
               AND cr.valuation_date = c.valuation_date
            ORDER BY c.classification_name;
            """
        )

        return jsonify(
            _json_safe(rows)
        )

    @app.get("/api/portfolio-groups")
    def portfolio_groups():
        rows = _fetch_all(
            """
            SELECT
                g.*,
                gr.portfolio_group_xirr_percent
            FROM portfolio_group_summary g
            LEFT JOIN portfolio_group_return_summary gr
                ON gr.portfolio_group_id = g.portfolio_group_id
               AND gr.valuation_date = g.valuation_date
            ORDER BY g.portfolio_group_name;
            """
        )

        return jsonify(
            _json_safe(rows)
        )

    @app.get("/api/securities")
    def securities():
        rows = _fetch_all(
            """
            SELECT
                s.*,
                sr.security_xirr_percent
            FROM security_summary s
            LEFT JOIN security_return_summary sr
                ON sr.account_security_id = s.account_security_id
               AND sr.valuation_date = s.valuation_date
            ORDER BY s.account_name, s.security_name;
            """
        )

        return jsonify(
            _json_safe(rows)
        )

    @app.get("/api/reconciliation")
    def reconciliation():
        row = _fetch_one(
            """
            SELECT *
            FROM portfolio_reporting_reconciliation;
            """
        )

        return jsonify(
            _json_safe(row or {})
        )

    @app.get("/api/dashboard")
    def dashboard_data():
        portfolio = _fetch_one(
            """
            SELECT
                ps.*,
                prs.portfolio_xirr_percent
            FROM portfolio_summary ps
            CROSS JOIN portfolio_return_summary prs;
            """
        )

        if portfolio is None:
            return jsonify({
                "error": "Portfolio summary is unavailable"
            }), 503

        accounts = _fetch_all(
            """
            SELECT
                a.*,
                ar.account_xirr_percent
            FROM account_summary a
            LEFT JOIN account_return_summary ar
                ON ar.account_id = a.account_id
               AND ar.valuation_date = a.valuation_date
            ORDER BY a.total_account_value DESC;
            """
        )

        classifications = _fetch_all(
            """
            SELECT
                c.*,
                cr.classification_xirr_percent
            FROM classification_summary c
            LEFT JOIN classification_return_summary cr
                ON cr.classification_id = c.classification_id
               AND cr.valuation_date = c.valuation_date
            ORDER BY c.total_securities_value DESC;
            """
        )

        portfolio_groups = _fetch_all(
            """
            SELECT
                g.*,
                gr.portfolio_group_xirr_percent
            FROM portfolio_group_summary g
            LEFT JOIN portfolio_group_return_summary gr
                ON gr.portfolio_group_id = g.portfolio_group_id
               AND gr.valuation_date = g.valuation_date
            ORDER BY g.total_securities_value DESC;
            """
        )

        securities = _fetch_all(
            """
            SELECT
                s.*,
                sr.security_xirr_percent
            FROM security_summary s
            LEFT JOIN security_return_summary sr
                ON sr.account_security_id = s.account_security_id
               AND sr.valuation_date = s.valuation_date
            WHERE s.quantity_held <> 0
            ORDER BY s.current_value DESC;
            """
        )

        return jsonify(
            _json_safe({
                "portfolio": portfolio,
                "accounts": accounts,
                "classifications": classifications,
                "portfolio_groups": portfolio_groups,
                "securities": securities
            })
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5050,
        debug=True
    )
