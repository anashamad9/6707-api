#!/usr/bin/env python3
"""Sync affiliate 6706 transaction rows from Google Sheets to static JSON."""

import csv
import json
import os
import sys
import time
from datetime import datetime, timezone
from io import StringIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SHEET_ID = "1KsSitjTjovlJegKIirqvpIwq00r9mwhg5hcKyC203Ec"
GID = "0"
AFFILIATE_ID = "6706"
OUTPUT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "docs", "api", "transactions.json"
)

FIELDS = {
    "Transaction_ID": "transaction_id",
    "offer_id": "offer_id",
    "affiliate_id": "affiliate_id",
    "datetime": "datetime",
    "status": "status",
    "payout": "payout",
    "revenue": "revenue",
    "sale_amount": "sale_amount",
    "affiliate_info1": "affiliate_info1",
    "Geo": "geo",
    "sales_status": "sales_status",
    "Month": "month",
}


def fetch_csv() -> str:
    url = (
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"
        f"/gviz/tq?tqx=out:csv&gid={GID}&_={time.time_ns()}"
    )
    request = Request(
        url,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
        },
    )

    try:
        with urlopen(request, timeout=60) as response:
            return response.read().decode("utf-8-sig")
    except HTTPError as exc:
        if exc.code in (401, 403):
            print(
                "ERROR: Google denied access. Share the sheet as "
                "'Anyone with the link' (Viewer) or publish it to the web.",
                file=sys.stderr,
            )
        else:
            print(f"ERROR fetching sheet: HTTP {exc.code}", file=sys.stderr)
        raise SystemExit(1) from exc
    except URLError as exc:
        print(f"ERROR fetching sheet: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def parse_rows(content: str) -> list[dict[str, str]]:
    reader = csv.DictReader(StringIO(content))
    if reader.fieldnames is None:
        raise ValueError("The sheet has no header row.")

    missing = [source for source in FIELDS if source not in reader.fieldnames]
    if missing:
        raise ValueError(f"Missing required sheet columns: {', '.join(missing)}")

    transactions = []
    for row in reader:
        if not any((value or "").strip() for value in row.values()):
            continue
        affiliate_id = (row.get("affiliate_id") or "").strip()
        if affiliate_id != AFFILIATE_ID:
            continue
        transactions.append(
            {
                target: (row.get(source) or "").strip()
                for source, target in FIELDS.items()
            }
        )
    return transactions


def main() -> None:
    print(f"Fetching sheet {SHEET_ID} (gid={GID})")
    transactions = parse_rows(fetch_csv())
    print(f"  {len(transactions)} transactions parsed for affiliate {AFFILIATE_ID}")

    output = {
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "6706 Transactions",
        "sheet_id": SHEET_ID,
        "gid": GID,
        "affiliate_id": AFFILIATE_ID,
        "total": len(transactions),
        "transactions": transactions,
    }

    output_path = os.path.normpath(OUTPUT_PATH)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Preserve the previous timestamp and file when the sheet data is unchanged.
    # This prevents scheduled runs from creating large, timestamp-only commits.
    try:
        with open(output_path, encoding="utf-8") as existing_file:
            existing = json.load(existing_file)
        if (
            existing.get("affiliate_id") == AFFILIATE_ID
            and existing.get("transactions") == transactions
        ):
            print(f"  No data changes; keeping {output_path}")
            return
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass

    temporary_path = f"{output_path}.tmp"
    with open(temporary_path, "w", encoding="utf-8") as output_file:
        json.dump(output, output_file, ensure_ascii=False, indent=2)
        output_file.write("\n")
    os.replace(temporary_path, output_path)
    print(f"  Written to {output_path}")


if __name__ == "__main__":
    main()
