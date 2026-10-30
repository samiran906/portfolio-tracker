"""PostgreSQL persistence for normalized market prices."""

from market_data.models import MarketQuote, PriceBar


class MarketDataStorage:
    """Persist daily prices and current quotes using an injected connection factory."""

    def __init__(self, connection_factory):
        self._connection_factory = connection_factory

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
