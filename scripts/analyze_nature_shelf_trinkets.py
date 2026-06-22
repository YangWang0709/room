#!/usr/bin/env python3
"""Summarize NatureShelfTrinketsFactory timing CSV output."""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter, defaultdict
from pathlib import Path


DEFAULT_CSV = Path("/tmp/infinigen_nature_shelf_trinkets_timing.csv")

DURATION_FIELD = "create_asset_total_duration"
COUNT_FIELDS = [
    "created_material_count",
    "created_texture_count",
    "created_node_group_count",
    "created_mesh_count",
    "created_object_count",
]
SUBSTAGE_FIELDS = [
    "base_factory_spawn_duration",
    "join_children_duration",
    "apply_initial_transform_duration",
    "apply_modifiers_duration",
    "stable_pose_duration",
    "apply_rotation_transform_duration",
    "scale_and_position_duration",
    "apply_final_location_transform_duration",
]
NAME_FIELDS = [
    ("material", "created_material_names"),
    ("texture", "created_texture_names"),
    ("node_group", "created_node_group_names"),
]

BASE_FACTORY_STAGE_FIELDS = [
    DURATION_FIELD,
    "base_factory_spawn_duration",
    "stable_pose_duration",
    "apply_modifiers_duration",
]


def as_float(row: dict, field: str) -> float:
    value = row.get(field, "")
    if value in ("", None):
        return 0.0
    return float(value)


def as_int(row: dict, field: str) -> int:
    value = row.get(field, "")
    if value in ("", None):
        return 0
    return int(float(value))


def split_names(value: str) -> list[str]:
    if not value:
        return []
    return [name for name in value.split(";") if name]


def normalize_blender_name(name: str) -> str:
    return re.sub(r"\.\d{3,}$", "", name)


def fmt_seconds(seconds: float) -> str:
    return f"{seconds:9.3f}s"


def ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def read_rows(path: Path) -> list[dict]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def empty_base_stats() -> dict:
    stats = {
        "count": 0,
    }
    for field in BASE_FACTORY_STAGE_FIELDS:
        stats[f"{field}_total"] = 0.0
        stats[f"{field}_max"] = 0.0
    for field in COUNT_FIELDS:
        stats[field] = 0
    return stats


def build_base_factory_stats(rows: list[dict]) -> dict[str, dict]:
    by_base = defaultdict(empty_base_stats)
    for row in rows:
        base_factory = row.get("base_factory_class") or "(unknown)"
        stats = by_base[base_factory]
        stats["count"] += 1
        for field in BASE_FACTORY_STAGE_FIELDS:
            value = as_float(row, field)
            stats[f"{field}_total"] += value
            stats[f"{field}_max"] = max(stats[f"{field}_max"], value)
        for field in COUNT_FIELDS:
            stats[field] += as_int(row, field)
    return by_base


def average(stats: dict, total_field: str) -> float:
    if stats["count"] == 0:
        return 0.0
    return stats[total_field] / stats["count"]


def print_base_factory_top(by_base: dict[str, dict], limit: int = 20) -> None:
    print("Slowest base_factory_class top 20")
    print("-" * 38)
    print(
        "base_factory_class,count,total,avg,max,"
        "spawn_total,spawn_avg,spawn_max,"
        "stable_total,stable_avg,stable_max,"
        "modifiers_total,modifiers_avg,modifiers_max,"
        "materials,textures,node_groups,meshes,objects"
    )
    for base_factory, stats in sorted(
        by_base.items(),
        key=lambda item: item[1][f"{DURATION_FIELD}_total"],
        reverse=True,
    )[:limit]:
        print(
            f"{base_factory},"
            f"{stats['count']},"
            f"{stats[f'{DURATION_FIELD}_total']:.6f},"
            f"{average(stats, f'{DURATION_FIELD}_total'):.6f},"
            f"{stats[f'{DURATION_FIELD}_max']:.6f},"
            f"{stats['base_factory_spawn_duration_total']:.6f},"
            f"{average(stats, 'base_factory_spawn_duration_total'):.6f},"
            f"{stats['base_factory_spawn_duration_max']:.6f},"
            f"{stats['stable_pose_duration_total']:.6f},"
            f"{average(stats, 'stable_pose_duration_total'):.6f},"
            f"{stats['stable_pose_duration_max']:.6f},"
            f"{stats['apply_modifiers_duration_total']:.6f},"
            f"{average(stats, 'apply_modifiers_duration_total'):.6f},"
            f"{stats['apply_modifiers_duration_max']:.6f},"
            f"{stats['created_material_count']},"
            f"{stats['created_texture_count']},"
            f"{stats['created_node_group_count']},"
            f"{stats['created_mesh_count']},"
            f"{stats['created_object_count']}"
        )
    print()


def print_count_top(by_base: dict[str, dict], field: str, title: str) -> None:
    print(title)
    print("-" * 38)
    for base_factory, stats in sorted(
        by_base.items(), key=lambda item: item[1][field], reverse=True
    )[:20]:
        if stats[field] == 0:
            continue
        avg = stats[field] / stats["count"] if stats["count"] else 0.0
        print(
            f"{base_factory:28s} total={stats[field]:7d} "
            f"count={stats['count']:5d} avg={avg:8.3f}"
        )
    print()


def print_cause_summary(successful: list[dict], substage_totals: dict[str, float]):
    total_duration = sum(as_float(row, DURATION_FIELD) for row in successful)
    base_spawn_total = substage_totals.get("base_factory_spawn_duration", 0.0)
    stable_pose_total = substage_totals.get("stable_pose_duration", 0.0)
    modifiers_total = substage_totals.get("apply_modifiers_duration", 0.0)

    base_spawn_ratio = ratio(base_spawn_total, total_duration)
    stable_pose_ratio = ratio(stable_pose_total, total_duration)
    modifiers_ratio = ratio(modifiers_total, total_duration)

    print("Cause summary")
    print("-" * 38)
    print(
        "base_factory.spawn_asset ratio: "
        f"{base_spawn_ratio:.1%} "
        f"({fmt_seconds(base_spawn_total)} / {fmt_seconds(total_duration)})"
    )
    print(
        "stable_pose ratio: "
        f"{stable_pose_ratio:.1%} "
        f"({fmt_seconds(stable_pose_total)} / {fmt_seconds(total_duration)})"
    )
    print(
        "apply_modifiers ratio: "
        f"{modifiers_ratio:.1%} "
        f"({fmt_seconds(modifiers_total)} / {fmt_seconds(total_duration)})"
    )
    print(
        "base_factory.spawn_asset_is_primary: "
        f"{'yes' if base_spawn_ratio >= 0.5 else 'no'}"
    )
    print(
        "stable_pose_is_primary: "
        f"{'yes' if stable_pose_ratio >= 0.5 else 'no'}"
    )
    print()


def print_failed_instances(failed: list[dict]) -> None:
    if not failed:
        return

    print("Failed instances")
    print("-" * 38)
    by_error = Counter(
        (
            row.get("base_factory_class") or "(unknown)",
            row.get("error_type") or "(unknown)",
        )
        for row in failed
    )
    for (base_factory, error_type), count in by_error.most_common():
        print(f"{base_factory:28s} error={error_type:20s} count={count:5d}")
    print()


def summarize_rows(rows: list[dict]) -> None:
    successful = [row for row in rows if str(row.get("success", "")).lower() == "true"]
    failed = [row for row in rows if str(row.get("success", "")).lower() != "true"]
    durations = [as_float(row, DURATION_FIELD) for row in successful]
    total_duration = sum(durations)
    max_duration = max(durations, default=0.0)
    avg_duration = total_duration / len(successful) if successful else 0.0

    print("NatureShelfTrinkets timing summary")
    print("=" * 38)
    print(f"csv_rows: {len(rows)}")
    print(f"successful_instances: {len(successful)}")
    print(f"failed_instances: {len(rows) - len(successful)}")
    print(f"total_duration: {fmt_seconds(total_duration)}")
    print(f"avg_duration:   {fmt_seconds(avg_duration)}")
    print(f"max_duration:   {fmt_seconds(max_duration)}")
    print()

    print_failed_instances(failed)

    print("Created datablock summary")
    print("-" * 38)
    for field in COUNT_FIELDS:
        values = [as_int(row, field) for row in successful]
        total = sum(values)
        avg = total / len(values) if values else 0.0
        print(
            f"{field:28s} total={total:7d} avg={avg:8.3f} "
            f"max={max(values, default=0):5d}"
        )
    print()

    print("Substage duration totals")
    print("-" * 38)
    substage_totals = {
        field: sum(as_float(row, field) for row in successful)
        for field in SUBSTAGE_FIELDS
    }
    for field, total in sorted(
        substage_totals.items(), key=lambda item: item[1], reverse=True
    ):
        print(f"{field:42s} {fmt_seconds(total)}")
    print()

    by_base = build_base_factory_stats(successful)
    print_base_factory_top(by_base)
    print_count_top(
        by_base,
        "created_material_count",
        "Created materials by base_factory_class top 20",
    )
    print_count_top(
        by_base,
        "created_texture_count",
        "Created textures by base_factory_class top 20",
    )
    print_count_top(
        by_base,
        "created_node_group_count",
        "Created node_groups by base_factory_class top 20",
    )
    print_cause_summary(successful, substage_totals)

    print("Slowest individual sample top 20")
    print("-" * 38)
    for row in sorted(
        successful, key=lambda item: as_float(item, DURATION_FIELD), reverse=True
    )[:20]:
        dominant_stage = max(
            SUBSTAGE_FIELDS, key=lambda field: as_float(row, field), default=""
        )
        print(
            f"{fmt_seconds(as_float(row, DURATION_FIELD))} "
            f"base={row.get('base_factory_class', ''):24s} "
            f"materials={as_int(row, 'created_material_count'):4d} "
            f"textures={as_int(row, 'created_texture_count'):4d} "
            f"node_groups={as_int(row, 'created_node_group_count'):4d} "
            f"meshes={as_int(row, 'created_mesh_count'):4d} "
            f"objects={as_int(row, 'created_object_count'):4d} "
            f"dominant={dominant_stage}"
        )
    print()

    print("Repeated material/texture/node_group name signals")
    print("-" * 38)
    repeated_any = False
    for label, field in NAME_FIELDS:
        normalized_counts = Counter()
        distinct_names_by_base = defaultdict(set)
        for row in successful:
            for name in split_names(row.get(field, "")):
                base_name = normalize_blender_name(name)
                normalized_counts[base_name] += 1
                distinct_names_by_base[base_name].add(name)
        repeated = [
            (name, count, len(distinct_names_by_base[name]))
            for name, count in normalized_counts.items()
            if count > 1
        ]
        repeated.sort(key=lambda item: item[1], reverse=True)
        print(f"{label}: repeated_base_names={len(repeated)}")
        for name, count, distinct_count in repeated[:20]:
            repeated_any = True
            print(
                f"  {name:40s} total_created={count:5d} "
                f"distinct_suffixed_names={distinct_count:5d}"
            )
    print()

    print("Recommended next optimization direction")
    print("-" * 38)
    if not successful:
        print("No successful timing rows were found; collect a populate sample first.")
        return

    created_totals = {
        field: sum(as_int(row, field) for row in successful) for field in COUNT_FIELDS
    }
    dominant_substage = max(substage_totals, key=substage_totals.get)
    top_base = max(by_base, key=lambda name: by_base[name][f"{DURATION_FIELD}_total"])

    print(
        f"Top base factory by duration is {top_base}; first inspect its "
        "asset generation path before broad reuse changes."
    )
    print(
        f"Dominant measured substage is {dominant_substage} "
        f"({fmt_seconds(substage_totals[dominant_substage])})."
    )

    if repeated_any and (
        created_totals["created_material_count"]
        or created_totals["created_texture_count"]
        or created_totals["created_node_group_count"]
    ):
        print(
            "There is a repeated-name signal, so material/texture/nodegroup "
            "template reuse is worth investigating behind a separate opt-in gate."
        )
    else:
        print(
            "The CSV does not show a strong repeated-name signal; prioritize "
            "base-factory spawn, mesh realization, or stable-pose costs first."
        )

    if len(successful) < 10:
        print(
            "This is a very small sample. Treat single slow rows as leads, not "
            "as enough evidence for a behavior change."
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze NatureShelfTrinketsFactory timing CSV output."
    )
    parser.add_argument(
        "csv_path",
        nargs="?",
        type=Path,
        default=DEFAULT_CSV,
        help=f"Timing CSV path. Defaults to {DEFAULT_CSV}",
    )
    args = parser.parse_args()

    if not args.csv_path.exists():
        raise SystemExit(f"CSV not found: {args.csv_path}")

    summarize_rows(read_rows(args.csv_path))


if __name__ == "__main__":
    main()
