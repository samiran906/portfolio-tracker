"""Flask API for the portfolio tracker reporting and management layer."""

from datetime import date, datetime
from decimal import Decimal
import logging
import os

from flask import Flask, jsonify, render_template, request
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


def _fetch_one(sql, params=None):
    with connect(
        _database_url(),
        row_factory=dict_row
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, params or ())
            return cursor.fetchone()

def _execute(sql, params=None):
    with connect(
        _database_url(),
        row_factory=dict_row
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, params or ())
            return cursor.fetchone()

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

    @app.put("/api/manage/accounts/<int:account_id>")
    def update_account(account_id):
        data = request.get_json(silent=True) or {}

        name = data.get("name")
        account_type = data.get("account_type")
        base_currency = data.get("base_currency")
        account_role = data.get("account_role")
        is_active = data.get("is_active")

        if (
            not name
            or not account_type
            or not base_currency
            or not account_role
            or is_active is None
        ):
            return jsonify({
                "error": (
                    "name, account_type, base_currency, "
                    "account_role, and is_active are required"
                )
            }), 400

        if account_role not in ("PORTFOLIO", "BALANCE_ONLY"):
            return jsonify({
                "error": "account_role must be PORTFOLIO or BALANCE_ONLY"
            }), 400

        if not isinstance(base_currency, str) or len(base_currency) != 3:
            return jsonify({
                "error": "base_currency must be a 3-letter currency code"
            }), 400

        if not isinstance(is_active, bool):
            return jsonify({
                "error": "is_active must be true or false"
            }), 400

        try:
            row = _execute(
                """
                UPDATE accounts
                SET
                    name = %s,
                    account_type = %s,
                    base_currency = %s,
                    account_role = %s,
                    is_active = %s,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING
                    id,
                    name,
                    account_type,
                    base_currency,
                    is_active,
                    account_role,
                    created_at,
                    updated_at;
                """,
                (
                    name.strip(),
                    account_type.strip(),
                    base_currency.upper(),
                    account_role,
                    is_active,
                    account_id,
                ),
            )

            if row is None:
                return jsonify({
                    "error": "account not found"
                }), 404

            return jsonify(_json_safe(row))

        except PsycopgError as error:
            app.logger.exception("Failed to update account")

            if getattr(error, "sqlstate", None) == "23505":
                return jsonify({
                    "error": "An account with this name already exists"
                }), 409

            return jsonify({
                "error": "unable to update account"
            }), 400

    @app.get("/api/manage/classifications")
    def manage_classifications():
        try:
            rows = _fetch_all(
                """
                SELECT
                    id,
                    name,
                    parent_id,
                    description,
                    is_active,
                    created_at
                FROM classifications
                ORDER BY name;
                """
            )

            return jsonify(_json_safe(rows))

        except PsycopgError:
            app.logger.exception("Failed to fetch classifications")
            return jsonify({
                "error": "unable to fetch classifications"
            }), 500

    @app.post("/api/manage/classifications")
    def create_classification():
        data = request.get_json(silent=True) or {}

        name = data.get("name")
        parent_id = data.get("parent_id")
        description = data.get("description")

        if not name:
            return jsonify({
                "error": "name is required"
            }), 400

        name = name.strip()

        if not name:
            return jsonify({
                "error": "name is required"
            }), 400

        if parent_id is not None:
            try:
                parent_id = int(parent_id)
            except (TypeError, ValueError):
                return jsonify({
                    "error": "parent_id must be an integer or null"
                }), 400

            if parent_id <= 0:
                return jsonify({
                    "error": "parent_id must be a positive integer or null"
                }), 400

            parent = _fetch_one(
                """
                SELECT id
                FROM classifications
                WHERE id = %s;
                """,
                (parent_id,),
            )

            if parent is None:
                return jsonify({
                    "error": "parent classification not found"
                }), 400

        try:
            row = _execute(
                """
                INSERT INTO classifications (
                    name,
                    parent_id,
                    description,
                    is_active
                )
                VALUES (%s, %s, %s, TRUE)
                RETURNING
                    id,
                    name,
                    parent_id,
                    description,
                    is_active,
                    created_at;
                """,
                (
                    name,
                    parent_id,
                    description.strip() if isinstance(description, str) else None,
                ),
            )

            return jsonify(_json_safe(row)), 201

        except PsycopgError as error:
            app.logger.exception("Failed to create classification")

            if getattr(error, "sqlstate", None) == "23505":
                return jsonify({
                    "error": "A classification with this name and parent already exists"
                }), 409

            if getattr(error, "sqlstate", None) == "23503":
                return jsonify({
                    "error": "parent classification not found"
                }), 400

            return jsonify({
                "error": "unable to create classification"
            }), 400

    @app.put("/api/manage/classifications/<int:classification_id>")
    def update_classification(classification_id):
        data = request.get_json(silent=True) or {}

        name = data.get("name")
        parent_id = data.get("parent_id")
        description = data.get("description")
        is_active = data.get("is_active")

        if (
            not name
            or is_active is None
        ):
            return jsonify({
                "error": "name and is_active are required"
            }), 400

        name = name.strip()

        if not name:
            return jsonify({
                "error": "name is required"
            }), 400

        if not isinstance(is_active, bool):
            return jsonify({
                "error": "is_active must be true or false"
            }), 400

        if parent_id is not None:
            try:
                parent_id = int(parent_id)
            except (TypeError, ValueError):
                return jsonify({
                    "error": "parent_id must be an integer or null"
                }), 400

            if parent_id <= 0:
                return jsonify({
                    "error": "parent_id must be a positive integer or null"
                }), 400

            if parent_id == classification_id:
                return jsonify({
                    "error": "a classification cannot be its own parent"
                }), 400

            parent = _fetch_one(
                """
                SELECT id
                FROM classifications
                WHERE id = %s;
                """,
                (parent_id,),
            )

            if parent is None:
                return jsonify({
                    "error": "parent classification not found"
                }), 400

        try:
            existing = _fetch_one(
                """
                SELECT id
                FROM classifications
                WHERE id = %s;
                """,
                (classification_id,),
            )

            if existing is None:
                return jsonify({
                    "error": "classification not found"
                }), 404

            if not is_active:
                child = _fetch_one(
                    """
                    SELECT id
                    FROM classifications
                    WHERE parent_id = %s
                    AND is_active = TRUE
                    LIMIT 1;
                    """,
                    (classification_id,),
                )

                if child is not None:
                    return jsonify({
                        "error": (
                            "cannot deactivate a classification "
                            "while it has active child classifications"
                        )
                    }), 409

            row = _execute(
                """
                UPDATE classifications
                SET
                    name = %s,
                    parent_id = %s,
                    description = %s,
                    is_active = %s
                WHERE id = %s
                RETURNING
                    id,
                    name,
                    parent_id,
                    description,
                    is_active,
                    created_at;
                """,
                (
                    name,
                    parent_id,
                    description.strip()
                    if isinstance(description, str)
                    else None,
                    is_active,
                    classification_id,
                ),
            )

            return jsonify(_json_safe(row))

        except PsycopgError as error:
            app.logger.exception("Failed to update classification")

            if getattr(error, "sqlstate", None) == "23505":
                return jsonify({
                    "error": (
                        "A classification with this name and parent "
                        "already exists"
                    )
                }), 409

            if getattr(error, "sqlstate", None) == "23503":
                return jsonify({
                    "error": "parent classification not found"
                }), 400

            return jsonify({
                "error": "unable to update classification"
            }), 400

    @app.get("/api/manage/accounts")
    def manage_accounts():
        rows = _fetch_all(
            """
            SELECT
                id,
                name,
                account_type,
                base_currency,
                is_active,
                account_role,
                created_at,
                updated_at
            FROM accounts
            ORDER BY name;
            """
        )

        return jsonify(_json_safe(rows))

    @app.post("/api/manage/accounts")
    def create_account():
        data = request.get_json(silent=True) or {}

        name = data.get("name")
        account_type = data.get("account_type")
        base_currency = data.get("base_currency", "INR")
        account_role = data.get("account_role")

        if not name or not account_type or not account_role:
            return jsonify({
                "error": "name, account_type, and account_role are required"
            }), 400

        if account_role not in ("PORTFOLIO", "BALANCE_ONLY"):
            return jsonify({
                "error": "account_role must be PORTFOLIO or BALANCE_ONLY"
            }), 400

        if not isinstance(base_currency, str) or len(base_currency) != 3:
            return jsonify({
                "error": "base_currency must be a 3-letter currency code"
            }), 400

        try:
            row = _execute(
                """
                INSERT INTO accounts (
                    name,
                    account_type,
                    base_currency,
                    is_active,
                    account_role
                )
                VALUES (%s, %s, %s, TRUE, %s)
                RETURNING
                    id,
                    name,
                    account_type,
                    base_currency,
                    is_active,
                    account_role,
                    created_at,
                    updated_at;
                """,
                (
                    name.strip(),
                    account_type.strip(),
                    base_currency.upper(),
                    account_role,
                ),
            )

            return jsonify(_json_safe(row)), 201

        except PsycopgError as error:
            app.logger.exception("Failed to create account")

            if getattr(error, "sqlstate", None) == "23505":
                return jsonify({
                    "error": "An account with this name already exists"
                }), 409

            return jsonify({
                "error": "unable to create account"
            }), 400
        
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
