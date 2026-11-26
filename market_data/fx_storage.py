"""PostgreSQL persistence for historical foreign-exchange rates."""

from datetime import date

from market_data.fx_models import FxRateBar


class FxRateStorage:
    """Persist historical FX rates independently of security prices."""

    def __init__(self, connection_factory):
        self._connection_factory = connection_factory

    def get_latest_rate_date(
        self,
        base_currency: str = "USD",
        quote_currency: str = "INR",
    ) -> date | None:
        """Return the latest stored date for a currency pair."""

        base_currency = base_currency.strip().upper()
        quote_currency = quote_currency.strip().upper()

        if len(base_currency) != 3 or len(quote_currency) != 3:
            raise ValueError("Currency codes must contain three characters")

        if base_currency == quote_currency:
            raise ValueError("Currency pair must contain different currencies")

        sql = """
            SELECT MAX(rate_date) AS latest_rate_date
            FROM fx_rates
            WHERE base_currency = %s
              AND quote_currency = %s
        """

        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, (base_currency, quote_currency))
                row = cursor.fetchone()

        return row["latest_rate_date"] if row else None

    def save_history(self, bars: list[FxRateBar]) -> int:
        """Upsert daily rates; return the number of records submitted."""

        if not bars:
            return 0

        if any(not isinstance(bar, FxRateBar) for bar in bars):
            raise TypeError("All records must be FxRateBar instances")

        currency_pair = {
            (bar.base_currency, bar.quote_currency)
            for bar in bars
        }

        if len(currency_pair) != 1:
            raise ValueError("All records must belong to the same currency pair")

        sql = """
            INSERT INTO fx_rates (
                rate_date,
                base_currency,
                quote_currency,
                open_rate,
                high_rate,
                low_rate,
                close_rate,
                provider,
                fetched_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (base_currency, quote_currency, rate_date)
            DO UPDATE SET
                open_rate = EXCLUDED.open_rate,
                high_rate = EXCLUDED.high_rate,
                low_rate = EXCLUDED.low_rate,
                close_rate = EXCLUDED.close_rate,
                provider = EXCLUDED.provider,
                fetched_at = NOW()
        """

        values = [
            (
                bar.rate_date,
                bar.base_currency,
                bar.quote_currency,
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                "YAHOO",
            )
            for bar in bars
        ]

        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.executemany(sql, values)

        return len(values)
