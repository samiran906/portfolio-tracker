"""Command-line interface for batch historical market-data refreshes."""

import argparse
from datetime import date, datetime
from zoneinfo import ZoneInfo

from psycopg import connect
from psycopg.rows import dict_row

from app import _database_url
from market_data.batch import (
    BatchPlan,
    MarketDataBatchPlanner,
    MarketDataBatchRunner,
)
from market_data.service import MarketDataService
from market_data.storage import MarketDataStorage


def parse_args():
    parser = argparse.ArgumentParser(
        description="Plan or execute batch historical market-data refreshes."
    )

    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute refreshes. Without this flag, only a dry run is performed.",
    )
    parser.add_argument(
        "--end-date",
        type=date.fromisoformat,
        default=datetime.now(ZoneInfo("Asia/Kolkata")).date(),
        help="Inclusive batch end date in YYYY-MM-DD format (default: India date).",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=1.0,
        help="Delay between security refreshes in execution mode (default: 1).",
    )

    parser.add_argument(
        "--security-id",
        type=int,
        default=None,
        help="Limit the plan to one security (used for immediate initial loads).",
    )

    args = parser.parse_args()

    if args.delay_seconds < 0:
        parser.error("--delay-seconds cannot be negative")

    if args.security_id is not None and args.security_id <= 0:
        parser.error("--security-id must be a positive integer")

    return args


def select_security_plan(plan, security_id):
    """Select one security and suppress an unnecessary repeat initial load."""
    planned = [
        item for item in plan.planned
        if item.security_id == security_id
    ]
    skipped = [
        item for item in plan.skipped
        if item["security_id"] == security_id
    ]

    if planned and planned[0].reason == "incremental_refresh":
        planned = []
        skipped.append({
            "security_id": security_id,
            "status": "skipped",
            "reason": "Price history already exists; immediate initial load is not needed",
        })

    if not planned and not skipped:
        skipped.append({
            "security_id": security_id,
            "status": "skipped",
            "reason": "Security is not eligible for market-data history refresh",
        })

    return BatchPlan(planned=planned, skipped=skipped)


def create_dependencies():
    connection_factory = lambda: connect(
        _database_url(),
        row_factory=dict_row,
    )

    storage = MarketDataStorage(connection_factory)
    service = MarketDataService(storage)
    planner = MarketDataBatchPlanner(storage)

    return storage, service, planner


def describe_provider(service, security):
    try:
        route = service._provider_route(security)
        provider = route["provider"]

        if provider == "NSE":
            return "NSE (Yahoo Finance fallback)"

        return provider

    except Exception as exc:
        return f"CONFIGURATION ERROR: {exc}"


def print_plan(plan, service):
    print("\
BATCH HISTORY REFRESH PLAN")
    print("=" * 100)

    if not plan.planned:
        print("No securities are eligible for refresh.")

    for item in plan.planned:
        security = item.security

        print(
            f"ID: {item.security_id} | "
            f"{security['name']} | "
            f"{security['account_name']} | "
            f"{security['symbol']}"
        )
        print(
            f"  Provider: {describe_provider(service, security)}"
        )
        print(
            f"  Dates: {item.start_date} to {item.end_date} | "
            f"Reason: {item.reason}"
        )

    if plan.skipped:
        print("\
SKIPPED SECURITIES")
        print("-" * 100)

        for item in plan.skipped:
            print(
                f"ID: {item['security_id']} | "
                f"Status: {item['status']} | "
                f"Reason: {item['reason']}"
            )

    print("\
PLAN SUMMARY")
    print(f"Planned: {len(plan.planned)}")
    print(f"Skipped: {len(plan.skipped)}")


def print_execution_report(report):
    print("\
EXECUTION RESULTS")
    print("=" * 100)

    for item in report.results:
        print(
            f"ID: {item.security_id} | "
            f"Status: {item.status} | "
            f"Provider: {item.provider or '-'} | "
            f"Records: {item.records_written}"
        )
        print(
            f"  Dates: {item.start_date} to {item.end_date} | "
            f"Reason: {item.reason}"
        )

        if item.fallback_reason:
            print(f"  Fallback: {item.fallback_reason}")

        if item.error:
            print(f"  Error: {item.error}")

    print("\
BATCH SUMMARY")
    print(f"Succeeded: {report.succeeded}")
    print(f"No data: {report.no_data}")
    print(f"Failed: {report.failed}")
    print(f"Skipped: {len(report.skipped)}")
    print(f"Records written: {report.records_written}")


def main():
    args = parse_args()

    storage, service, planner = create_dependencies()
    plan = planner.create_plan(end_date=args.end_date)
    if args.security_id is not None:
        plan = select_security_plan(plan, args.security_id)

    print_plan(plan, service)

    if not args.execute:
        print("\
DRY RUN ONLY - no provider requests or database writes performed.")
        print("Use --execute to perform the refresh.")
        return 0

    print("\
EXECUTING BATCH REFRESH")
    runner = MarketDataBatchRunner(
        service,
        delay_seconds=args.delay_seconds,
    )

    report = runner.execute(plan)
    print_execution_report(report)

    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
