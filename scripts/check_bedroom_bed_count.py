#!/usr/bin/env python3
"""Check that generated bedrooms contain at most one bed-like object."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


FIELDNAMES = [
    "seed",
    "scene_dir",
    "room_name",
    "room_type",
    "bed_count",
    "bed_object_names",
    "factory_classes",
    "object_locations",
    "status",
    "source",
    "detail",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="coarse directory, seed directory, or production output root")
    parser.add_argument("--allow-fail", action="store_true", help="return 0 even when a bedroom has more than one bed")
    parser.add_argument("--output-dir", type=Path, help="directory for bedroom_bed_count_report.csv/.md")
    parser.add_argument("--blender-bin", default=os.environ.get("BLENDER_BIN", "blender"))
    parser.add_argument("--blender-timeout", type=float, default=120.0)
    return parser.parse_args()


def seed_from_path(path: Path) -> str:
    for part in reversed(path.parts):
        match = re.fullmatch(r"seed_(.+)", part)
        if match:
            return match.group(1)
    return path.name


def discover_scene_dirs(path: Path) -> list[Path]:
    if (path / "solve_state.json").exists() or (path / "scene.blend").exists():
        return [path]
    if (path / "coarse").exists():
        return [path / "coarse"]
    seed_coarse_dirs = sorted(
        candidate
        for candidate in path.glob("seed_*/coarse")
        if candidate.is_dir()
    )
    if seed_coarse_dirs:
        return seed_coarse_dirs
    return [path]


def has_tag(tags: list[str], semantic: str) -> bool:
    return f"Semantics({semantic})" in tags


def tag_semantics(tags: list[str]) -> set[str]:
    values = set()
    for tag in tags:
        match = re.fullmatch(r"Semantics\((.+)\)", tag)
        if match:
            values.add(match.group(1))
    return values


def factory_from_value(value: str) -> str:
    if not value:
        return ""
    match = re.search(r"([A-Za-z_][A-Za-z0-9_]*Factory)\(", value)
    if match:
        return match.group(1)
    match = re.search(r"FromGenerator\(([A-Za-z_][A-Za-z0-9_]*Factory)\)", value)
    if match:
        return match.group(1)
    return value


def factory_classes(state_obj: dict[str, Any]) -> list[str]:
    classes = []
    generator = state_obj.get("generator")
    if isinstance(generator, str):
        factory = factory_from_value(generator)
        if factory:
            classes.append(factory)
    for tag in state_obj.get("tags", []):
        if isinstance(tag, str) and tag.startswith("FromGenerator("):
            factory = factory_from_value(tag)
            if factory:
                classes.append(factory)
    return sorted(set(classes))


def is_bed_like(name: str, state_obj: dict[str, Any]) -> bool:
    tags = state_obj.get("tags", [])
    if has_tag(tags, "bed"):
        return True
    classes = factory_classes(state_obj)
    if any(factory in {"BedFactory", "BedFrameFactory"} for factory in classes):
        return True
    generator = str(state_obj.get("generator") or "")
    return "BedFactory" in generator or "Semantics(bed)" in " ".join(tags)


def relation_targets(state_obj: dict[str, Any]) -> set[str]:
    targets = set()
    for relation in state_obj.get("relations", []):
        if isinstance(relation, dict) and relation.get("target_name"):
            targets.add(str(relation["target_name"]))
    return targets


def object_location(state_obj: dict[str, Any]) -> str:
    location = state_obj.get("location") or state_obj.get("obj_location")
    if isinstance(location, list) and len(location) >= 3:
        return ",".join(f"{float(v):.4f}" for v in location[:3])
    return ""


def rows_from_solve_state(scene_dir: Path) -> tuple[list[dict[str, str]], bool]:
    state_path = scene_dir / "solve_state.json"
    if not state_path.exists():
        return [], False
    with state_path.open() as handle:
        data = json.load(handle)
    objs = data.get("objs")
    if not isinstance(objs, dict):
        return [
            unknown_row(
                scene_dir,
                "solve_state.json did not contain an objs dictionary",
                source="solve_state",
            )
        ], True

    bedrooms = {
        name: value
        for name, value in objs.items()
        if isinstance(value, dict)
        and value.get("active", True)
        and has_tag(value.get("tags", []), "bedroom")
        and has_tag(value.get("tags", []), "room")
    }
    bed_objects = {
        name: value
        for name, value in objs.items()
        if isinstance(value, dict)
        and value.get("active", True)
        and is_bed_like(name, value)
    }

    rows = []
    if not bedrooms:
        return [
            unknown_row(scene_dir, "no active bedroom rooms found in solve_state.json")
        ], True

    for room_name, room_obj in sorted(bedrooms.items()):
        room_beds = []
        for bed_name, bed_obj in bed_objects.items():
            if room_name in relation_targets(bed_obj):
                room_beds.append((bed_name, bed_obj))

        room_type = ",".join(sorted(tag_semantics(room_obj.get("tags", []))))
        bed_names = [bed_obj.get("obj") or bed_name for bed_name, bed_obj in room_beds]
        bed_factories = sorted(
            {
                factory
                for _, bed_obj in room_beds
                for factory in factory_classes(bed_obj)
            }
        )
        locations = [object_location(bed_obj) for _, bed_obj in room_beds]
        locations = [location for location in locations if location]
        bed_count = len(room_beds)
        status = "fail" if bed_count > 1 else "pass"
        rows.append(
            {
                "seed": seed_from_path(scene_dir),
                "scene_dir": str(scene_dir),
                "room_name": room_name,
                "room_type": room_type,
                "bed_count": str(bed_count),
                "bed_object_names": "; ".join(str(name) for name in bed_names),
                "factory_classes": "; ".join(bed_factories),
                "object_locations": "; ".join(locations),
                "status": status,
                "source": "solve_state",
                "detail": "",
            }
        )
    return rows, True


def unknown_row(scene_dir: Path, detail: str, source: str = "unknown") -> dict[str, str]:
    return {
        "seed": seed_from_path(scene_dir),
        "scene_dir": str(scene_dir),
        "room_name": "",
        "room_type": "",
        "bed_count": "",
        "bed_object_names": "",
        "factory_classes": "",
        "object_locations": "",
        "status": "unknown",
        "source": source,
        "detail": detail,
    }


def rows_from_blender(scene_dir: Path, blender_bin: str, timeout: float) -> list[dict[str, str]]:
    scene_blend = scene_dir / "scene.blend"
    if not scene_blend.exists():
        return [unknown_row(scene_dir, "missing solve_state.json and scene.blend")]
    if shutil.which(blender_bin) is None:
        return [unknown_row(scene_dir, f"missing solve_state.json and blender binary {blender_bin!r}")]

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        summary_path = Path(tmp.name)
    expr = r"""
import json
import os
import bpy

def factory_from_name(name):
    for part in name.replace(".", "_").split("_"):
        if part.endswith("Factory"):
            return part
    if "BedFactory" in name:
        return "BedFactory"
    return ""

bed_objects = []
bedrooms = []
for obj in bpy.data.objects:
    text = " ".join([obj.name, str(obj.get("generator", "")), str(obj.get("tags", ""))])
    if "bedroom" in obj.name.lower():
        bedrooms.append(obj.name)
    if "Semantics(bed)" in text or "BedFactory" in text:
        bed_objects.append({
            "name": obj.name,
            "factory": factory_from_name(text),
            "location": [float(v) for v in obj.location],
        })
with open(os.environ["BEDROOM_BED_COUNT_SUMMARY"], "w") as handle:
    json.dump({"bedrooms": bedrooms, "bed_objects": bed_objects}, handle)
"""
    env = os.environ.copy()
    env["BEDROOM_BED_COUNT_SUMMARY"] = str(summary_path)
    try:
        subprocess.run(
            [blender_bin, "--background", str(scene_blend), "--python-expr", expr],
            check=True,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
        summary = json.loads(summary_path.read_text())
    except Exception as exc:
        return [unknown_row(scene_dir, f"Blender fallback failed: {exc}", source="blender")]
    finally:
        summary_path.unlink(missing_ok=True)

    bed_names = [item.get("name", "") for item in summary.get("bed_objects", [])]
    factories = sorted({item.get("factory", "") for item in summary.get("bed_objects", []) if item.get("factory")})
    locations = [
        ",".join(f"{float(v):.4f}" for v in item.get("location", [])[:3])
        for item in summary.get("bed_objects", [])
    ]
    locations = [location for location in locations if location]
    bedrooms = summary.get("bedrooms") or [""]
    rows = []
    for bedroom in bedrooms:
        rows.append(
            {
                "seed": seed_from_path(scene_dir),
                "scene_dir": str(scene_dir),
                "room_name": bedroom,
                "room_type": "bedroom" if bedroom else "",
                "bed_count": "",
                "bed_object_names": "; ".join(bed_names),
                "factory_classes": "; ".join(factories),
                "object_locations": "; ".join(locations),
                "status": "unknown",
                "source": "blender",
                "detail": "solve_state.json missing; Blender fallback cannot reliably map beds to bedrooms",
            }
        )
    return rows


def collect_rows(args: argparse.Namespace) -> list[dict[str, str]]:
    rows = []
    for scene_dir in discover_scene_dirs(args.path):
        state_rows, had_state = rows_from_solve_state(scene_dir)
        if had_state:
            rows.extend(state_rows)
        else:
            rows.extend(rows_from_blender(scene_dir, args.blender_bin, args.blender_timeout))
    return rows


def clean_cell(value: str) -> str:
    return " ".join(value.split()).replace("|", "\\|")


def render_markdown(rows: list[dict[str, str]]) -> str:
    lines = [
        "# Bedroom Bed Count Report",
        "",
        f"- rows: `{len(rows)}`",
        f"- pass: `{sum(row['status'] == 'pass' for row in rows)}`",
        f"- fail: `{sum(row['status'] == 'fail' for row in rows)}`",
        f"- unknown: `{sum(row['status'] == 'unknown' for row in rows)}`",
        "",
        "| seed | room | type | bed_count | status | bed objects | factories | source | detail |",
        "| --- | --- | --- | ---: | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                clean_cell(row.get(field, ""))
                for field in (
                    "seed",
                    "room_name",
                    "room_type",
                    "bed_count",
                    "status",
                    "bed_object_names",
                    "factory_classes",
                    "source",
                    "detail",
                )
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def write_reports(output_dir: Path, rows: list[dict[str, str]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "bedroom_bed_count_report.csv"
    md_path = output_dir / "bedroom_bed_count_report.md"
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    md_path.write_text(render_markdown(rows))
    print(f"wrote {csv_path}")
    print(f"wrote {md_path}")


def main() -> int:
    args = parse_args()
    rows = collect_rows(args)
    output_dir = args.output_dir or args.path
    write_reports(output_dir, rows)
    print(render_markdown(rows))

    failed = [row for row in rows if row["status"] == "fail"]
    if failed and not args.allow_fail:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
