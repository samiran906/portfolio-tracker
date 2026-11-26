-- Store historical foreign-exchange rates independently
-- from security market prices.
--
-- Rates are expressed as:
--   quote_currency units per one base_currency unit
--
-- Example:
--   USD / INR = 92.60 means 1 USD = 92.60 INR.

CREATE TABLE public.fx_rates (
    rate_date DATE NOT NULL,

    base_currency VARCHAR(3) NOT NULL,
    quote_currency VARCHAR(3) NOT NULL,

    open_rate NUMERIC(18, 8),
    high_rate NUMERIC(18, 8),
    low_rate NUMERIC(18, 8),
    close_rate NUMERIC(18, 8) NOT NULL,

    provider VARCHAR(32) NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_fx_rates
        PRIMARY KEY (base_currency, quote_currency, rate_date),

    CONSTRAINT chk_fx_rates_base_currency
        CHECK (base_currency ~ '^[A-Z]{3}$'),

    CONSTRAINT chk_fx_rates_quote_currency
        CHECK (quote_currency ~ '^[A-Z]{3}$'),

    CONSTRAINT chk_fx_rates_distinct_currencies
        CHECK (base_currency <> quote_currency),

    CONSTRAINT chk_fx_rates_positive_values
        CHECK (
            close_rate > 0
            AND (open_rate IS NULL OR open_rate > 0)
            AND (high_rate IS NULL OR high_rate > 0)
            AND (low_rate IS NULL OR low_rate > 0)
        ),

    CONSTRAINT chk_fx_rates_high_low
        CHECK (
            high_rate IS NULL
            OR low_rate IS NULL
            OR high_rate >= low_rate
        )
);

COMMENT ON TABLE public.fx_rates IS
    'Historical daily foreign-exchange rates, independent of security prices';

COMMENT ON COLUMN public.fx_rates.base_currency IS
    'Currency being converted from';

COMMENT ON COLUMN public.fx_rates.quote_currency IS
    'Currency being converted to';

COMMENT ON COLUMN public.fx_rates.close_rate IS
    'Daily closing rate: quote currency units per one base currency unit';
