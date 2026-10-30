"""MFapi.in provider for Indian mutual-fund NAV history."""

import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from market_data.models import PriceBar
from market_data.errors import MarketDataError


BASE_URL = "https://api.mfapi.in/mf"


def _parse_nav(value) -> Decimal:
    try:
        nav = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError, AttributeError) as exc:
        raise MarketDataError("MFapi returned an invalid NAV value") from exc

    if not nav.is_finite() or nav <= 0:
        raise MarketDataError("MFapi returned a non-positive or non-finite NAV")

    return nav


def _parse_date(value) -> date:
    try:
        # MFapi publishes NAV dates as DD-MM-YYYY.
        return datetime.strptime(str(value).strip(), "%d-%m-%Y").date()
    except (ValueError, TypeError) as exc:
        raise MarketDataError("MFapi returned an invalid NAV date") from exc


class MFapiProvider:
    """Retrieve published NAV history by the actual MFapi scheme code."""

    def __init__(self, timeout: float = 15.0):
        self.timeout = timeout

    @staticmethod
    def _validate_scheme_code(scheme_code: str) -> str:
        code = str(scheme_code).strip()
        if not re.fullmatch(r"\d{1,12}", code):
            raise ValueError("MFapi scheme code must contain only digits")
        return code

    def get_history(
        self,
        scheme_code: str,
        start_date: date,
        end_date: date | None = None,
    ) -> list[PriceBar]:
        """Return published NAVs in the inclusive requested date range."""
        code = self._validate_scheme_code(scheme_code)
        if end_date is not None and end_date < start_date:
            raise ValueError("end_date must not precede start_date")

        params = {}
        if start_date:
            params["startDate"] = start_date.isoformat()
        if end_date:
            params["endDate"] = end_date.isoformat()

        url = f"{BASE_URL}/{code}"
        if params:
            url = f"{url}?{urlencode(params)}"

        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "PortfolioTracker/1.0",
            },
        )

        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise MarketDataError(
                f"MFapi request failed with HTTP {exc.code} for scheme {code}"
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise MarketDataError(
                f"MFapi request failed for scheme {code}"
            ) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MarketDataError(
                f"MFapi returned invalid JSON for scheme {code}"
            ) from exc

        if not isinstance(payload, dict):
            raise MarketDataError("MFapi response has an unexpected format")

        data = payload.get("data")
        if not isinstance(data, list):
            raise MarketDataError("MFapi response is missing NAV history")

        bars = []
        for entry in data:
            if not isinstance(entry, dict):
                continue

            nav_date = _parse_date(entry.get("date"))
            if nav_date < start_date or (end_date and nav_date > end_date):
                continue

            bars.append(
                PriceBar(
                    price_date=nav_date,
                    close=_parse_nav(entry.get("nav")),
                    currency="INR",
                )
            )

        # A scheme should have at most one NAV per date. If the provider
        # returns duplicates, keep one deterministic record per date.
        by_date = {bar.price_date: bar for bar in bars}
        return [by_date[day] for day in sorted(by_date)]

    def get_latest_nav(self, scheme_code: str) -> PriceBar:
        """Return the latest published NAV using MFapi's latest endpoint."""
        code = self._validate_scheme_code(scheme_code)
        url = f"{BASE_URL}/{code}/latest"

        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "PortfolioTracker/1.0",
            },
        )

        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise MarketDataError(
                f"MFapi latest NAV request failed with HTTP {exc.code} "
                f"for scheme {code}"
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise MarketDataError(
                f"MFapi latest NAV request failed for scheme {code}"
            ) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MarketDataError(
                f"MFapi returned invalid latest NAV JSON for scheme {code}"
            ) from exc

        if not isinstance(payload, dict):
            raise MarketDataError("MFapi latest NAV response has an unexpected format")

        data = payload.get("data")
        if not isinstance(data, list) or not data:
            raise MarketDataError(
                f"No published NAV found for scheme {code}"
            )

        entry = data[0]
        if not isinstance(entry, dict):
            raise MarketDataError("MFapi latest NAV record has an unexpected format")

        return PriceBar(
            price_date=_parse_date(entry.get("date")),
            close=_parse_nav(entry.get("nav")),
            currency="INR",
        )
