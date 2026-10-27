-- Return NULL when total-portfolio XIRR is undefined or the
-- Newton-Raphson calculation cannot safely proceed.
-- This preserves the existing function signature.

CREATE OR REPLACE FUNCTION public.get_total_portfolio_xirr_as_of_date(
    p_valuation_date date
)
RETURNS numeric
LANGUAGE plpgsql
AS $function$
DECLARE
    v_rate NUMERIC := 0.10;
    v_new_rate NUMERIC;
    v_npv NUMERIC;
    v_derivative NUMERIC;
    v_base_date DATE;
    v_iteration INTEGER;
    v_has_positive BOOLEAN;
    v_has_negative BOOLEAN;
BEGIN
    SELECT
        MIN(entry_date),
        BOOL_OR(amount > 0),
        BOOL_OR(amount < 0)
    INTO
        v_base_date,
        v_has_positive,
        v_has_negative
    FROM get_total_portfolio_xirr_cash_flows_as_of_date(
        p_valuation_date
    );

    IF v_base_date IS NULL
       OR COALESCE(v_has_positive, FALSE) = FALSE
       OR COALESCE(v_has_negative, FALSE) = FALSE
    THEN
        RETURN NULL;
    END IF;

    FOR v_iteration IN 1..100 LOOP
        SELECT
            SUM(
                amount /
                POWER(
                    1 + v_rate,
                    (entry_date - v_base_date) / 365.0
                )
            ),
            SUM(
                -((entry_date - v_base_date) / 365.0) *
                amount /
                POWER(
                    1 + v_rate,
                    ((entry_date - v_base_date) / 365.0) + 1
                )
            )
        INTO v_npv, v_derivative
        FROM get_total_portfolio_xirr_cash_flows_as_of_date(
            p_valuation_date
        );

        IF v_npv IS NULL THEN
            RETURN NULL;
        END IF;

        IF ABS(v_npv) < 0.000001 THEN
            RETURN v_rate;
        END IF;

        IF v_derivative IS NULL
           OR ABS(v_derivative) < 0.0000000001
        THEN
            RETURN NULL;
        END IF;

        v_new_rate := v_rate - (v_npv / v_derivative);

        IF v_new_rate <= -0.999999 THEN
            v_new_rate := (v_rate - 0.999999) / 2;
        END IF;

        IF ABS(v_new_rate - v_rate) < 0.0000000001 THEN
            RETURN v_new_rate;
        END IF;

        v_rate := v_new_rate;
    END LOOP;

    RETURN NULL;
END;
$function$;
