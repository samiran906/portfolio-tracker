"""PostgreSQL persistence for normalized market prices."""

from datetime import date
from market_data.models import MarketQuote, PriceBar


class MarketDataStorage:
    """Persist daily prices and current quotes using an injected connection factory."""

    def __init__(self, connection_factory):
        self._connection_factory = connection_factory


    def get_latest_price_dates(self, security_ids: list[int]) -> dict[int, date]:
        """Return the latest stored price date for each requested security."""
        if not security_ids:
            return {}

        if any(security_id <= 0 for security_id in security_ids):
            raise ValueError("All security IDs must be positive")

        sql = """
            SELECT
                security_id,
                MAX(price_date) AS latest_price_date
            FROM security_prices
            WHERE security_id = ANY(%s)
            GROUP BY security_id
        """

        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, (security_ids,))
                rows = cursor.fetchall()

        return {
            row["security_id"]: row["latest_price_date"]
            for row in rows
        }


    def get_active_market_data_securities(self) -> list[dict]:
        """Return active market-data securities and their portfolio associations."""
        sql = """
            SELECT
                s.id AS security_id,
                s.name,
                s.symbol,
                s.instrument_type,
                s.currency,
                ase.id AS account_security_id,
                ase.broker_symbol,
                a.id AS account_id,
                a.name AS account_name,
                COUNT(*) OVER (
                    PARTITION BY s.id
                ) AS active_association_count,
                transaction_dates.first_transaction_date
            FROM securities s
            JOIN account_securities ase
                ON ase.security_id = s.id
               AND ase.is_active = TRUE
            JOIN accounts a
                ON a.id = ase.account_id
               AND a.is_active = TRUE
               AND a.account_role = 'PORTFOLIO'
            LEFT JOIN (
                SELECT
                    ase_tx.security_id,
                    MIN(st.transaction_date) AS first_transaction_date
                FROM security_transactions st
                JOIN account_securities ase_tx
                    ON ase_tx.id = st.account_security_id
                GROUP BY ase_tx.security_id
            ) transaction_dates
                ON transaction_dates.security_id = s.id
            WHERE s.is_active = TRUE
              AND s.instrument_type IN ('STOCK', 'ETF', 'MUTUAL_FUND')
            ORDER BY s.id, ase.id
        """

        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql)
                rows = cursor.fetchall()

        return rows

    def save_history(self, security_id: int, bars: list[PriceBar]) -> int:
        """Upsert daily prices; return the number of records submitted for upsert."""
        if security_id <= 0:
            raise ValueError("security_id must be positive")

        if not bars:
            return 0

        sql = """
            INSERT INTO security_prices (
                security_id,
                price_date,
                open_price,
                high_price,
                low_price,
                close_price,
                currency
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (security_id, price_date)
            DO UPDATE SET
                open_price = EXCLUDED.open_price,
                high_price = EXCLUDED.high_price,
                low_price = EXCLUDED.low_price,
                close_price = EXCLUDED.close_price,
                currency = EXCLUDED.currency
        """

        values = [
            (
                security_id,
                bar.price_date,
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.currency,
            )
            for bar in bars
        ]

        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.executemany(sql, values)

        return len(values)

    def save_quote(self, security_id: int, quote: MarketQuote) -> None:
        """Upsert the latest quote without touching historical daily prices."""
        if security_id <= 0:
            raise ValueError("security_id must be positive")

        sql = """
            INSERT INTO security_quotes (
                security_id,
                price,
                quote_time,
                open_price,
                high_price,
                low_price,
                previous_close,
                currency,
                updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (security_id)
            DO UPDATE SET
                price = EXCLUDED.price,
                quote_time = EXCLUDED.quote_time,
                open_price = EXCLUDED.open_price,
                high_price = EXCLUDED.high_price,
                low_price = EXCLUDED.low_price,
                previous_close = EXCLUDED.previous_close,
                currency = EXCLUDED.currency,
                updated_at = NOW()
        """

        values = (
            security_id,
            quote.price,
            quote.quote_time,
            quote.open,
            quote.high,
            quote.low,
            quote.previous_close,
            quote.currency,
        )

        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, values)
