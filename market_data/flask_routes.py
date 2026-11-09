"""Flask endpoints for per-security market-data refreshes."""

from datetime import date

from flask import Blueprint, jsonify, request

from market_data.service import MarketDataService
from market_data.storage import MarketDataStorage


SUPPORTED_INSTRUMENT_TYPES = {"STOCK", "ETF", "MUTUAL_FUND"}

SECURITY_LOOKUP_SQL = """
    SELECT
        s.id AS security_id,
        s.name,
        s.symbol,
        s.instrument_type,
        s.currency,
        ase.id AS account_security_id,
        ase.broker_symbol,
        a.id AS account_id
    FROM securities s
    JOIN account_securities ase
        ON ase.security_id = s.id
       AND ase.is_active = TRUE
    JOIN accounts a
        ON a.id = ase.account_id
       AND a.is_active = TRUE
       AND a.account_role = 'PORTFOLIO'
    WHERE s.id = %s
      AND s.is_active = TRUE
    ORDER BY ase.id
"""


def create_market_data_blueprint(
    connection_factory,
    market_data_service=None,
):
    """Create the market-data Blueprint with injectable dependencies."""

    blueprint = Blueprint(
        "market_data",
        __name__,
        url_prefix="/api/market-data",
    )

    if market_data_service is None:
        storage = MarketDataStorage(connection_factory)
        market_data_service = MarketDataService(storage)

    def load_security(security_id):
        """Load one unambiguous active security/account association."""

        with connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(SECURITY_LOOKUP_SQL, (security_id,))
                rows = cursor.fetchall()

        if not rows:
            return None, (
                jsonify({
                    "error": (
                        "No active security with an active portfolio "
                        "account association was found."
                    )
                }),
                404,
            )

        if len(rows) > 1:
            return None, (
                jsonify({
                    "error": (
                        "This security has multiple active portfolio "
                        "account associations. The security-level refresh "
                        "endpoint cannot determine which broker symbol "
                        "to use."
                    )
                }),
                409,
            )

        return rows[0], None

    def validate_security_instrument(security):
        instrument_type = str(
            security.get("instrument_type") or ""
        ).upper()

        if instrument_type not in SUPPORTED_INSTRUMENT_TYPES:
            return (
                jsonify({
                    "error": (
                        f"Market-data refresh is not supported for "
                        f"instrument type '{instrument_type}'."
                    )
                }),
                422,
            )

        return None

    def build_refresh_response(security_id, operation, result):
        payload = {
            "security_id": security_id,
            "operation": operation,
            "status": result.status,
            "records_written": result.records_written,
        }

        if result.error:
            payload["error"] = result.error

        http_status = (
            200 if result.status in {"success", "no_data"} else 502
        )

        return jsonify(payload), http_status

    @blueprint.post("/securities/<int:security_id>/history")
    def refresh_security_history(security_id):
        security, error_response = load_security(security_id)

        if error_response:
            return error_response

        instrument_error = validate_security_instrument(security)
        if instrument_error:
            return instrument_error

        data = request.get_json(silent=True)

        if not isinstance(data, dict):
            return jsonify({
                "error": "A JSON request body is required."
            }), 400

        start_value = data.get("start_date")
        end_value = data.get("end_date")

        if not isinstance(start_value, str):
            return jsonify({
                "error": "start_date is required in YYYY-MM-DD format."
            }), 400

        try:
            start_date = date.fromisoformat(start_value)
            if start_date.isoformat() != start_value:
                raise ValueError
        except ValueError:
            return jsonify({
                "error": "start_date must be a valid YYYY-MM-DD date."
            }), 400

        end_date = None

        if end_value is not None:
            if not isinstance(end_value, str):
                return jsonify({
                    "error": "end_date must be a YYYY-MM-DD date."
                }), 400

            try:
                end_date = date.fromisoformat(end_value)
                if end_date.isoformat() != end_value:
                    raise ValueError
            except ValueError:
                return jsonify({
                    "error": "end_date must be a valid YYYY-MM-DD date."
                }), 400

            if end_date < start_date:
                return jsonify({
                    "error": "end_date cannot be earlier than start_date."
                }), 400

        result = market_data_service.refresh_history_result(
            security,
            start_date,
            end_date,
        )

        return build_refresh_response(
            security_id,
            "history",
            result,
        )

    @blueprint.post("/securities/<int:security_id>/quote")
    def refresh_security_quote(security_id):
        security, error_response = load_security(security_id)

        if error_response:
            return error_response

        instrument_error = validate_security_instrument(security)
        if instrument_error:
            return instrument_error

        result = market_data_service.refresh_quote_result(security)

        return build_refresh_response(
            security_id,
            "quote",
            result,
        )

    return blueprint
