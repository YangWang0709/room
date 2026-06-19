#!/usr/bin/env python3
"""Summarize GarbageCollect target-level timing CSV output."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from typing import Iterable


DEFAULT_TIMING_CSV = Path("/tmp/infinigen_gc_timing.csv")
TARGET_LIMIT = 20
SLOW_ROW_LIMIT = 50
ZERO_REMOVE_LIMIT = 20

PHASES = ("enter_snapshot", "exit_cleanup")

TARGET_TABLE_COLUMNS = (
    "context_id",
    "phase",
    "target_name",
    "target_len_before",
    "target_len_after",
    "keep_names_count",
    "scanned_count",
    "skipped_in_use_count",
    "skipped_keep_name_count",
    "skipped_no_gc_count",
    "removed_count",
    "remove_duration",
    "node_group_interval",
    "node_group_cleanup_skipped",
    "node_group_cleanup_due",
    "effective_cleanup",
    "duration",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze infinigen_gc_timing.csv rows from "
            "infinigen.core.util.blender.GarbageCollect."
        )
    )
    parser.add_argument(
        "csv_path",
        nargs="?",
        default=DEFAULT_TIMING_CSV,
        type=Path,
        help=f"Path to infinigen_gc_timing.csv. Default: {DEFAULT_TIMING_CSV}",
    )
    return parser.parse_args()


def as_float(row: dict[str, str], key: str) -> float:
    value = (row.get(key) or "").strip()
    if not value:
        return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


def as_int(row: dict[str, str], key: str) -> int:
    value = (row.get(key) or "").strip()
    if not value:
        return 0
    try:
        return int(float(value))
    except ValueError:
        return 0


def as_bool(row: dict[str, str], key: str) -> bool:
    return (row.get(key) or "").strip().lower() in {"1", "true", "yes", "y"}


def has_value(row: dict[str, str], key: str) -> bool:
    return bool((row.get(key) or "").strip())


def cleanup_skipped(row: dict[str, str]) -> bool:
    return as_bool(row, "node_group_cleanup_skipped")


def cleanup_effective(row: dict[str, str]) -> bool:
    if has_value(row, "effective_cleanup"):
        return as_bool(row, "effective_cleanup")
    return row.get("phase") == "exit_cleanup"


def cleanup_due(row: dict[str, str]) -> bool:
    if has_value(row, "node_group_cleanup_due"):
        return as_bool(row, "node_group_cleanup_due")
    return cleanup_effective(row)


def as_optional_int(row: dict[str, str], key: str) -> int | None:
    value = (row.get(key) or "").strip()
    if not value:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def clean_label(value: str | None) -> str:
    value = (value or "").strip()
    return value if value else "(unknown)"


def fmt(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def print_table(headers: tuple[str, ...], rows: Iterable[Iterable[object]]) -> None:
    rows = [tuple(fmt(value) for value in row) for row in rows]
    widths = [len(header) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))

    print(
        "  "
        + "  ".join(
            header.ljust(widths[index]) for index, header in enumerate(headers)
        )
    )
    print("  " + "  ".join("-" * width for width in widths))
    for row in rows:
        print(
            "  "
            + "  ".join(
                value.ljust(widths[index]) for index, value in enumerate(row)
            )
        )


def load_rows(csv_path: Path) -> list[dict[str, str]]:
    if not csv_path.exists():
        raise SystemExit(f"GC timing CSV does not exist: {csv_path}")
    with csv_path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def is_context_row(row: dict[str, str]) -> bool:
    return row.get("row_type") == "context"


def is_target_row(row: dict[str, str]) -> bool:
    return row.get("row_type") == "target" or row.get("phase") in PHASES


def context_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [row for row in rows if is_context_row(row)]


def target_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [row for row in rows if is_target_row(row)]


def phase_duration(rows: list[dict[str, str]], phase: str) -> float:
    return sum(
        as_float(row, "duration") for row in rows if row.get("phase") == phase
    )


def print_context_summary(contexts: list[dict[str, str]], targets: list[dict[str, str]]):
    print("\nA. GC context summary")
    context_total = len(contexts)
    success_count = sum(1 for row in contexts if as_bool(row, "success"))
    failed_count = context_total - success_count
    enter_target_total = phase_duration(targets, "enter_snapshot")
    exit_target_total = phase_duration(targets, "exit_cleanup")
    enter_context_total = sum(as_float(row, "enter_total_duration") for row in contexts)
    exit_context_total = sum(as_float(row, "exit_total_duration") for row in contexts)
    total_context_duration = sum(as_float(row, "total_duration") for row in contexts)

    print_table(
        (
            "context_count",
            "success",
            "failed",
            "context_total",
            "context_enter",
            "context_exit",
            "target_enter",
            "target_exit",
        ),
        (
            (
                context_total,
                success_count,
                failed_count,
                total_context_duration,
                enter_context_total,
                exit_context_total,
                enter_target_total,
                exit_target_total,
            ),
        ),
    )


def summarize_targets(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    groups: dict[str, dict[str, object]] = defaultdict(
        lambda: {
            "rows": 0,
            "duration": 0.0,
            "enter_duration": 0.0,
            "exit_duration": 0.0,
            "remove_duration": 0.0,
            "scanned_count": 0,
            "removed_count": 0,
            "skipped_in_use_count": 0,
            "skipped_keep_name_count": 0,
            "skipped_no_gc_count": 0,
        }
    )

    for row in rows:
        target_name = clean_label(row.get("target_name"))
        group = groups[target_name]
        duration = as_float(row, "duration")
        group["rows"] = int(group["rows"]) + 1
        group["duration"] = float(group["duration"]) + duration
        group["remove_duration"] = float(group["remove_duration"]) + as_float(
            row, "remove_duration"
        )
        if row.get("phase") == "enter_snapshot":
            group["enter_duration"] = float(group["enter_duration"]) + duration
        elif row.get("phase") == "exit_cleanup":
            group["exit_duration"] = float(group["exit_duration"]) + duration
        for count_key in (
            "scanned_count",
            "removed_count",
            "skipped_in_use_count",
            "skipped_keep_name_count",
            "skipped_no_gc_count",
        ):
            group[count_key] = int(group[count_key]) + as_int(row, count_key)

    summary = []
    for target_name, group in groups.items():
        summary.append({"target_name": target_name, **group})
    return sorted(summary, key=lambda item: float(item["duration"]), reverse=True)


def print_target_duration_summary(targets: list[dict[str, str]]) -> None:
    print("\nB. Duration by target_name (top 20)")
    print_table(
        (
            "target_name",
            "rows",
            "duration",
            "enter_duration",
            "exit_duration",
            "remove_duration",
        ),
        (
            (
                item["target_name"],
                item["rows"],
                item["duration"],
                item["enter_duration"],
                item["exit_duration"],
                item["remove_duration"],
            )
            for item in summarize_targets(targets)[:TARGET_LIMIT]
        ),
    )


def print_target_count_summary(targets: list[dict[str, str]]) -> None:
    print("\nC. Scanned and removed counts by target_name")
    summary = sorted(
        summarize_targets(targets),
        key=lambda item: (int(item["scanned_count"]), int(item["removed_count"])),
        reverse=True,
    )
    print_table(
        (
            "target_name",
            "scanned_count",
            "removed_count",
            "skipped_in_use",
            "skipped_keep_name",
            "skipped_no_gc",
            "duration",
        ),
        (
            (
                item["target_name"],
                item["scanned_count"],
                item["removed_count"],
                item["skipped_in_use_count"],
                item["skipped_keep_name_count"],
                item["skipped_no_gc_count"],
                item["duration"],
            )
            for item in summary[:TARGET_LIMIT]
        ),
    )


def slow_target_rows(targets: list[dict[str, str]]) -> list[dict[str, object]]:
    rows = []
    for row in targets:
        item: dict[str, object] = {
            column: row.get(column, "") for column in TARGET_TABLE_COLUMNS
        }
        for key in (
            "target_len_before",
            "target_len_after",
            "keep_names_count",
            "scanned_count",
            "skipped_in_use_count",
            "skipped_keep_name_count",
            "skipped_no_gc_count",
            "removed_count",
        ):
            item[key] = as_int(row, key)
        item["remove_duration"] = as_float(row, "remove_duration")
        interval = as_optional_int(row, "node_group_interval")
        item["node_group_interval"] = "" if interval is None else interval
        item["node_group_cleanup_skipped"] = cleanup_skipped(row)
        item["node_group_cleanup_due"] = cleanup_due(row)
        item["effective_cleanup"] = cleanup_effective(row)
        item["duration"] = as_float(row, "duration")
        item["target_name"] = clean_label(row.get("target_name"))
        rows.append(item)
    return sorted(rows, key=lambda item: float(item["duration"]), reverse=True)


def print_slow_target_rows(targets: list[dict[str, str]]) -> None:
    print("\nD. Slowest target-level GC rows (top 50)")
    print_table(
        TARGET_TABLE_COLUMNS,
        (
            (item[column] for column in TARGET_TABLE_COLUMNS)
            for item in slow_target_rows(targets)[:SLOW_ROW_LIMIT]
        ),
    )


def print_zero_remove_rows(targets: list[dict[str, str]]) -> None:
    print("\nE. exit_cleanup rows with removed_count=0 but high duration (top 20)")
    zero_remove = [
        item
        for item in slow_target_rows(targets)
        if item["phase"] == "exit_cleanup" and int(item["removed_count"]) == 0
    ]
    print_table(
        TARGET_TABLE_COLUMNS,
        (
            (item[column] for column in TARGET_TABLE_COLUMNS)
            for item in zero_remove[:ZERO_REMOVE_LIMIT]
        ),
    )


def node_group_exit_rows(targets: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        row
        for row in targets
        if row.get("phase") == "exit_cleanup"
        and clean_label(row.get("target_name")) == "node_groups"
    ]


def print_node_group_throttling_summary(targets: list[dict[str, str]]) -> None:
    print("\nF. Node group throttling summary")
    node_rows = node_group_exit_rows(targets)
    intervals = sorted(
        {
            interval
            for interval in (
                as_optional_int(row, "node_group_interval") for row in node_rows
            )
            if interval is not None
        }
    )
    interval_label = ",".join(str(interval) for interval in intervals) or "1"

    skipped_rows = [row for row in node_rows if cleanup_skipped(row)]
    executed_rows = [
        row for row in node_rows if not cleanup_skipped(row) and cleanup_effective(row)
    ]
    node_duration = sum(as_float(row, "duration") for row in node_rows)
    node_remove_duration = sum(as_float(row, "remove_duration") for row in node_rows)
    executed_duration = sum(as_float(row, "duration") for row in executed_rows)
    executed_remove_duration = sum(
        as_float(row, "remove_duration") for row in executed_rows
    )
    skipped_duration = sum(as_float(row, "duration") for row in skipped_rows)
    estimated_saved_time = (
        executed_remove_duration / len(executed_rows) * len(skipped_rows)
        if executed_rows
        else 0.0
    )
    max_node_group_count = 0
    for row in node_rows:
        max_node_group_count = max(
            max_node_group_count,
            as_int(row, "target_len_before"),
            as_int(row, "target_len_after"),
        )

    print_table(
        (
            "interval",
            "node_group_exit_rows",
            "skipped_cleanup",
            "executed_cleanup",
            "node_groups_duration",
            "node_groups_remove",
            "executed_duration",
            "executed_remove",
            "skipped_duration",
            "estimated_saved_time",
            "max_node_groups",
        ),
        (
            (
                interval_label,
                len(node_rows),
                len(skipped_rows),
                len(executed_rows),
                node_duration,
                node_remove_duration,
                executed_duration,
                executed_remove_duration,
                skipped_duration,
                estimated_saved_time,
                max_node_group_count,
            ),
        ),
    )
    if skipped_rows:
        print(
            "  Note: estimated_saved_time is a naive skipped-count estimate; "
            "compare raw node_groups_remove totals and A/B output before "
            "treating throttling as a speedup."
        )


def print_guidance(targets: list[dict[str, str]]) -> None:
    print("\nG. GC guidance")
    enter_total = phase_duration(targets, "enter_snapshot")
    exit_total = phase_duration(targets, "exit_cleanup")
    remove_total = sum(as_float(row, "remove_duration") for row in targets)
    exit_scan_total = max(exit_total - remove_total, 0.0)
    scanned_total = sum(
        as_int(row, "scanned_count")
        for row in targets
        if row.get("phase") == "exit_cleanup"
    )
    removed_total = sum(
        as_int(row, "removed_count")
        for row in targets
        if row.get("phase") == "exit_cleanup"
    )
    removed_rate = removed_total / scanned_total if scanned_total else 0.0
    total = enter_total + exit_total
    target_summary = summarize_targets(targets)
    top_target = target_summary[0] if target_summary else None
    top_target_share = (
        float(top_target["duration"]) / total if top_target and total else 0.0
    )

    print(f"  enter_snapshot_duration: {enter_total:.3f}s")
    print(f"  exit_cleanup_duration: {exit_total:.3f}s")
    print(f"  exit_cleanup_scan_duration_estimate: {exit_scan_total:.3f}s")
    print(f"  remove_duration: {remove_total:.3f}s")
    print(f"  exit_cleanup_scanned_count: {scanned_total}")
    print(f"  exit_cleanup_removed_count: {removed_total}")
    print(f"  exit_cleanup_removed_rate: {removed_rate:.3%}")

    node_rows = node_group_exit_rows(targets)
    skipped_node_groups = sum(1 for row in node_rows if cleanup_skipped(row))
    executed_node_groups = sum(
        1
        for row in node_rows
        if not cleanup_skipped(row) and cleanup_effective(row)
    )
    if skipped_node_groups:
        print(f"  node_group_cleanup_skipped_count: {skipped_node_groups}")
        print(f"  node_group_cleanup_executed_count: {executed_node_groups}")

    if top_target:
        print(
            "  top_target: "
            f"{top_target['target_name']} "
            f"{float(top_target['duration']):.3f}s ({top_target_share:.3%})"
        )

    if enter_total >= max(exit_scan_total, remove_total):
        print(
            "  Judgment: enter_snapshot is dominant; next consider an opt-in "
            "snapshot scope or target-reduction experiment."
        )
    elif remove_total >= exit_scan_total and remove_total >= enter_total:
        print(
            "  Judgment: remove calls dominate; next consider opt-in batch "
            "remove or target-specific cleanup experiments."
        )
    elif exit_scan_total >= enter_total and removed_rate < 0.01:
        print(
            "  Judgment: exit_cleanup scanning dominates while removals are "
            "rare; next consider opt-in less-frequent or deferred cleanup."
        )
    elif exit_scan_total >= enter_total:
        print(
            "  Judgment: exit_cleanup scanning is the larger stage; inspect "
            "the slow target rows before changing cleanup cadence."
        )
    else:
        print(
            "  Judgment: no single GC phase clearly dominates in this sample; "
            "compare the top target rows before designing an experiment."
        )

    if top_target and top_target_share >= 0.4:
        print(
            "  Target note: one target_name dominates the sample; keep the next "
            "opt-in experiment scoped around that target first."
        )


def main() -> None:
    args = parse_args()
    rows = load_rows(args.csv_path)
    contexts = context_rows(rows)
    targets = target_rows(rows)

    print(f"GC timing CSV: {args.csv_path}")
    print(f"Total CSV rows: {len(rows)}")
    print(f"Context rows: {len(contexts)}")
    print(f"Target rows: {len(targets)}")

    print_context_summary(contexts, targets)
    print_target_duration_summary(targets)
    print_target_count_summary(targets)
    print_slow_target_rows(targets)
    print_zero_remove_rows(targets)
    print_node_group_throttling_summary(targets)
    print_guidance(targets)


if __name__ == "__main__":
    main()
