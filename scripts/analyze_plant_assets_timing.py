#!/usr/bin/env python3
"""Summarize PlantContainer / LargePlantContainer populate timing CSV output."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path


DEFAULT_CSV = Path("/tmp/infinigen_plant_assets_timing.csv")
DURATION_FIELD = "create_asset_total_duration"
COUNT_FIELDS = [
    "created_mesh_count",
    "created_material_count",
    "created_texture_count",
    "created_node_group_count",
    "created_object_count",
    "created_image_count",
]
STAGE_FIELDS = [
    "geometry_duration",
    "material_duration",
    "pot_create_duration",
    "pot_finalize_duration",
    "dirt_geometry_duration",
    "dirt_material_duration",
    "plant_spawn_duration",
    "plant_finalize_duration",
    "plant_place_duration",
    "join_duration",
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


def fmt_seconds(value: float) -> str:
    return f"{value:9.3f}s"


def read_rows(path: Path) -> list[dict]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def successful_rows(rows: list[dict]) -> list[dict]:
    return [row for row in rows if str(row.get("success", "")).lower() == "true"]


def failed_rows(rows: list[dict]) -> list[dict]:
    return [row for row in rows if str(row.get("success", "")).lower() != "true"]


def aggregate(rows: list[dict], key_field: str) -> dict[str, dict]:
    by_key = defaultdict(lambda: defaultdict(float))
    for row in rows:
        key = row.get(key_field) or "(unknown)"
        stats = by_key[key]
        stats["count"] += 1
        stats["total_duration"] += as_float(row, DURATION_FIELD)
        stats["max_duration"] = max(
            stats["max_duration"], as_float(row, DURATION_FIELD)
        )
        for field in STAGE_FIELDS + COUNT_FIELDS:
            stats[field] += as_float(row, field)
    return by_key


def print_duration_top(by_key: dict[str, dict], title: str) -> None:
    print(title)
    print("-" * 38)
    print(
        "class,count,total,avg,max,geometry,material,pot_create,dirt_geometry,"
        "dirt_material,plant_spawn,plant_finalize,join,meshes,materials,"
        "textures,node_groups,objects,images"
    )
    for key, stats in sorted(
        by_key.items(), key=lambda item: item[1]["total_duration"], reverse=True
    )[:20]:
        count = stats["count"]
        print(
            f"{key},"
            f"{int(count)},"
            f"{stats['total_duration']:.6f},"
            f"{stats['total_duration'] / count if count else 0.0:.6f},"
            f"{stats['max_duration']:.6f},"
            f"{stats['geometry_duration']:.6f},"
            f"{stats['material_duration']:.6f},"
            f"{stats['pot_create_duration']:.6f},"
            f"{stats['dirt_geometry_duration']:.6f},"
            f"{stats['dirt_material_duration']:.6f},"
            f"{stats['plant_spawn_duration']:.6f},"
            f"{stats['plant_finalize_duration']:.6f},"
            f"{stats['join_duration']:.6f},"
            f"{int(stats['created_mesh_count'])},"
            f"{int(stats['created_material_count'])},"
            f"{int(stats['created_texture_count'])},"
            f"{int(stats['created_node_group_count'])},"
            f"{int(stats['created_object_count'])},"
            f"{int(stats['created_image_count'])}"
        )
    print()


def print_count_top(by_factory: dict[str, dict], field: str, title: str) -> None:
    print(title)
    print("-" * 38)
    for factory, stats in sorted(
        by_factory.items(), key=lambda item: item[1][field], reverse=True
    )[:20]:
        if stats[field] == 0:
            continue
        print(
            f"{factory:28s} total={int(stats[field]):6d} "
            f"count={int(stats['count']):5d}"
        )
    print()


def print_slowest(rows: list[dict], limit: int = 20) -> None:
    print("slowest samples top")
    print("-" * 38)
    for row in sorted(rows, key=lambda item: as_float(item, DURATION_FIELD), reverse=True)[
        :limit
    ]:
        dominant_stage = max(STAGE_FIELDS, key=lambda field: as_float(row, field))
        print(
            f"{fmt_seconds(as_float(row, DURATION_FIELD))} "
            f"factory={row.get('factory_class', ''):28s} "
            f"plant={row.get('plant_factory_class', ''):24s} "
            f"meshes={as_int(row, 'created_mesh_count'):4d} "
            f"materials={as_int(row, 'created_material_count'):3d} "
            f"textures={as_int(row, 'created_texture_count'):3d} "
            f"node_groups={as_int(row, 'created_node_group_count'):4d} "
            f"dominant={dominant_stage}"
        )
    print()


def print_recommendation(rows: list[dict], by_factory: dict[str, dict]) -> None:
    print("optimization direction")
    print("-" * 38)
    if not rows:
        print("No successful rows were found.")
        return

    top_factory = max(by_factory, key=lambda name: by_factory[name]["total_duration"])
    total_meshes = sum(as_int(row, "created_mesh_count") for row in rows)
    total_materials = sum(as_int(row, "created_material_count") for row in rows)
    total_node_groups = sum(as_int(row, "created_node_group_count") for row in rows)
    stage_totals = {
        field: sum(as_float(row, field) for row in rows) for field in STAGE_FIELDS
    }
    dominant_stage = max(stage_totals, key=stage_totals.get)
    print(f"Top duration factory: {top_factory}")
    print(f"Dominant measured stage: {dominant_stage}")
    if total_materials or total_node_groups:
        print(
            "Material/nodegroup reuse is worth investigating only after checking "
            "the concrete plant subfactory, because leaf/stem node graphs often "
            "carry per-instance shape and material variation."
        )
    if total_meshes >= len(rows) * 3:
        print(
            "Plant template reuse may be worth a later opt-in experiment, but "
            "visual risk is high for leaf/stem geometry and should not be "
            "simplified without a quality gate."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", nargs="?", type=Path, default=DEFAULT_CSV)
    args = parser.parse_args()

    if not args.csv_path.exists():
        raise SystemExit(f"CSV not found: {args.csv_path}")

    rows = read_rows(args.csv_path)
    successful = successful_rows(rows)
    failed = failed_rows(rows)
    total = sum(as_float(row, DURATION_FIELD) for row in successful)

    print("Plant asset timing summary")
    print("=" * 38)
    print(f"csv_rows: {len(rows)}")
    print(f"successful_rows: {len(successful)}")
    print(f"failed_rows: {len(failed)}")
    print(f"total_duration: {fmt_seconds(total)}")
    print(f"avg_duration:   {fmt_seconds(total / len(successful) if successful else 0.0)}")
    print(
        f"max_duration:   "
        f"{fmt_seconds(max((as_float(row, DURATION_FIELD) for row in successful), default=0.0))}"
    )
    print()

    if failed:
        print("failure summary")
        print("-" * 38)
        for row in failed[:20]:
            print(
                f"factory={row.get('factory_class', '')} "
                f"error={row.get('error_type', '')}"
            )
        print()

    by_factory = aggregate(successful, "factory_class")
    by_plant = aggregate(successful, "plant_factory_class")
    print_duration_top(by_factory, "factory_class duration top")
    print_duration_top(by_plant, "plant_factory_class duration top")
    print_count_top(by_factory, "created_mesh_count", "created mesh count top")
    print_count_top(by_factory, "created_material_count", "created material count top")
    print_count_top(by_factory, "created_texture_count", "created texture count top")
    print_count_top(
        by_factory, "created_node_group_count", "created node_group count top"
    )
    print_slowest(successful)
    print_recommendation(successful, by_factory)


if __name__ == "__main__":
    main()
