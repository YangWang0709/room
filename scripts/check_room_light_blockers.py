#!/usr/bin/env python3
"""Report room objects that may block Dome Light in Isaac Sim."""

from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
import sys
from pathlib import Path


FIELDNAMES = [
    "object_name",
    "collections",
    "type",
    "vertex_count",
    "polygon_count",
    "bbox_min",
    "bbox_max",
    "bbox_extent",
    "material_names",
    "suspected_category",
    "detail",
]


def blender_argv() -> list[str]:
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1 :]
    return sys.argv[1:]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="coarse directory or scene.blend")
    parser.add_argument("--output-dir", type=Path, help="directory for reports")
    parser.add_argument("--blender-bin", default="blender")
    parser.add_argument("--inside-blender", action="store_true")
    return parser.parse_args(blender_argv())


def scene_blend_from_path(path: Path) -> Path:
    if path.is_file() and path.name.endswith(".blend"):
        return path
    return path / "scene.blend"


def report_paths(output_dir: Path) -> tuple[Path, Path]:
    return output_dir / "light_blockers_report.csv", output_dir / "light_blockers_report.md"


def clean_cell(value: str) -> str:
    return " ".join(str(value).split()).replace("|", "\\|")


def write_reports(output_dir: Path, rows: list[dict[str, str]], message: str = "") -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path, md_path = report_paths(output_dir)
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in FIELDNAMES})

    category_counts: dict[str, int] = {}
    for row in rows:
        category = row.get("suspected_category", "")
        if row.get("object_name") and category:
            category_counts[category] = category_counts.get(category, 0) + 1

    lines = [
        "# Room Light Blockers Report",
        "",
        f"- rows: `{len([row for row in rows if row.get('object_name')])}`",
        f"- exterior: `{category_counts.get('exterior', 0)}`",
        f"- pillar: `{category_counts.get('pillar', 0)}`",
        f"- ceiling: `{category_counts.get('ceiling', 0)}`",
        f"- unknown_frame: `{category_counts.get('unknown_frame', 0)}`",
    ]
    if message:
        lines.extend(["", "## Message", "", message])
    lines.extend(
        [
            "",
            "## Objects",
            "",
            "| object | collections | type | verts | polys | bbox min | bbox max | bbox extent | materials | category | detail |",
            "| --- | --- | --- | ---: | ---: | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in rows:
        if not row.get("object_name"):
            continue
        lines.append(
            "| "
            + " | ".join(
                clean_cell(row.get(field, ""))
                for field in (
                    "object_name",
                    "collections",
                    "type",
                    "vertex_count",
                    "polygon_count",
                    "bbox_min",
                    "bbox_max",
                    "bbox_extent",
                    "material_names",
                    "suspected_category",
                    "detail",
                )
            )
            + " |"
        )
    md_path.write_text("\n".join(lines) + "\n")
    print(f"wrote {csv_path}")
    print(f"wrote {md_path}")


def failure_row(detail: str) -> dict[str, str]:
    return {
        "object_name": "",
        "collections": "",
        "type": "",
        "vertex_count": "",
        "polygon_count": "",
        "bbox_min": "",
        "bbox_max": "",
        "bbox_extent": "",
        "material_names": "",
        "suspected_category": "error",
        "detail": detail,
    }


def fmt_vec(values) -> str:
    return ",".join(f"{float(value):.4f}" for value in values)


def inspect_with_bpy() -> list[dict[str, str]]:
    import bpy
    from mathutils import Vector

    rows: list[dict[str, str]] = []

    for obj in sorted(bpy.data.objects, key=lambda item: item.name):
        collections = sorted(collection.name for collection in obj.users_collection)
        joined = " ".join([obj.name, *collections]).lower()
        category = ""
        detail = ""

        if "room_exterior" in joined or "exterior" in obj.name.lower():
            category = "exterior"
        elif "pillars" in joined or "pillar" in obj.name.lower():
            category = "pillar"
        elif "ceiling" in joined:
            category = "ceiling"
        elif obj.type == "MESH" and "room" in joined and "wall" not in joined and "floor" not in joined:
            coords = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
            if coords:
                mins = [min(coord[i] for coord in coords) for i in range(3)]
                maxs = [max(coord[i] for coord in coords) for i in range(3)]
                extent = [maxs[i] - mins[i] for i in range(3)]
                if max(extent[:2]) > 1.0 and maxs[2] > 2.0:
                    category = "unknown_frame"
                    detail = "large room-like mesh near the upper room volume"

        if not category:
            continue

        if obj.type == "MESH" and obj.data is not None:
            vertex_count = str(len(obj.data.vertices))
            polygon_count = str(len(obj.data.polygons))
            material_names = "; ".join(
                slot.material.name
                for slot in obj.material_slots
                if slot.material is not None
            )
            coords = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
            mins = [min(coord[i] for coord in coords) for i in range(3)]
            maxs = [max(coord[i] for coord in coords) for i in range(3)]
            extent = [maxs[i] - mins[i] for i in range(3)]
        else:
            vertex_count = ""
            polygon_count = ""
            material_names = ""
            mins = maxs = extent = []

        rows.append(
            {
                "object_name": obj.name,
                "collections": "; ".join(collections),
                "type": obj.type,
                "vertex_count": vertex_count,
                "polygon_count": polygon_count,
                "bbox_min": fmt_vec(mins) if mins else "",
                "bbox_max": fmt_vec(maxs) if maxs else "",
                "bbox_extent": fmt_vec(extent) if extent else "",
                "material_names": material_names,
                "suspected_category": category,
                "detail": detail,
            }
        )

    return rows


def open_scene_with_bpy(scene_blend: Path) -> None:
    import bpy

    bpy.ops.wm.open_mainfile(filepath=str(scene_blend))


def run_via_blender(args: argparse.Namespace, scene_blend: Path, output_dir: Path) -> int:
    blender_bin = shutil.which(args.blender_bin)
    if blender_bin is None:
        detail = (
            f"Blender binary {args.blender_bin!r} was not found. "
            "Run this script with Blender available, or run Blender background "
            "directly to inspect scene.blend."
        )
        write_reports(output_dir, [failure_row(detail)], detail)
        print(f"ERROR: {detail}", file=sys.stderr)
        return 2

    cmd = [
        blender_bin,
        "--background",
        str(scene_blend),
        "--python",
        str(Path(__file__).resolve()),
        "--",
        str(args.path),
        "--output-dir",
        str(output_dir),
        "--inside-blender",
    ]
    return subprocess.run(cmd, check=False).returncode


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir or args.path
    scene_blend = scene_blend_from_path(args.path)

    if not scene_blend.exists():
        detail = f"Missing scene.blend at {scene_blend}"
        write_reports(output_dir, [failure_row(detail)], detail)
        print(f"ERROR: {detail}", file=sys.stderr)
        return 2

    if not args.inside_blender:
        try:
            import bpy  # noqa: F401
        except ImportError:
            return run_via_blender(args, scene_blend, output_dir)
        try:
            open_scene_with_bpy(scene_blend)
        except Exception as exc:
            detail = f"Could not open scene.blend with bpy module: {exc}"
            write_reports(output_dir, [failure_row(detail)], detail)
            print(f"ERROR: {detail}", file=sys.stderr)
            return 2

    try:
        rows = inspect_with_bpy()
    except ImportError:
        detail = "Could not import bpy. Run with Blender background to inspect scene.blend."
        write_reports(output_dir, [failure_row(detail)], detail)
        print(f"ERROR: {detail}", file=sys.stderr)
        return 2

    message = f"Inspected {scene_blend}"
    write_reports(output_dir, rows, message)
    print(
        "summary: "
        f"exterior={sum(row['suspected_category'] == 'exterior' for row in rows)} "
        f"pillar={sum(row['suspected_category'] == 'pillar' for row in rows)} "
        f"ceiling={sum(row['suspected_category'] == 'ceiling' for row in rows)} "
        f"unknown_frame={sum(row['suspected_category'] == 'unknown_frame' for row in rows)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
