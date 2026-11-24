"""Planning and orchestration for batch historical market-data refreshes."""

from dataclasses import dataclass
from datetime import date, timedelta
import time


@dataclass(frozen=True)
class HistoryRefreshPlan:
    """Planned history refresh for one security."""

    security_id: int
    security: dict
    start_date: date
    end_date: date
    reason: str


@dataclass(frozen=True)
class BatchPlan:
    """Complete batch planning result."""

    planned: list[HistoryRefreshPlan]
    skipped: list[dict]


class MarketDataBatchPlanner:
    """Calculate initial and incremental history refresh windows."""

    def __init__(
        self,
        storage,
        initial_history_years: int = 10,
        overlap_days: int = 5,
    ):
        if initial_history_years <= 0:
            raise ValueError("initial_history_years must be positive")

        if overlap_days < 0:
            raise ValueError("overlap_days cannot be negative")

        self.storage = storage
        self.initial_history_years = initial_history_years
        self.overlap_days = overlap_days

    @staticmethod
    def _years_ago(reference_date: date, years: int) -> date:
        """Subtract calendar years, handling leap-day boundaries."""
        try:
            return reference_date.replace(year=reference_date.year - years)
        except ValueError:
            return reference_date.replace(
                year=reference_date.year - years,
                day=28,
            )

    def create_plan(
        self,
        end_date: date | None = None,
    ) -> BatchPlan:
        """Build a refresh plan without contacting market-data providers."""
        end_date = end_date or date.today()

        securities = self.storage.get_active_market_data_securities()

        security_ids = sorted({
            row["security_id"] for row in securities
        })

        latest_dates = (
            self.storage.get_latest_price_dates(security_ids)
            if security_ids
            else {}
        )

        planned = []
        skipped = []
        seen_security_ids = set()

        for security in securities:
            security_id = security["security_id"]

            if security_id in seen_security_ids:
                continue

            seen_security_ids.add(security_id)

            association_count = security["active_association_count"]

            if association_count != 1:
                skipped.append({
                    "security_id": security_id,
                    "reason": (
                        "Multiple active portfolio account associations"
                    ),
                    "status": "skipped",
                })
                continue

            first_transaction_date = security["first_transaction_date"]
            latest_date = latest_dates.get(security_id)

            if latest_date is None:
                if first_transaction_date is not None:
                    start_date = first_transaction_date
                    reason = "initial_load_from_first_transaction"
                else:
                    start_date = self._years_ago(
                        end_date,
                        self.initial_history_years,
                    )
                    reason = "initial_load_default_period"
            else:
                start_date = latest_date - timedelta(
                    days=self.overlap_days
                )
                reason = "incremental_refresh"

            if start_date > end_date:
                skipped.append({
                    "security_id": security_id,
                    "reason": "History start date is after batch end date",
                    "status": "skipped",
                })
                continue

            planned.append(
                HistoryRefreshPlan(
                    security_id=security_id,
                    security=security,
                    start_date=start_date,
                    end_date=end_date,
                    reason=reason,
                )
            )

        return BatchPlan(
            planned=planned,
            skipped=skipped,
        )

@dataclass(frozen=True)
class BatchSecurityResult:
    """Outcome of refreshing one security."""

    security_id: int
    start_date: date
    end_date: date
    reason: str
    status: str
    records_written: int = 0
    provider: str | None = None
    fallback_reason: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class BatchExecutionReport:
    """Aggregate results from one batch execution."""

    results: list[BatchSecurityResult]
    skipped: list[dict]

    @property
    def succeeded(self) -> int:
        return sum(item.status == "success" for item in self.results)

    @property
    def no_data(self) -> int:
        return sum(item.status == "no_data" for item in self.results)

    @property
    def failed(self) -> int:
        return sum(item.status == "failed" for item in self.results)

    @property
    def records_written(self) -> int:
        return sum(item.records_written for item in self.results)


class MarketDataBatchRunner:
    """Execute planned history refreshes independently and sequentially."""

    def __init__(self, market_data_service, delay_seconds: float = 0):
        if delay_seconds < 0:
            raise ValueError("delay_seconds cannot be negative")

        self.market_data_service = market_data_service
        self.delay_seconds = delay_seconds

    def execute(self, plan: BatchPlan) -> BatchExecutionReport:
        """Execute every planned refresh without stopping on individual errors."""
        results = []

        for index, item in enumerate(plan.planned):
            if index > 0 and self.delay_seconds:
                time.sleep(self.delay_seconds)

            try:
                refresh = self.market_data_service.refresh_history_result(
                    item.security,
                    item.start_date,
                    item.end_date,
                )

                result = BatchSecurityResult(
                    security_id=item.security_id,
                    start_date=item.start_date,
                    end_date=item.end_date,
                    reason=item.reason,
                    status=refresh.status,
                    records_written=refresh.records_written,
                    provider=refresh.provider,
                    fallback_reason=refresh.fallback_reason,
                    error=refresh.error,
                )

            except Exception as exc:
                result = BatchSecurityResult(
                    security_id=item.security_id,
                    start_date=item.start_date,
                    end_date=item.end_date,
                    reason=item.reason,
                    status="failed",
                    error=str(exc),
                )

            results.append(result)

        return BatchExecutionReport(
            results=results,
            skipped=plan.skipped,
        )
