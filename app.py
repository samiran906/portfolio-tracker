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
