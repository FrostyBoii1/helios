#!/usr/bin/env python
"""Dry-run import report for the legacy jobs workbook (COMPLETED sheet).

READ-ONLY ANALYSIS TOOL. Does NOT write to the database, does NOT create
customers/jobs, and does NOT modify the workbook. The parsing logic lives in the
shared, DB-free module `app.services.import_parser`; this script is a thin CLI
wrapper that loads a workbook from a path you supply and prints a summary report.

Usage:
    python backend/scripts/import_dryrun.py "/path/to/workbook.xlsx"
    python backend/scripts/import_dryrun.py "/path/to/workbook.xlsx" --sheet COMPLETED
    python backend/scripts/import_dryrun.py "/path/to/workbook.xlsx" --samples 5
    python backend/scripts/import_dryrun.py "/path/to/workbook.xlsx" --json-output out.json

The workbook path is always supplied as an argument — no real path is hardcoded.
Save any JSON output to a git-ignored dir (e.g. ref/); it can contain PII.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

# Make the backend root importable so `app.services.import_parser` resolves
# regardless of the current working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import openpyxl
except ImportError:  # pragma: no cover
    sys.exit("openpyxl is required: pip install openpyxl (it is in backend/requirements.txt)")

from app.services import import_parser  # noqa: E402


def build_report(ws) -> dict:
    rep = {
        "classes": Counter(),
        "sales": Counter(),
        "installers": Counter(),
        "distributors_raw": Counter(),
        "retailers_raw": Counter(),
        "nmi_inferred": Counter(),
        "approval": Counter(),
        "msb": Counter(),
        "issues": Counter(),
        "issue_samples": [],
        "parsed_samples": [],
        "likely_jobs": 0,
        "all_rows": [],
    }
    for prow in import_parser.parse_rows(ws):
        rep["classes"][prow.row_class] += 1
        for issue in prow.issues:
            rep["issues"][issue["kind"]] += 1
            if len(rep["issue_samples"]) < 15:
                rep["issue_samples"].append(
                    {"row": prow.source_row_index, "kind": issue["kind"], "reason": issue["message"]}
                )
        if prow.row_class not in ("job", "ambiguous"):
            continue
        p = prow.parsed
        if prow.row_class == "job":
            rep["likely_jobs"] += 1
        if p.get("salesperson"):
            rep["sales"][p["salesperson"]] += 1
        if p.get("installer_raw"):
            rep["installers"][p["installer_raw"]] += 1
        if p.get("distributor_raw"):
            rep["distributors_raw"][p["distributor_raw"]] += 1
        if p.get("retailer_raw"):
            rep["retailers_raw"][p["retailer_raw"]] += 1
        rep["nmi_inferred"][p.get("distributor_inferred") or "UNMATCHED/none"] += 1
        rep["approval"][p.get("approval_state", "none")] += 1
        rep["msb"][p.get("msb_state", "no")] += 1
        rep["all_rows"].append({"row": prow.source_row_index, **p})
    return rep


def print_report(sheet: str, rep: dict, samples: int) -> None:
    def section(t: str) -> None:
        print(f"\n=== {t} ===")

    print("DRY-RUN IMPORT REPORT (read-only - no database writes)")
    print(f"Sheet: {sheet!r}")

    section("Row classification")
    for k in ("blank", "divider", "job", "ambiguous"):
        print(f"  {k:10}: {rep['classes'].get(k, 0)}")
    print(f"  likely jobs (clean ref): {rep['likely_jobs']}")

    for title, key in [("Approval status", "approval"), ("MSB/SB pics state", "msb")]:
        section(title)
        for k, v in rep[key].most_common():
            print(f"  {k:10}: {v}")

    section("NMI -> distributor inference")
    for k, v in rep["nmi_inferred"].most_common():
        print(f"  {v:5}  {k}")

    for title, key, n in [
        ("Top salesperson (parsed)", "sales", 10),
        ("Top installer (raw)", "installers", 12),
        ("Top distributor (raw)", "distributors_raw", 8),
        ("Top retailer (raw)", "retailers_raw", 8),
    ]:
        section(title)
        for k, v in rep[key].most_common(n):
            print(f"  {v:4}  {k!r}")

    section("Issue counts")
    for k, v in rep["issues"].most_common():
        print(f"  {v:5}  {k}")

    section("Sample issues (row - kind - reason)")
    for it in rep["issue_samples"]:
        print(f"  row {it['row']}: {it['kind']} - {it['reason']}")

    section("Sample parsed job rows")
    for p in [r for r in rep["all_rows"]][:samples]:
        print(f"\n  row {p['row']} ref={p.get('legacy_reference')!r}")
        print(f"    customer: {p.get('customer_name')!r}  extracted: {p.get('name_extracted_notes')!r}")
        print(f"    sales: {p.get('salesperson')!r} sale_date={p.get('sale_date')}  install={p.get('install_date')}")
        print(f"    approval: {p.get('approval_state')}  msb: {p.get('msb_state')}")
        print(f"    nmi: {p.get('nmi_raw')!r} -> {p.get('distributor_inferred')!r}; sheet dist {p.get('distributor_raw')!r}")
        print(f"    panels: {p.get('no_of_panels')} {p.get('panel_raw')!r} [{p.get('panel_confidence')}]")
        print(f"    inverter: {p.get('inverter_raw')!r} [{p.get('inverter_confidence')}]")


def main() -> None:
    ap = argparse.ArgumentParser(description="Read-only dry-run report for the jobs workbook.")
    ap.add_argument("workbook", help="Path to the .xlsx workbook (never hardcoded).")
    ap.add_argument("--sheet", default="COMPLETED")
    ap.add_argument("--samples", type=int, default=5)
    ap.add_argument("--json-output", default=None, help="Optional parsed JSON (PII — keep git-ignored).")
    args = ap.parse_args()

    wb = openpyxl.load_workbook(args.workbook, read_only=False, data_only=True)
    if args.sheet not in wb.sheetnames:
        sys.exit(f"Sheet {args.sheet!r} not found. Available: {wb.sheetnames}")
    rep = build_report(wb[args.sheet])
    print_report(args.sheet, rep, args.samples)

    if args.json_output:
        with open(args.json_output, "w", encoding="utf-8") as fh:
            json.dump({"sheet": args.sheet, "rows": rep["all_rows"]}, fh, indent=2, ensure_ascii=False)
        print(f"\n[wrote parsed JSON -> {args.json_output} — contains PII, keep it git-ignored]")


if __name__ == "__main__":
    main()
