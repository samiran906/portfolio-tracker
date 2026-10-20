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
        view = request.args.get("view", "dashboard")

        if view == "management":
            return render_template(
                "management.html",
                active_view="management"
            )

        if view == "securities":
            return render_template(
                "securities.html",
                active_view="securities"
            )

        if view == "transactions":
            return render_template(
                "transactions.html",
                active_view="transactions"
            )

        return render_template(
            "dashboard.html",
            active_view="dashboard"
        )
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


    @app.get("/api/manage/securities")
    def manage_securities():
        rows = _fetch_all(
            """
            SELECT
                s.id,
                s.name,
                s.symbol,
                s.instrument_type,
                s.currency,
                s.exchange,
                s.country,
                s.is_active,
                sc.classification_id,
                c.name AS classification_name,
                COALESCE(
                    (
                        SELECT jsonb_agg(
                            jsonb_build_object(
                                'account_id', a.id,
                                'account_name', a.name,
                                'account_security_id', ase.id,
                                'is_active', ase.is_active,
                                'broker_symbol', ase.broker_symbol,
                                'broker_security_id', ase.broker_security_id,
                                'opened_on', ase.opened_on
                            )
                            ORDER BY a.name
                        )
                        FROM account_securities ase
                        JOIN accounts a ON a.id = ase.account_id
                        WHERE ase.security_id = s.id
                    ),
                    '[]'::jsonb
                ) AS accounts
            FROM securities s
            LEFT JOIN security_classifications sc
                ON sc.security_id = s.id
            LEFT JOIN classifications c
                ON c.id = sc.classification_id
            ORDER BY s.name;
            """
        )
        return jsonify(_json_safe(rows))

    @app.post("/api/manage/securities")
    def create_security():
        data = request.get_json(silent=True) or {}

        name = data.get("name")
        instrument_type = data.get("instrument_type")
        currency = data.get("currency")
        classification_id = data.get("classification_id")
        account_id = data.get("account_id")
        symbol = data.get("symbol")
        exchange = data.get("exchange")
        country = data.get("country")
        broker_symbol = data.get("broker_symbol")
        broker_security_id = data.get("broker_security_id")
        opened_on = data.get("opened_on")

        if opened_on in ("", None):
            opened_on = None
        elif not isinstance(opened_on, str):
            return jsonify({
                "error": "opened_on must be a date in YYYY-MM-DD format"
            }), 400
        else:
            try:
                parsed_date = date.fromisoformat(opened_on)
                if parsed_date.isoformat() != opened_on:
                    raise ValueError
                opened_on = parsed_date
            except ValueError:
                return jsonify({
                    "error": "opened_on must be a valid date in YYYY-MM-DD format"
                }), 400

        allowed_types = {
            "STOCK", "ETF", "MUTUAL_FUND", "PRECIOUS_METAL"
        }

        if not isinstance(name, str) or not name.strip():
            return jsonify({"error": "name is required"}), 400

        if not isinstance(instrument_type, str) or instrument_type not in allowed_types:
            return jsonify({
                "error": "instrument_type must be STOCK, ETF, MUTUAL_FUND, or PRECIOUS_METAL"
            }), 400

        if not isinstance(currency, str) or len(currency.strip()) != 3:
            return jsonify({
                "error": "currency must be a 3-letter currency code"
            }), 400

        try:
            classification_id = int(classification_id)
            account_id = int(account_id)
            if classification_id <= 0 or account_id <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({
                "error": "classification_id and account_id must be positive integers"
            }), 400

        try:
            with connect(_database_url(), row_factory=dict_row) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT c.id
                        FROM classifications c
                        WHERE c.id = %s
                          AND c.is_active = TRUE
                          AND NOT EXISTS (
                              SELECT 1
                              FROM classifications child
                              WHERE child.parent_id = c.id
                          );
                        """,
                        (classification_id,),
                    )
                    if cursor.fetchone() is None:
                        return jsonify({
                            "error": "an active leaf classification is required"
                        }), 400

                    cursor.execute(
                        """
                        SELECT id, name
                        FROM accounts
                        WHERE id = %s
                          AND is_active = TRUE
                          AND account_role = 'PORTFOLIO';
                        """,
                        (account_id,),
                    )
                    selected_account = cursor.fetchone()
                    if selected_account is None:
                        return jsonify({
                            "error": "an active portfolio account is required"
                        }), 400

                    account_name = selected_account["name"]
                    country_value = (country or "").strip().lower() if isinstance(country, str) else ""

                    if account_name == "Zerodha":
                        allowed_account_types = {"STOCK", "ETF"}
                        expected_currency = "INR"
                        expected_country = "india"
                    elif account_name == "INDmoney":
                        allowed_account_types = {"STOCK", "ETF"}
                        expected_currency = "USD"
                        expected_country = "usa"
                        if country_value in {"us", "united states", "united states of america"}:
                            country_value = "usa"
                    elif account_name == "Paytm Money":
                        allowed_account_types = {"MUTUAL_FUND"}
                        expected_currency = "INR"
                        expected_country = "india"
                    else:
                        return jsonify({
                            "error": "securities can only be assigned to Zerodha, INDmoney, or Paytm Money"
                        }), 400

                    if instrument_type not in allowed_account_types:
                        return jsonify({
                            "error": f"{account_name} does not support this instrument type"
                        }), 400

                    if currency.strip().upper() != expected_currency:
                        return jsonify({
                            "error": f"{account_name} requires currency {expected_currency}"
                        }), 400

                    if country_value != expected_country:
                        return jsonify({
                            "error": f"{account_name} requires country "
                                     f"{'USA' if expected_country == 'usa' else 'India'}"
                        }), 400

                    country = "USA" if expected_country == "usa" else "India"

                    cursor.execute(
                        """
                        INSERT INTO securities (
                            name, symbol, instrument_type, currency,
                            exchange, country, is_active
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, TRUE)
                        RETURNING id, name, symbol, instrument_type,
                                  currency, exchange, country, is_active;
                        """,
                        (
                            name.strip(),
                            symbol.strip() or None if isinstance(symbol, str) else None,
                            instrument_type,
                            currency.strip().upper(),
                            exchange.strip() or None if isinstance(exchange, str) else None,
                            country.strip() or None if isinstance(country, str) else None,
                        ),
                    )
                    security = cursor.fetchone()
                    security_id = security["id"]

                    cursor.execute(
                        """
                        INSERT INTO security_classifications (
                            security_id, classification_id
                        )
                        VALUES (%s, %s);
                        """,
                        (security_id, classification_id),
                    )

                    cursor.execute(
                        """
                        INSERT INTO account_securities (
                            account_id, security_id, broker_symbol,
                            broker_security_id, opened_on, is_active
                        )
                        VALUES (%s, %s, %s, %s, %s, TRUE)
                        RETURNING id;
                        """,
                        (
                            account_id,
                            security_id,
                            broker_symbol.strip() or None
                            if isinstance(broker_symbol, str) else None,
                            broker_security_id.strip() or None
                            if isinstance(broker_security_id, str) else None,
                            opened_on or None,
                        ),
                    )
                    security["account_security_id"] = cursor.fetchone()["id"]
                    security["classification_id"] = classification_id
                    return jsonify(_json_safe(security)), 201

        except PsycopgError as error:
            app.logger.exception("Failed to create security")
            if getattr(error, "sqlstate", None) == "23505":
                return jsonify({
                    "error": "A conflicting security or account relationship already exists"
                }), 409
            if getattr(error, "sqlstate", None) == "23503":
                return jsonify({
                    "error": "The selected account or classification does not exist"
                }), 400
            return jsonify({"error": "unable to create security"}), 400

        except ValueError:
            return jsonify({"error": "opened_on must be a valid date"}), 400

    @app.put("/api/manage/securities/<int:security_id>")
    def update_security(security_id):
        data = request.get_json(silent=True) or {}

        name = data.get("name")
        instrument_type = data.get("instrument_type")
        currency = data.get("currency")
        classification_id = data.get("classification_id")
        symbol = data.get("symbol")
        exchange = data.get("exchange")
        country = data.get("country")
        broker_symbol = data.get("broker_symbol")
        broker_security_id = data.get("broker_security_id")
        opened_on = data.get("opened_on")
        is_active = data.get("is_active")

        if opened_on in ("", None):
            opened_on = None
        elif not isinstance(opened_on, str):
            return jsonify({
                "error": "opened_on must be a date in YYYY-MM-DD format"
            }), 400
        else:
            try:
                parsed_date = date.fromisoformat(opened_on)
                if parsed_date.isoformat() != opened_on:
                    raise ValueError
                opened_on = parsed_date
            except ValueError:
                return jsonify({
                    "error": "opened_on must be a valid date in YYYY-MM-DD format"
                }), 400

        allowed_types = {
            "STOCK", "ETF", "MUTUAL_FUND", "PRECIOUS_METAL"
        }

        if not isinstance(name, str) or not name.strip():
            return jsonify({"error": "name is required"}), 400
        if not isinstance(instrument_type, str) or instrument_type not in allowed_types:
            return jsonify({"error": "invalid instrument_type"}), 400
        if not isinstance(currency, str) or len(currency.strip()) != 3:
            return jsonify({"error": "currency must be a 3-letter currency code"}), 400
        if not isinstance(is_active, bool):
            return jsonify({"error": "is_active must be true or false"}), 400

        try:
            classification_id = int(classification_id)
            if classification_id <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"error": "classification_id must be a positive integer"}), 400

        try:
            with connect(_database_url(), row_factory=dict_row) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT id
                        FROM securities
                        WHERE id = %s
                        FOR UPDATE;
                        """,
                        (security_id,),
                    )
                    if cursor.fetchone() is None:
                        return jsonify({"error": "security not found"}), 404

                    cursor.execute(
                        """
                        SELECT
                            a.name AS account_name,
                            ase.id AS account_security_id
                        FROM account_securities ase
                        JOIN accounts a ON a.id = ase.account_id
                        WHERE ase.security_id = %s
                        FOR UPDATE OF ase;
                        """,
                        (security_id,),
                    )
                    associated_accounts = cursor.fetchall()

                    if len(associated_accounts) != 1:
                        return jsonify({
                            "error": (
                                "security must have exactly one account association "
                                "before it can be edited"
                            )
                        }), 409

                    account_name = associated_accounts[0]["account_name"]
                    account_security_id = associated_accounts[0]["account_security_id"]
                    country_value = (country or "").strip().lower() if isinstance(country, str) else ""

                    if account_name == "Zerodha":
                        allowed_account_types = {"STOCK", "ETF"}
                        expected_currency = "INR"
                        expected_country = "india"
                    elif account_name == "INDmoney":
                        allowed_account_types = {"STOCK", "ETF"}
                        expected_currency = "USD"
                        expected_country = "usa"
                        if country_value in {"us", "united states", "united states of america"}:
                            country_value = "usa"
                    elif account_name == "Paytm Money":
                        allowed_account_types = {"MUTUAL_FUND"}
                        expected_currency = "INR"
                        expected_country = "india"
                    else:
                        return jsonify({
                            "error": "unsupported account for security management"
                        }), 409

                    if instrument_type not in allowed_account_types:
                        return jsonify({
                            "error": f"{account_name} does not support this instrument type"
                        }), 400

                    if currency.strip().upper() != expected_currency:
                        return jsonify({
                            "error": f"{account_name} requires currency {expected_currency}"
                        }), 400

                    if country_value != expected_country:
                        return jsonify({
                            "error": f"{account_name} requires country "
                                     f"{'USA' if expected_country == 'usa' else 'India'}"
                        }), 400

                    country = "USA" if expected_country == "usa" else "India"

                    cursor.execute(
                        """
                        SELECT c.id
                        FROM classifications c
                        WHERE c.id = %s
                          AND c.is_active = TRUE
                          AND NOT EXISTS (
                              SELECT 1 FROM classifications child
                              WHERE child.parent_id = c.id
                          );
                        """,
                        (classification_id,),
                    )
                    if cursor.fetchone() is None:
                        return jsonify({
                            "error": "an active leaf classification is required"
                        }), 400

                    if is_active:
                        cursor.execute(
                            """
                            SELECT 1
                            FROM account_securities ase
                            JOIN accounts a ON a.id = ase.account_id
                            WHERE ase.security_id = %s
                              AND ase.is_active = TRUE
                              AND a.is_active = TRUE
                              AND a.account_role = 'PORTFOLIO'
                            LIMIT 1;
                            """,
                            (security_id,),
                        )
                        if cursor.fetchone() is None:
                            return jsonify({
                                "error": (
                                    "an active portfolio account relationship "
                                    "is required to activate a security"
                                )
                            }), 409

                    if not is_active:
                        cursor.execute(
                            """
                            SELECT 1
                            FROM account_securities
                            WHERE security_id = %s
                              AND is_active = TRUE
                            LIMIT 1;
                            """,
                            (security_id,),
                        )
                        if cursor.fetchone() is not None:
                            return jsonify({
                                "error": "remove or deactivate active account relationships before deactivating this security"
                            }), 409

                    cursor.execute(
                        """
                        UPDATE securities
                        SET name = %s,
                            symbol = %s,
                            instrument_type = %s,
                            currency = %s,
                            exchange = %s,
                            country = %s,
                            is_active = %s,
                            updated_at = NOW()
                        WHERE id = %s
                        RETURNING id, name, symbol, instrument_type,
                                  currency, exchange, country, is_active;
                        """,
                        (
                            name.strip(),
                            symbol.strip() or None if isinstance(symbol, str) else None,
                            instrument_type,
                            currency.strip().upper(),
                            exchange.strip() or None if isinstance(exchange, str) else None,
                            country.strip() or None if isinstance(country, str) else None,
                            is_active,
                            security_id,
                        ),
                    )
                    security = cursor.fetchone()

                    cursor.execute(
                        """
                        UPDATE account_securities
                        SET broker_symbol = %s,
                            broker_security_id = %s,
                            opened_on = %s
                        WHERE id = %s
                          AND security_id = %s;
                        """,
                        (
                            broker_symbol.strip() or None
                            if isinstance(broker_symbol, str) else None,
                            broker_security_id.strip() or None
                            if isinstance(broker_security_id, str) else None,
                            opened_on,
                            account_security_id,
                            security_id,
                        ),
                    )

                    cursor.execute(
                        """
                        DELETE FROM security_classifications
                        WHERE security_id = %s;
                        """,
                        (security_id,),
                    )
                    cursor.execute(
                        """
                        INSERT INTO security_classifications (
                            security_id, classification_id
                        )
                        VALUES (%s, %s);
                        """,
                        (security_id, classification_id),
                    )
                    security["classification_id"] = classification_id
                    return jsonify(_json_safe(security))

        except PsycopgError as error:
            app.logger.exception("Failed to update security")
            if getattr(error, "sqlstate", None) == "23505":
                return jsonify({"error": "conflicting security data"}), 409
            if getattr(error, "sqlstate", None) == "23503":
                return jsonify({
                    "error": "the selected classification does not exist"
                }), 400
            return jsonify({"error": "unable to update security"}), 400

    @app.post("/api/manage/security-accounts/<int:account_security_id>/deactivate")
    def deactivate_security_account(account_security_id):
        try:
            with connect(_database_url(), row_factory=dict_row) as connection:
                with connection.cursor() as cursor:
                    # Lock the relationship and its security so the
                    # changes are handled in one transaction.
                    cursor.execute(
                        """
                        SELECT
                            ase.id AS account_security_id,
                            ase.security_id,
                            ase.is_active AS relationship_is_active,
                            s.is_active AS security_is_active
                        FROM account_securities ase
                        JOIN securities s ON s.id = ase.security_id
                        WHERE ase.id = %s
                        FOR UPDATE OF ase, s;
                        """,
                        (account_security_id,),
                    )
                    relationship = cursor.fetchone()

                    if relationship is None:
                        return jsonify({
                            "error": "account-security relationship not found"
                        }), 404

                    security_id = relationship["security_id"]

                    if not relationship["relationship_is_active"]:
                        return jsonify({
                            "account_security_id": account_security_id,
                            "security_id": security_id,
                            "relationship_is_active": False,
                            "security_is_active": relationship["security_is_active"],
                            "message": "relationship is already inactive",
                        })

                    # Use the running transaction calculation so corporate
                    # actions such as splits are reflected in the quantity.
                    cursor.execute(
                        """
                        SELECT quantity_held
                        FROM account_security_transaction_calculations
                        WHERE account_security_id = %s
                        ORDER BY transaction_sequence DESC
                        LIMIT 1;
                        """,
                        (account_security_id,),
                    )
                    holding = cursor.fetchone()

                    if holding is not None and holding["quantity_held"] != 0:
                        return jsonify({
                            "error": (
                                "Cannot deactivate this relationship while a "
                                f"non-zero holding remains "
                                f"({holding['quantity_held']} shares/units). "
                                "Record the disposal or correct the transactions first."
                            ),
                            "quantity_held": str(holding["quantity_held"]),
                        }), 409

                    cursor.execute(
                        """
                        UPDATE account_securities
                        SET is_active = FALSE
                        WHERE id = %s;
                        """,
                        (account_security_id,),
                    )

                    # Keep the security active while any account
                    # relationship remains active.
                    cursor.execute(
                        """
                        SELECT EXISTS (
                            SELECT 1
                            FROM account_securities ase
                            JOIN accounts a ON a.id = ase.account_id
                            WHERE ase.security_id = %s
                              AND ase.is_active = TRUE
                              AND a.is_active = TRUE
                              AND a.account_role = 'PORTFOLIO'
                        ) AS has_active_relationship;
                        """,
                        (security_id,),
                    )
                    has_active_relationship = cursor.fetchone()[
                        "has_active_relationship"
                    ]

                    auto_deactivated = False

                    if not has_active_relationship:
                        cursor.execute(
                            """
                            UPDATE securities
                            SET is_active = FALSE,
                                updated_at = NOW()
                            WHERE id = %s
                              AND is_active = TRUE;
                            """,
                            (security_id,),
                        )
                        auto_deactivated = cursor.rowcount == 1

                    return jsonify({
                        "account_security_id": account_security_id,
                        "security_id": security_id,
                        "relationship_is_active": False,
                        "security_is_active": bool(has_active_relationship),
                        "security_auto_deactivated": auto_deactivated,
                    })

        except PsycopgError:
            app.logger.exception(
                "Failed to deactivate account-security relationship"
            )
            return jsonify({
                "error": "unable to deactivate account-security relationship"
            }), 400

    @app.post("/api/manage/security-accounts/<int:account_security_id>/activate")
    def activate_security_account(account_security_id):
        try:
            with connect(_database_url(), row_factory=dict_row) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT
                            ase.id AS account_security_id,
                            ase.security_id,
                            ase.is_active AS relationship_is_active,
                            a.is_active AS account_is_active,
                            a.account_role,
                            s.is_active AS security_is_active
                        FROM account_securities ase
                        JOIN accounts a ON a.id = ase.account_id
                        JOIN securities s ON s.id = ase.security_id
                        WHERE ase.id = %s
                        FOR UPDATE OF ase, s;
                        """,
                        (account_security_id,),
                    )
                    relationship = cursor.fetchone()

                    if relationship is None:
                        return jsonify({
                            "error": "account-security relationship not found"
                        }), 404

                    if (
                        not relationship["account_is_active"]
                        or relationship["account_role"] != "PORTFOLIO"
                    ):
                        return jsonify({
                            "error": (
                                "An active portfolio account is required "
                                "to activate this relationship."
                            )
                        }), 409

                    cursor.execute(
                        """
                        UPDATE account_securities
                        SET is_active = TRUE
                        WHERE id = %s;
                        """,
                        (account_security_id,),
                    )

                    cursor.execute(
                        """
                        UPDATE securities
                        SET is_active = TRUE,
                            updated_at = NOW()
                        WHERE id = %s;
                        """,
                        (relationship["security_id"],),
                    )

                    return jsonify({
                        "account_security_id": account_security_id,
                        "security_id": relationship["security_id"],
                        "relationship_is_active": True,
                        "security_is_active": True,
                        "message": "Account-security relationship activated.",
                    })

        except PsycopgError:
            app.logger.exception(
                "Failed to activate account-security relationship"
            )
            return jsonify({
                "error": "unable to activate account-security relationship"
            }), 400


    @app.get("/api/manage/account-transactions")
    def manage_account_transactions():
        """List account deposits and withdrawals with optional filters."""
        try:
            account_id = request.args.get("account_id", type=int)
            transaction_type = request.args.get(
                "transaction_type", ""
            ).strip().upper()
            page = request.args.get("page", default=1, type=int)
            page_size = request.args.get("page_size", default=25, type=int)

            if page is None or page < 1:
                return jsonify({"error": "page must be a positive integer"}), 400
            if page_size is None or not 1 <= page_size <= 100:
                return jsonify({
                    "error": "page_size must be between 1 and 100"
                }), 400
            if account_id is not None and account_id <= 0:
                return jsonify({"error": "account_id must be positive"}), 400
            if transaction_type and transaction_type not in {
                "DEPOSIT", "WITHDRAWAL"
            }:
                return jsonify({
                    "error": "transaction_type must be DEPOSIT or WITHDRAWAL"
                }), 400

            conditions = [
                "a.account_role = 'PORTFOLIO'",
                "a.is_active = TRUE",
                "act.transaction_type IN ('DEPOSIT', 'WITHDRAWAL')",
            ]
            params = []

            if account_id is not None:
                conditions.append("a.id = %s")
                params.append(account_id)
            if transaction_type:
                conditions.append("act.transaction_type = %s")
                params.append(transaction_type)

            where_clause = "WHERE " + " AND ".join(conditions)
            offset = (page - 1) * page_size

            with connect(
                _database_url(), row_factory=dict_row
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        SELECT
                            act.id AS transaction_id,
                            act.account_id,
                            a.name AS account_name,
                            act.transaction_date,
                            act.transaction_type,
                            act.amount,
                            act.currency,
                            act.description,
                            act.reference,
                            COUNT(*) OVER() AS total_count
                        FROM account_cash_transactions act
                        JOIN accounts a ON a.id = act.account_id
                        {where_clause}
                        ORDER BY act.transaction_date DESC, act.id DESC
                        LIMIT %s OFFSET %s;
                        """,
                        (*params, page_size, offset),
                    )
                    rows = cursor.fetchall()

            total = int(rows[0]["total_count"]) if rows else 0
            for row in rows:
                row.pop("total_count", None)

            return jsonify(_json_safe({
                "items": rows,
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": (total + page_size - 1) // page_size,
            }))

        except PsycopgError:
            app.logger.exception("Failed to fetch account transactions")
            return jsonify({
                "error": "unable to fetch account transactions"
            }), 500

    @app.post("/api/manage/account-transactions")
    def create_account_transaction():
        """Record a deposit or withdrawal in an active portfolio account."""
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({
                "error": "request body must be a JSON object"
            }), 400

        from decimal import InvalidOperation

        try:
            account_id = payload.get("account_id")
            if (
                isinstance(account_id, bool)
                or not isinstance(account_id, int)
                or account_id <= 0
            ):
                raise ValueError("account_id must be a positive integer")

            transaction_type = str(
                payload.get("transaction_type", "")
            ).strip().upper()
            if transaction_type not in {"DEPOSIT", "WITHDRAWAL"}:
                raise ValueError(
                    "transaction_type must be DEPOSIT or WITHDRAWAL"
                )

            raw_date = payload.get("transaction_date")
            if not isinstance(raw_date, str) or not raw_date.strip():
                raise ValueError("transaction_date is required")
            try:
                transaction_date = date.fromisoformat(raw_date.strip())
            except ValueError:
                raise ValueError(
                    "transaction_date must use YYYY-MM-DD format"
                )

            raw_amount = payload.get("amount")
            if raw_amount is None or raw_amount == "":
                raise ValueError("amount is required")
            try:
                amount = Decimal(str(raw_amount))
            except (InvalidOperation, ValueError):
                raise ValueError("amount must be a valid number")
            if not amount.is_finite() or amount <= 0:
                raise ValueError("amount must be a finite number greater than zero")
            if amount.as_tuple().exponent < -2:
                raise ValueError("amount can have at most two decimal places")

            description = payload.get("description")
            reference = payload.get("reference")
            if description is not None and not isinstance(description, str):
                raise ValueError("description must be text or null")
            if reference is not None and not isinstance(reference, str):
                raise ValueError("reference must be text or null")
            if description is not None and len(description) > 2000:
                raise ValueError("description cannot exceed 2000 characters")
            if reference is not None and len(reference) > 200:
                raise ValueError("reference cannot exceed 200 characters")

            with connect(
                _database_url(), row_factory=dict_row
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT id, name, base_currency
                        FROM accounts
                        WHERE id = %s
                          AND account_role = 'PORTFOLIO'
                          AND is_active = TRUE
                        FOR SHARE;
                        """,
                        (account_id,),
                    )
                    account = cursor.fetchone()

                    if account is None:
                        return jsonify({
                            "error": "account must be an active portfolio account"
                        }), 400

                    cursor.execute(
                        """
                        INSERT INTO account_cash_transactions (
                            account_id,
                            transaction_date,
                            transaction_type,
                            amount,
                            currency,
                            description,
                            reference
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        RETURNING id;
                        """,
                        (
                            account_id,
                            transaction_date,
                            transaction_type,
                            amount,
                            account["base_currency"],
                            description.strip() if description else None,
                            reference.strip() if reference else None,
                        ),
                    )
                    transaction_id = cursor.fetchone()["id"]

            return jsonify({
                "message": "account transaction created",
                "transaction_id": transaction_id,
            }), 201

        except ValueError as error:
            return jsonify({"error": str(error)}), 400
        except PsycopgError:
            app.logger.exception("Failed to create account transaction")
            return jsonify({
                "error": "unable to create account transaction"
            }), 500

    @app.put("/api/manage/account-transactions/<int:transaction_id>")
    def update_account_transaction(transaction_id):
        """Update an existing deposit or withdrawal."""
        from decimal import InvalidOperation

        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({
                "error": "request body must be a JSON object"
            }), 400

        try:
            account_id = payload.get("account_id")
            if (
                isinstance(account_id, bool)
                or not isinstance(account_id, int)
                or account_id <= 0
            ):
                raise ValueError("account_id must be a positive integer")

            transaction_type = str(
                payload.get("transaction_type", "")
            ).strip().upper()
            if transaction_type not in {"DEPOSIT", "WITHDRAWAL"}:
                raise ValueError(
                    "transaction_type must be DEPOSIT or WITHDRAWAL"
                )

            raw_date = payload.get("transaction_date")
            if not isinstance(raw_date, str) or not raw_date.strip():
                raise ValueError("transaction_date is required")
            try:
                transaction_date = date.fromisoformat(raw_date.strip())
            except ValueError:
                raise ValueError(
                    "transaction_date must use YYYY-MM-DD format"
                )

            raw_amount = payload.get("amount")
            if raw_amount is None or raw_amount == "":
                raise ValueError("amount is required")
            try:
                amount = Decimal(str(raw_amount))
            except (InvalidOperation, ValueError):
                raise ValueError("amount must be a valid number")
            if not amount.is_finite() or amount <= 0:
                raise ValueError(
                    "amount must be a finite number greater than zero"
                )
            if amount.as_tuple().exponent < -2:
                raise ValueError(
                    "amount can have at most two decimal places"
                )

            description = payload.get("description")
            reference = payload.get("reference")
            if description is not None and not isinstance(description, str):
                raise ValueError("description must be text or null")
            if reference is not None and not isinstance(reference, str):
                raise ValueError("reference must be text or null")
            if description is not None and len(description) > 2000:
                raise ValueError(
                    "description cannot exceed 2000 characters"
                )
            if reference is not None and len(reference) > 200:
                raise ValueError(
                    "reference cannot exceed 200 characters"
                )

            with connect(
                _database_url(), row_factory=dict_row
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT id
                        FROM accounts
                        WHERE id = %s
                          AND account_role = 'PORTFOLIO'
                          AND is_active = TRUE;
                        """,
                        (account_id,),
                    )
                    account = cursor.fetchone()
                    if account is None:
                        raise ValueError(
                            "account must be an active portfolio account"
                        )

                    cursor.execute(
                        """
                        UPDATE account_cash_transactions AS act
                        SET account_id = %s,
                            transaction_date = %s,
                            transaction_type = %s,
                            amount = %s,
                            currency = a.base_currency,
                            description = %s,
                            reference = %s
                        FROM accounts AS a
                        WHERE act.id = %s
                          AND act.transaction_type IN (
                              'DEPOSIT', 'WITHDRAWAL'
                          )
                          AND a.id = %s
                        RETURNING act.id;
                        """,
                        (
                            account_id,
                            transaction_date,
                            transaction_type,
                            amount,
                            description.strip() if description else None,
                            reference.strip() if reference else None,
                            transaction_id,
                            account_id,
                        ),
                    )
                    updated = cursor.fetchone()

            if updated is None:
                return jsonify({
                    "error": "account transaction not found"
                }), 404

            return jsonify({
                "message": "account transaction updated",
                "transaction_id": transaction_id,
            })

        except ValueError as error:
            return jsonify({"error": str(error)}), 400
        except PsycopgError:
            app.logger.exception("Failed to update account transaction")
            return jsonify({
                "error": "unable to update account transaction"
            }), 500

    @app.delete("/api/manage/account-transactions/<int:transaction_id>")
    def delete_account_transaction(transaction_id):
        """Delete an existing deposit or withdrawal."""
        try:
            with connect(
                _database_url(), row_factory=dict_row
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        DELETE FROM account_cash_transactions
                        WHERE id = %s
                          AND transaction_type IN (
                              'DEPOSIT', 'WITHDRAWAL'
                          )
                        RETURNING id;
                        """,
                        (transaction_id,),
                    )
                    deleted = cursor.fetchone()

            if deleted is None:
                return jsonify({
                    "error": "account transaction not found"
                }), 404

            return jsonify({
                "message": "account transaction deleted",
                "transaction_id": transaction_id,
            })

        except PsycopgError:
            app.logger.exception("Failed to delete account transaction")
            return jsonify({
                "error": "unable to delete account transaction"
            }), 500

    @app.get("/api/manage/wallet-cash")
    def get_wallet_cash():
        """Return current wallet cash balances for supported broker accounts."""
        try:
            rows = _fetch_all("""
                SELECT
                    w.account_id,
                    a.name AS account_name,
                    w.cash_balance,
                    a.base_currency AS currency,
                    w.updated_at
                FROM account_wallet_cash w
                JOIN accounts a ON a.id = w.account_id
                WHERE w.account_id IN (1, 2)
                ORDER BY w.account_id;
            """)

            return jsonify(_json_safe({"items": rows}))

        except PsycopgError:
            app.logger.exception("Failed to fetch wallet cash")
            return jsonify({
                "error": "unable to fetch wallet cash"
            }), 500

    @app.put("/api/manage/wallet-cash/<int:account_id>")
    def update_wallet_cash(account_id):
        """Set the current wallet cash balance for a supported broker."""
        from decimal import InvalidOperation

        if account_id not in {1, 2}:
            return jsonify({
                "error": "wallet cash is supported only for Zerodha and INDmoney"
            }), 400

        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({
                "error": "request body must be a JSON object"
            }), 400

        raw_balance = payload.get("cash_balance")
        if raw_balance is None or raw_balance == "":
            return jsonify({"error": "cash_balance is required"}), 400

        try:
            balance = Decimal(str(raw_balance))
        except (InvalidOperation, ValueError):
            return jsonify({"error": "cash_balance must be a valid number"}), 400

        if not balance.is_finite() or balance < 0:
            return jsonify({
                "error": "cash_balance must be a finite, non-negative number"
            }), 400

        if balance.as_tuple().exponent < -2:
            return jsonify({
                "error": "cash_balance can have at most two decimal places"
            }), 400

        try:
            with connect(
                _database_url(), row_factory=dict_row
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE account_wallet_cash AS w
                        SET cash_balance = %s,
                            updated_at = NOW()
                        FROM accounts AS a
                        WHERE w.account_id = %s
                          AND a.id = w.account_id
                          AND a.is_active = TRUE
                          AND a.account_role = 'PORTFOLIO'
                        RETURNING
                            w.account_id,
                            a.name AS account_name,
                            w.cash_balance,
                            a.base_currency AS currency,
                            w.updated_at;
                        """,
                        (balance, account_id),
                    )
                    row = cursor.fetchone()

            if row is None:
                return jsonify({
                    "error": "wallet cash account not found or inactive"
                }), 404

            return jsonify({
                "message": "wallet cash updated",
                "item": _json_safe(row),
            })

        except PsycopgError:
            app.logger.exception("Failed to update wallet cash")
            return jsonify({
                "error": "unable to update wallet cash"
            }), 500

    @app.get("/api/manage/security-transactions")
    def manage_security_transactions():
        # Read-only transaction history with optional filters and pagination.
        try:
            account_id = request.args.get("account_id", type=int)
            security_id = request.args.get("security_id", type=int)
            transaction_type = request.args.get("transaction_type", "").strip().upper()

            page = request.args.get("page", default=1, type=int)
            page_size = request.args.get("page_size", default=25, type=int)

            if page is None or page < 1:
                return jsonify({"error": "page must be a positive integer"}), 400

            if page_size is None or not 1 <= page_size <= 100:
                return jsonify({
                    "error": "page_size must be between 1 and 100"
                }), 400

            if account_id is not None and account_id <= 0:
                return jsonify({"error": "account_id must be positive"}), 400

            if security_id is not None and security_id <= 0:
                return jsonify({"error": "security_id must be positive"}), 400

            allowed_types = {"BUY", "SELL", "BONUS", "SPLIT"}
            if transaction_type and transaction_type not in allowed_types:
                return jsonify({
                    "error": "transaction_type must be BUY, SELL, BONUS, or SPLIT"
                }), 400

            conditions = []
            params = []

            if account_id is not None:
                conditions.append("a.id = %s")
                params.append(account_id)

            if security_id is not None:
                conditions.append("s.id = %s")
                params.append(security_id)

            if transaction_type:
                conditions.append("st.transaction_type = %s")
                params.append(transaction_type)

            where_clause = (
                "WHERE " + " AND ".join(conditions)
                if conditions else ""
            )

            offset = (page - 1) * page_size

            with connect(
                _database_url(),
                row_factory=dict_row
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                SELECT
                    st.id AS transaction_id,
                    st.account_security_id,
                    st.transaction_date,
                    st.transaction_type,
                    st.quantity,
                    st.price,
                    st.settlement_amount,
                    st.currency,
                    st.reference,
                    st.notes,
                    st.corporate_action_from,
                    st.corporate_action_to,
                    a.id AS account_id,
                    a.name AS account_name,
                    a.is_active AS account_is_active,
                    s.id AS security_id,
                    s.name AS security_name,
                    s.symbol,
                    s.instrument_type,
                    s.is_active AS security_is_active,
                    ase.is_active AS account_security_is_active,
                    calc.transaction_sequence,
                    calc.quantity_held,
                    calc.cost_basis,
                    calc.average_cost,
                    COUNT(*) OVER() AS total_count
                FROM security_transactions st
                JOIN account_securities ase
                    ON ase.id = st.account_security_id
                JOIN accounts a
                    ON a.id = ase.account_id
                JOIN securities s
                    ON s.id = ase.security_id
                LEFT JOIN account_security_transaction_calculations calc
                    ON calc.transaction_id = st.id
                {where_clause}
                ORDER BY st.transaction_date DESC, st.id DESC
                LIMIT %s OFFSET %s;
                        """,
                        (*params, page_size, offset),
                    )
                    rows = cursor.fetchall()

            total = int(rows[0]["total_count"]) if rows else 0

            # The window count is metadata, not part of each transaction.
            for row in rows:
                row.pop("total_count", None)

            return jsonify(_json_safe({
                "items": rows,
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": (total + page_size - 1) // page_size,
            }))

        except PsycopgError:
            app.logger.exception("Failed to fetch security transactions")
            return jsonify({
                "error": "unable to fetch security transactions"
            }), 500

    @app.post("/api/manage/security-transactions")
    def create_security_transaction():
        """Create a transaction and reject any resulting negative holding."""
        from decimal import InvalidOperation

        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "request body must be a JSON object"}), 400

        def parse_decimal(field, required=True):
            value = payload.get(field)
            if value is None or value == "":
                if required:
                    raise ValueError(f"{field} is required")
                return None
            try:
                number = Decimal(str(value))
            except (InvalidOperation, ValueError):
                raise ValueError(f"{field} must be a valid number")
            if not number.is_finite():
                raise ValueError(f"{field} must be a finite number")
            return number

        try:
            account_security_id = payload.get("account_security_id")
            if (
                isinstance(account_security_id, bool)
                or not isinstance(account_security_id, int)
                or account_security_id <= 0
            ):
                raise ValueError("account_security_id must be a positive integer")

            transaction_type = str(
                payload.get("transaction_type", "")
            ).strip().upper()

            if transaction_type not in {"BUY", "SELL", "BONUS", "SPLIT"}:
                raise ValueError(
                    "transaction_type must be BUY, SELL, BONUS, or SPLIT"
                )

            raw_date = payload.get("transaction_date")
            if not isinstance(raw_date, str) or not raw_date.strip():
                raise ValueError("transaction_date is required")
            try:
                transaction_date = date.fromisoformat(raw_date.strip())
            except ValueError:
                raise ValueError("transaction_date must use YYYY-MM-DD format")

            reference = payload.get("reference")
            notes = payload.get("notes")

            if reference is not None and not isinstance(reference, str):
                raise ValueError("reference must be text or null")
            if notes is not None and not isinstance(notes, str):
                raise ValueError("notes must be text or null")

            if transaction_type in {"BUY", "SELL"}:
                quantity = parse_decimal("quantity")
                price = parse_decimal("price")
                settlement = parse_decimal("settlement_amount", required=False)

                if quantity <= 0:
                    raise ValueError("quantity must be greater than zero")
                if price < 0:
                    raise ValueError("price cannot be negative")
                if settlement is None:
                    settlement = quantity * price
                if settlement < 0:
                    raise ValueError("settlement_amount cannot be negative")

                action_from = None
                action_to = None
            else:
                quantity = None
                price = None
                settlement = None
                action_from = parse_decimal("corporate_action_from")
                action_to = parse_decimal("corporate_action_to")

                if action_from <= 0 or action_to <= 0:
                    raise ValueError(
                        "corporate-action ratios must be greater than zero"
                    )

            with connect(
                _database_url(),
                row_factory=dict_row
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT
                            ase.id,
                            s.currency,
                            a.account_role,
                            a.is_active AS account_is_active,
                            ase.is_active AS relationship_is_active,
                            s.is_active AS security_is_active
                        FROM account_securities ase
                        JOIN accounts a ON a.id = ase.account_id
                        JOIN securities s ON s.id = ase.security_id
                        WHERE ase.id = %s
                        FOR UPDATE OF ase
                        """,
                        (account_security_id,),
                    )
                    relationship = cursor.fetchone()

                    if relationship is None:
                        return jsonify({
                            "error": "account-security relationship not found"
                        }), 404

                    if (
                        not relationship["account_is_active"]
                        or relationship["account_role"] != "PORTFOLIO"
                        or not relationship["relationship_is_active"]
                        or not relationship["security_is_active"]
                    ):
                        return jsonify({
                            "error": (
                                "new transactions require an active security "
                                "and an active portfolio account relationship"
                            )
                        }), 409

                    cursor.execute(
                        """
                        INSERT INTO security_transactions (
                            account_security_id,
                            transaction_date,
                            transaction_type,
                            quantity,
                            price,
                            settlement_amount,
                            currency,
                            reference,
                            notes,
                            corporate_action_from,
                            corporate_action_to
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (
                            account_security_id,
                            transaction_date,
                            transaction_type,
                            quantity,
                            price,
                            settlement,
                            relationship["currency"],
                            reference,
                            notes,
                            action_from,
                            action_to,
                        ),
                    )
                    transaction_id = cursor.fetchone()["id"]

                    # Validate the entire timeline, not just the new row.
                    cursor.execute(
                        """
                        SELECT
                            transaction_id,
                            transaction_date,
                            transaction_type,
                            quantity_held
                        FROM account_security_transaction_calculations
                        WHERE account_security_id = %s
                          AND quantity_held < 0
                        ORDER BY transaction_date, transaction_sequence
                        LIMIT 1
                        """,
                        (account_security_id,),
                    )
                    invalid_row = cursor.fetchone()

                    if invalid_row is not None:
                        connection.rollback()
                        return jsonify({
                            "error": (
                                "transaction rejected because it would cause "
                                "negative holdings in the transaction history"
                            ),
                            "conflicting_transaction_date": (
                                invalid_row["transaction_date"].isoformat()
                            ),
                            "conflicting_transaction_type": (
                                invalid_row["transaction_type"]
                            ),
                        }), 409

            return jsonify({
                "message": "transaction created",
                "transaction_id": transaction_id,
            }), 201

        except ValueError as error:
            return jsonify({"error": str(error)}), 400
        except PsycopgError:
            app.logger.exception("Failed to create security transaction")
            return jsonify({
                "error": "unable to create security transaction"
            }), 400


    @app.put("/api/manage/security-transactions/<int:transaction_id>")
    def update_security_transaction(transaction_id):
        """Update a transaction and reject negative holdings anywhere in history."""
        from decimal import InvalidOperation

        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "request body must be a JSON object"}), 400

        def parse_decimal(field, required=True):
            value = payload.get(field)
            if value is None or value == "":
                if required:
                    raise ValueError(f"{field} is required")
                return None
            try:
                number = Decimal(str(value))
            except (InvalidOperation, ValueError):
                raise ValueError(f"{field} must be a valid number")
            if not number.is_finite():
                raise ValueError(f"{field} must be a finite number")
            return number

        try:
            transaction_type = str(
                payload.get("transaction_type", "")
            ).strip().upper()
            if transaction_type not in {"BUY", "SELL", "BONUS", "SPLIT"}:
                raise ValueError(
                    "transaction_type must be BUY, SELL, BONUS, or SPLIT"
                )

            raw_date = payload.get("transaction_date")
            if not isinstance(raw_date, str) or not raw_date.strip():
                raise ValueError("transaction_date is required")
            try:
                transaction_date = date.fromisoformat(raw_date.strip())
            except ValueError:
                raise ValueError("transaction_date must use YYYY-MM-DD format")

            reference = payload.get("reference")
            notes = payload.get("notes")
            if reference is not None and not isinstance(reference, str):
                raise ValueError("reference must be text or null")
            if notes is not None and not isinstance(notes, str):
                raise ValueError("notes must be text or null")
            if reference is not None and len(reference) > 200:
                raise ValueError("reference cannot exceed 200 characters")

            if transaction_type in {"BUY", "SELL"}:
                quantity = parse_decimal("quantity")
                price = parse_decimal("price")
                settlement = parse_decimal("settlement_amount", required=False)
                if quantity <= 0:
                    raise ValueError("quantity must be greater than zero")
                if price < 0:
                    raise ValueError("price cannot be negative")
                if settlement is None:
                    settlement = quantity * price
                if settlement < 0:
                    raise ValueError("settlement_amount cannot be negative")
                action_from = None
                action_to = None
            else:
                quantity = price = settlement = None
                action_from = parse_decimal("corporate_action_from")
                action_to = parse_decimal("corporate_action_to")
                if action_from <= 0 or action_to <= 0:
                    raise ValueError(
                        "corporate-action ratios must be greater than zero"
                    )

            with connect(
                _database_url(), row_factory=dict_row
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT
                            st.id,
                            st.account_security_id,
                            ase.is_active AS relationship_is_active,
                            a.is_active AS account_is_active,
                            a.account_role,
                            s.is_active AS security_is_active
                        FROM security_transactions st
                        JOIN account_securities ase
                            ON ase.id = st.account_security_id
                        JOIN accounts a ON a.id = ase.account_id
                        JOIN securities s ON s.id = ase.security_id
                        WHERE st.id = %s
                        FOR UPDATE OF st, ase
                        """,
                        (transaction_id,),
                    )
                    existing = cursor.fetchone()

                    if existing is None:
                        return jsonify({"error": "transaction not found"}), 404

                    if (
                        not existing["account_is_active"]
                        or existing["account_role"] != "PORTFOLIO"
                    ):
                        return jsonify({
                            "error": "transaction account is not an active portfolio account"
                        }), 409

                    account_security_id = existing["account_security_id"]

                    cursor.execute(
                        """
                        UPDATE security_transactions
                        SET transaction_date = %s,
                            transaction_type = %s,
                            quantity = %s,
                            price = %s,
                            settlement_amount = %s,
                            reference = %s,
                            notes = %s,
                            corporate_action_from = %s,
                            corporate_action_to = %s
                        WHERE id = %s
                        """,
                        (
                            transaction_date, transaction_type, quantity,
                            price, settlement, reference, notes,
                            action_from, action_to, transaction_id,
                        ),
                    )

                    cursor.execute(
                        """
                        SELECT transaction_id, transaction_date,
                               transaction_type, quantity_held
                        FROM account_security_transaction_calculations
                        WHERE account_security_id = %s
                          AND quantity_held < 0
                        ORDER BY transaction_date, transaction_sequence
                        LIMIT 1
                        """,
                        (account_security_id,),
                    )
                    invalid_row = cursor.fetchone()

                    if invalid_row is not None:
                        connection.rollback()
                        return jsonify({
                            "error": (
                                "edit rejected because it would cause negative "
                                "holdings in the transaction history"
                            ),
                            "conflicting_transaction_date":
                                invalid_row["transaction_date"].isoformat(),
                            "conflicting_transaction_type":
                                invalid_row["transaction_type"],
                        }), 409

            return jsonify({
                "message": "transaction updated",
                "transaction_id": transaction_id,
            }), 200

        except ValueError as error:
            return jsonify({"error": str(error)}), 400
        except PsycopgError:
            app.logger.exception("Failed to update security transaction")
            return jsonify({
                "error": "unable to update security transaction"
            }), 400

    @app.delete("/api/manage/security-transactions/<int:transaction_id>")
    def delete_security_transaction(transaction_id):
        """Delete a transaction only if the remaining history stays valid."""
        try:
            with connect(
                _database_url(), row_factory=dict_row
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT
                            st.id,
                            st.account_security_id,
                            a.is_active AS account_is_active,
                            a.account_role
                        FROM security_transactions st
                        JOIN account_securities ase
                            ON ase.id = st.account_security_id
                        JOIN accounts a ON a.id = ase.account_id
                        WHERE st.id = %s
                        FOR UPDATE OF st, ase
                        """,
                        (transaction_id,),
                    )
                    existing = cursor.fetchone()

                    if existing is None:
                        return jsonify({"error": "transaction not found"}), 404

                    if (
                        not existing["account_is_active"]
                        or existing["account_role"] != "PORTFOLIO"
                    ):
                        return jsonify({
                            "error": "transaction account is not an active portfolio account"
                        }), 409

                    account_security_id = existing["account_security_id"]

                    cursor.execute(
                        "DELETE FROM security_transactions WHERE id = %s",
                        (transaction_id,),
                    )

                    cursor.execute(
                        """
                        SELECT transaction_id, transaction_date,
                               transaction_type, quantity_held
                        FROM account_security_transaction_calculations
                        WHERE account_security_id = %s
                          AND quantity_held < 0
                        ORDER BY transaction_date, transaction_sequence
                        LIMIT 1
                        """,
                        (account_security_id,),
                    )
                    invalid_row = cursor.fetchone()

                    if invalid_row is not None:
                        connection.rollback()
                        return jsonify({
                            "error": (
                                "deletion rejected because it would cause "
                                "negative holdings in the transaction history"
                            ),
                            "conflicting_transaction_date":
                                invalid_row["transaction_date"].isoformat(),
                            "conflicting_transaction_type":
                                invalid_row["transaction_type"],
                        }), 409

            return jsonify({
                "message": "transaction deleted",
                "transaction_id": transaction_id,
            }), 200

        except PsycopgError:
            app.logger.exception("Failed to delete security transaction")
            return jsonify({
                "error": "unable to delete security transaction"
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
