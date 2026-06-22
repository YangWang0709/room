#!/usr/bin/env python3
"""Summarize PlantContainer / LargePlantContainer populate timing CSV output."""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
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
    "container_spawn_duration",
    "geometry_duration",
    "material_duration",
    "pot_create_duration",
    "pot_finalize_duration",
    "dirt_geometry_duration",
    "dirt_material_duration",
    "plant_spawn_duration",
    "leaf_generation_duration",
    "stem_generation_duration",
    "branch_generation_duration",
    "material_generation_duration",
    "nodegroup_generation_duration",
    "modifier_apply_duration",
    "plant_finalize_duration",
    "plant_place_duration",
    "join_duration",
    "join_objects_duration",
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


def parse_prefix_top(value: str) -> Counter:
    counter = Counter()
    if not value:
        return counter
    for part in value.split(";"):
        if not part or ":" not in part:
            continue
        prefix, count = part.rsplit(":", 1)
        try:
            counter[prefix] += int(float(count))
        except ValueError:
            continue
    return counter


def prefix_counter(rows: list[dict], field: str) -> Counter:
    counter = Counter()
    for row in rows:
        counter.update(parse_prefix_top(row.get(field, "")))
    return counter


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


def print_stage_summary(rows: list[dict]) -> None:
    print("substage duration summary")
    print("-" * 38)
    totals = {field: sum(as_float(row, field) for row in rows) for field in STAGE_FIELDS}
    total_duration = sum(as_float(row, DURATION_FIELD) for row in rows)
    print("stage,total,share_of_total")
    for field, value in sorted(totals.items(), key=lambda item: item[1], reverse=True):
        share = value / total_duration if total_duration else 0.0
        print(f"{field},{value:.6f},{share:.3%}")
    print()


def print_plant_spawn_top(rows: list[dict], limit: int = 20) -> None:
    print("plant_spawn_duration top")
    print("-" * 38)
    for row in sorted(
        rows, key=lambda item: as_float(item, "plant_spawn_duration"), reverse=True
    )[:limit]:
        print(
            f"{fmt_seconds(as_float(row, 'plant_spawn_duration'))} "
            f"total={as_float(row, DURATION_FIELD):.3f}s "
            f"factory={row.get('factory_class', ''):28s} "
            f"plant={row.get('plant_factory_class', ''):20s} "
            f"concrete={row.get('concrete_plant_factory_class', ''):28s} "
            f"leaf={as_float(row, 'leaf_generation_duration'):.3f}s "
            f"stem={as_float(row, 'stem_generation_duration'):.3f}s "
            f"branch={as_float(row, 'branch_generation_duration'):.3f}s "
            f"node_groups={as_int(row, 'created_node_group_count'):4d}"
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


def print_creation_totals(rows: list[dict]) -> None:
    print("created datablock totals")
    print("-" * 38)
    for field in COUNT_FIELDS:
        print(f"{field}: {sum(as_int(row, field) for row in rows)}")
    print()


def print_prefix_top(rows: list[dict], field: str, title: str, limit: int = 50) -> None:
    print(title)
    print("-" * 38)
    counter = prefix_counter(rows, field)
    if not counter:
        print("(none)")
    for prefix, count in counter.most_common(limit):
        print(f"{prefix},{count}")
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
            f"concrete={row.get('concrete_plant_factory_class', ''):28s} "
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
    total_textures = sum(as_int(row, "created_texture_count") for row in rows)
    total_node_groups = sum(as_int(row, "created_node_group_count") for row in rows)
    stage_totals = {
        field: sum(as_float(row, field) for row in rows) for field in STAGE_FIELDS
    }
    dominant_stage = max(stage_totals, key=stage_totals.get)
    print(f"Top duration factory: {top_factory}")
    print(f"Dominant measured stage: {dominant_stage}")
    print(f"Total created meshes/materials/textures/nodegroups: {total_meshes}/{total_materials}/{total_textures}/{total_node_groups}")

    if stage_totals.get("plant_spawn_duration", 0.0) > stage_totals.get(
        "container_spawn_duration", 0.0
    ):
        print(
            "Primary next target: concrete plant spawn internals, not the pot/container wrapper."
        )
    else:
        print("Container work is competitive with plant spawn; inspect pot/dirt stages first.")

    if stage_totals.get("material_generation_duration", 0.0) > 0.25 * sum(
        as_float(row, DURATION_FIELD) for row in rows
    ):
        print(
            "Material reuse may be worth an opt-in experiment such as "
            "INFINIGEN_REUSE_PLANT_MATERIALS=1, but only if per-instance "
            "color/noise variation is preserved."
        )
    elif total_materials:
        print(
            "Material creation exists but is not the dominant measured stage in this CSV."
        )

    if total_node_groups:
        print(
            "Nodegroup reuse may be worth investigating with "
            "INFINIGEN_REUSE_PLANT_NODEGROUPS=1 only for fixed helper groups. "
            "Top-level leaf/stem graphs often encode per-instance parameters."
        )

    if total_meshes >= len(rows) * 3 or stage_totals.get(
        "leaf_generation_duration", 0.0
    ) + stage_totals.get("stem_generation_duration", 0.0) + stage_totals.get(
        "branch_generation_duration", 0.0
    ) > 0.5 * stage_totals.get("plant_spawn_duration", 0.0):
        print(
            "Plant template geometry reuse/simplification may be the larger lever, "
            "but it is high visual risk and should only be tried behind "
            "INFINIGEN_REUSE_PLANT_TEMPLATE_GEOMETRY=1 with a quality gate."
        )
    print("Do not reduce plant count or complexity as the next default path.")


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
    by_concrete_plant = aggregate(successful, "concrete_plant_factory_class")
    print_duration_top(by_factory, "factory_class duration top")
    print_duration_top(by_plant, "plant_factory_class duration top")
    print_duration_top(by_concrete_plant, "concrete_plant_factory_class duration top")
    print_plant_spawn_top(successful, limit=20)
    print_stage_summary(successful)
    print_creation_totals(successful)
    print_count_top(by_factory, "created_mesh_count", "created mesh count top")
    print_count_top(by_factory, "created_material_count", "created material count top")
    print_count_top(by_factory, "created_texture_count", "created texture count top")
    print_count_top(
        by_factory, "created_node_group_count", "created node_group count top"
    )
    print_prefix_top(successful, "created_material_prefix_top", "material prefix top 50")
    print_prefix_top(
        successful, "created_node_group_prefix_top", "nodegroup prefix top 50"
    )
    print_slowest(successful)
    print_recommendation(successful, by_factory)


if __name__ == "__main__":
    main()
