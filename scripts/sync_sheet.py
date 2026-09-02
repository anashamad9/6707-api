#!/usr/bin/env python3
"""Sync affiliate 6706 transaction rows from Google Sheets to static JSON."""

import csv
import json
import os
import re
import sys
import time
import zipfile
from datetime import datetime, timezone
from io import StringIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

SHEET_ID = "1KsSitjTjovlJegKIirqvpIwq00r9mwhg5hcKyC203Ec"
GID = "0"
AFFILIATE_ID = "6706"
OUTPUT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "docs", "api", "transactions.json"
)
MAPPING_PATH = os.path.join(os.path.dirname(__file__), "..", "Mapping.xlsx")

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

XML_NS = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def normalize_id(value: str) -> str:
    """Make Excel numeric IDs such as 1406.0 match sheet IDs such as 1406."""
    value = value.strip()
    if re.fullmatch(r"\d+\.0+", value):
        return value.split(".", 1)[0]
    return value


def excel_column_index(reference: str) -> int:
    letters = re.match(r"[A-Z]+", reference)
    if not letters:
        raise ValueError(f"Invalid Excel cell reference: {reference}")
    index = 0
    for letter in letters.group(0):
        index = index * 26 + ord(letter) - 64
    return index - 1


def load_offer_mapping() -> dict[str, str]:
    """Read offer IDs and names from Mapping.xlsx using Python's standard library."""
    mapping_path = os.path.normpath(MAPPING_PATH)
    try:
        with zipfile.ZipFile(mapping_path) as workbook:
            shared_strings = []
            if "xl/sharedStrings.xml" in workbook.namelist():
                shared_root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
                for item in shared_root.findall("main:si", XML_NS):
                    shared_strings.append(
                        "".join(node.text or "" for node in item.iterfind(".//main:t", XML_NS))
                    )

            sheet_root = ET.fromstring(workbook.read("xl/worksheets/sheet1.xml"))
    except (FileNotFoundError, KeyError, zipfile.BadZipFile, ET.ParseError) as exc:
        raise ValueError(f"Could not read offer mapping workbook: {mapping_path}") from exc

    rows = []
    for row in sheet_root.findall(".//main:sheetData/main:row", XML_NS):
        values: dict[int, str] = {}
        for item in row.findall("main:c", XML_NS):
            reference = item.attrib.get("r", "")
            cell_type = item.attrib.get("t")
            value_node = item.find("main:v", XML_NS)
            value = "" if value_node is None else value_node.text or ""
            if cell_type == "s" and value:
                value = shared_strings[int(value)]
            elif cell_type == "inlineStr":
                value = "".join(
                    node.text or "" for node in item.iterfind(".//main:t", XML_NS)
                )
            values[excel_column_index(reference)] = value.strip()
        if values:
            rows.append(values)

    if not rows:
        raise ValueError("Mapping.xlsx contains no rows.")

    header = {value.casefold(): index for index, value in rows[0].items()}
    try:
        name_column = header["offer name"]
        id_column = header["offer id"]
    except KeyError as exc:
        raise ValueError("Mapping.xlsx must contain 'Offer name' and 'Offer id' columns.") from exc

    offers: dict[str, str] = {}
    for row in rows[1:]:
        offer_id = normalize_id(row.get(id_column, ""))
        offer_name = row.get(name_column, "").strip()
        if not offer_id or not offer_name:
            continue
        if offer_id in offers and offers[offer_id] != offer_name:
            raise ValueError(
                f"Mapping.xlsx has conflicting names for offer ID {offer_id}: "
                f"'{offers[offer_id]}' and '{offer_name}'"
            )
        offers[offer_id] = offer_name

    if not offers:
        raise ValueError("Mapping.xlsx contains no valid offer mappings.")
    return offers


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


def parse_rows(content: str, offer_mapping: dict[str, str]) -> list[dict[str, str]]:
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
        record = {
            target: (row.get(source) or "").strip()
            for source, target in FIELDS.items()
        }
        offer_id = normalize_id(record["offer_id"])
        record["offer_id"] = offer_id
        record = {
            "transaction_id": record.pop("transaction_id"),
            "offer_id": record.pop("offer_id"),
            "offer_name": offer_mapping.get(offer_id, ""),
            **record,
        }
        transactions.append(record)
    return transactions


def main() -> None:
    print(f"Fetching sheet {SHEET_ID} (gid={GID})")
    offer_mapping = load_offer_mapping()
    print(f"  {len(offer_mapping)} offer mappings loaded from Mapping.xlsx")
    transactions = parse_rows(fetch_csv(), offer_mapping)
    print(f"  {len(transactions)} transactions parsed for affiliate {AFFILIATE_ID}")
    unmapped_offer_ids = sorted(
        {item["offer_id"] for item in transactions if not item["offer_name"]}
    )
    print(f"  {len(unmapped_offer_ids)} offer IDs have no mapping")

    output = {
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "6706 Transactions",
        "sheet_id": SHEET_ID,
        "gid": GID,
        "affiliate_id": AFFILIATE_ID,
        "mapping_source": "Mapping.xlsx",
        "mapped_offers": len(offer_mapping),
        "unmapped_offer_ids": unmapped_offer_ids,
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
