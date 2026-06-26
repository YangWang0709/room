#!/usr/bin/env python3
"""Check generated indoor scenes for carpet/rug floor-covering objects."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


FIELDNAMES = [
    "seed",
    "scene_dir",
    "object_name",
    "factory_class",
    "collections",
    "category",
    "tags",
    "bbox_min",
    "bbox_max",
    "bbox_extent",
    "carpet_object_count",
    "status",
    "source",
    "detail",
]

CARPET_WORDS = {
    "rug",
    "rugs",
    "carpet",
    "carpets",
    "doormat",
    "doormats",
    "floorcovering",
    "floorcoverings",
    "floor_covering",
    "floor_coverings",
    "floor-covering",
    "floor-coverings",
    "area_rug",
    "area-rug",
    "runner",
}
CARPET_FACTORY_RE = re.compile(
    r"\b((?:[A-Za-z_][A-Za-z0-9_]*)?"
    r"(?:Rug|Carpet|Doormat|FloorCovering|AreaRug|Runner)"
    r"[A-Za-z0-9_]*Factory|MatFactory)\b"
)


def blender_argv() -> list[str]:
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1 :]
    return sys.argv[1:]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="coarse directory, seed directory, or production output root")
    parser.add_argument("--allow-fail", action="store_true", help="return 0 even when carpets/rugs or unknowns are reported")
    parser.add_argument("--output-dir", type=Path, help="directory for no_carpet_report.csv/.md")
    parser.add_argument("--blender-bin", default=os.environ.get("BLENDER_BIN", "blender"))
    parser.add_argument("--inside-blender", action="store_true")
    return parser.parse_args(blender_argv())


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


def report_paths(output_dir: Path) -> tuple[Path, Path]:
    return output_dir / "no_carpet_report.csv", output_dir / "no_carpet_report.md"


def clean_cell(value: str, limit: int = 220) -> str:
    value = " ".join(str(value).split()).replace("|", "\\|")
    if len(value) > limit:
        return value[: limit - 3] + "..."
    return value


def tokenize(value: str) -> set[str]:
    lowered = value.lower()
    tokens = {token for token in re.split(r"[^a-z0-9_+-]+", lowered) if token}
    normalized = {token.replace("-", "_") for token in tokens}
    return tokens | normalized


def factory_from_value(value: str) -> str:
    if not value:
        return ""
    match = CARPET_FACTORY_RE.search(value)
    if match:
        return next(group for group in match.groups() if group)
    match = re.search(r"([A-Za-z_][A-Za-z0-9_]*Factory)\(", value)
    if match:
        return match.group(1)
    match = re.search(r"FromGenerator\(([A-Za-z_][A-Za-z0-9_]*Factory)\)", value)
    if match:
        return match.group(1)
    return ""


def factory_classes(state_obj: dict[str, Any]) -> list[str]:
    classes = []
    generator = state_obj.get("generator")
    if isinstance(generator, str):
        factory = factory_from_value(generator)
        if factory:
            classes.append(factory)
    for tag in state_obj.get("tags", []):
        if isinstance(tag, str) and "Factory" in tag:
            factory = factory_from_value(tag)
            if factory:
                classes.append(factory)
    return sorted(set(classes))


def carpet_category(
    object_name: str,
    factories: list[str],
    tags: list[str],
    collections: list[str] | None = None,
) -> tuple[str, str]:
    collections = collections or []
    for factory in factories:
        if CARPET_FACTORY_RE.search(factory):
            return "factory", f"factory class {factory}"

    tag_text = " ".join(tags)
    for token in tokenize(tag_text):
        if token in CARPET_WORDS or token in {"floormat", "floor_mat"}:
            return "category_tag", f"tag matched {token}"

    collection_text = " ".join(collections)
    for token in tokenize(collection_text):
        if token in CARPET_WORDS or token in {"floormat", "floor_mat"}:
            return "collection", f"collection matched {token}"

    for token in tokenize(object_name):
        if token in CARPET_WORDS:
            return "object_name", f"object name matched {token}"

    return "", ""


def blank_row(scene_dir: Path, status: str, source: str, detail: str) -> dict[str, str]:
    return {
        "seed": seed_from_path(scene_dir),
        "scene_dir": str(scene_dir),
        "object_name": "",
        "factory_class": "",
        "collections": "",
        "category": "",
        "tags": "",
        "bbox_min": "",
        "bbox_max": "",
        "bbox_extent": "",
        "carpet_object_count": "0",
        "status": status,
        "source": source,
        "detail": detail,
    }


def rows_from_solve_state(scene_dir: Path) -> tuple[list[dict[str, str]], bool]:
    state_path = scene_dir / "solve_state.json"
    if not state_path.exists():
        return [], False

    try:
        data = json.loads(state_path.read_text())
    except json.JSONDecodeError as exc:
        return [blank_row(scene_dir, "unknown", "solve_state", f"could not parse solve_state.json: {exc}")], True

    objs = data.get("objs")
    if not isinstance(objs, dict):
        return [blank_row(scene_dir, "unknown", "solve_state", "solve_state.json did not contain an objs dictionary")], True

    rows: list[dict[str, str]] = []
    for state_name, state_obj in sorted(objs.items()):
        if not isinstance(state_obj, dict) or not state_obj.get("active", True):
            continue
        tags = [str(tag) for tag in state_obj.get("tags", [])]
        factories = factory_classes(state_obj)
        object_name = str(state_obj.get("obj") or state_name)
        category, detail = carpet_category(object_name, factories, tags)
        if not category:
            continue
        rows.append(
            {
                "seed": seed_from_path(scene_dir),
                "scene_dir": str(scene_dir),
                "object_name": object_name,
                "factory_class": "; ".join(factories),
                "collections": "",
                "category": category,
                "tags": "; ".join(tags),
                "bbox_min": "",
                "bbox_max": "",
                "bbox_extent": "",
                "carpet_object_count": "",
                "status": "fail",
                "source": "solve_state",
                "detail": detail,
            }
        )

    if not rows:
        return [blank_row(scene_dir, "pass", "solve_state", "no carpet/rug objects found")], True

    count = str(len(rows))
    for row in rows:
        row["carpet_object_count"] = count
    return rows, True


def fmt_vec(values) -> str:
    return ",".join(f"{float(value):.4f}" for value in values)


def rows_from_open_blend(scene_dir: Path) -> list[dict[str, str]]:
    import bpy
    from mathutils import Vector

    rows: list[dict[str, str]] = []
    for obj in sorted(bpy.data.objects, key=lambda item: item.name):
        collections = sorted(collection.name for collection in obj.users_collection)
        tags = []
        for key in ("tags", "semantics", "category"):
            value = obj.get(key)
            if value:
                tags.append(str(value))
        factory = factory_from_value(
            " ".join([obj.name, str(obj.get("generator", "")), str(obj.get("factory_class", ""))])
        )
        factories = [factory] if factory else []
        category, detail = carpet_category(obj.name, factories, tags, collections)
        if not category:
            continue

        if obj.type == "MESH" and obj.data is not None:
            coords = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
            mins = [min(coord[i] for coord in coords) for i in range(3)]
            maxs = [max(coord[i] for coord in coords) for i in range(3)]
            extent = [maxs[i] - mins[i] for i in range(3)]
        else:
            mins = maxs = extent = []

        rows.append(
            {
                "seed": seed_from_path(scene_dir),
                "scene_dir": str(scene_dir),
                "object_name": obj.name,
                "factory_class": "; ".join(factories),
                "collections": "; ".join(collections),
                "category": category,
                "tags": "; ".join(tags),
                "bbox_min": fmt_vec(mins) if mins else "",
                "bbox_max": fmt_vec(maxs) if maxs else "",
                "bbox_extent": fmt_vec(extent) if extent else "",
                "carpet_object_count": "",
                "status": "fail",
                "source": "scene.blend",
                "detail": detail,
            }
        )

    if not rows:
        return [blank_row(scene_dir, "pass", "scene.blend", "no carpet/rug objects found")]

    count = str(len(rows))
    for row in rows:
        row["carpet_object_count"] = count
    return rows


def run_blender_for_scene(args: argparse.Namespace, scene_dir: Path) -> list[dict[str, str]]:
    scene_blend = scene_dir / "scene.blend"
    if not scene_blend.exists():
        return [blank_row(scene_dir, "unknown", "unknown", f"missing solve_state.json and scene.blend at {scene_dir}")]
    blender_bin = shutil.which(args.blender_bin)
    if blender_bin is None:
        return [blank_row(scene_dir, "unknown", "scene.blend", f"missing blender binary {args.blender_bin!r}")]

    env = os.environ.copy()
    env["NO_CARPET_SCENE_DIR"] = str(scene_dir)
    cmd = [
        blender_bin,
        "--background",
        str(scene_blend),
        "--python",
        str(Path(__file__).resolve()),
        "--",
        str(scene_dir),
        "--inside-blender",
    ]
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        detail = clean_cell((proc.stderr or proc.stdout or "").strip(), limit=500)
        return [blank_row(scene_dir, "unknown", "scene.blend", f"blender inspection failed: {detail}")]
    marker = "NO_CARPET_JSON:"
    payload_text = ""
    for line in proc.stdout.splitlines():
        if line.startswith(marker):
            payload_text = line[len(marker) :]
            break
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        return [blank_row(scene_dir, "unknown", "scene.blend", f"could not read blender inspection JSON: {exc}")]
    return payload["rows"]


def collect_rows(args: argparse.Namespace) -> list[dict[str, str]]:
    scene_dirs = discover_scene_dirs(args.path)
    rows: list[dict[str, str]] = []
    for scene_dir in scene_dirs:
        state_rows, used_state = rows_from_solve_state(scene_dir)
        if used_state:
            rows.extend(state_rows)
        else:
            rows.extend(run_blender_for_scene(args, scene_dir))
    return rows


def write_reports(output_dir: Path, rows: list[dict[str, str]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path, md_path = report_paths(output_dir)
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in FIELDNAMES})

    fail_rows = [row for row in rows if row.get("status") == "fail"]
    unknown_rows = [row for row in rows if row.get("status") == "unknown"]
    pass_rows = [row for row in rows if row.get("status") == "pass"]
    lines = [
        "# No Carpet Report",
        "",
        f"- rows: `{len(rows)}`",
        f"- pass: `{len(pass_rows)}`",
        f"- fail: `{len(fail_rows)}`",
        f"- unknown: `{len(unknown_rows)}`",
        f"- carpet_object_count: `{len(fail_rows)}`",
        "",
        "## Objects",
        "",
        "| seed | scene | object | factory | collections | category | bbox min | bbox max | bbox extent | status | source | detail |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                clean_cell(row.get(field, ""))
                for field in (
                    "seed",
                    "scene_dir",
                    "object_name",
                    "factory_class",
                    "collections",
                    "category",
                    "bbox_min",
                    "bbox_max",
                    "bbox_extent",
                    "status",
                    "source",
                    "detail",
                )
            )
            + " |"
        )
    md_path.write_text("\n".join(lines) + "\n")
    print(f"wrote {csv_path}")
    print(f"wrote {md_path}")
    print(
        "summary: "
        f"pass={len(pass_rows)} fail={len(fail_rows)} "
        f"unknown={len(unknown_rows)} carpet_object_count={len(fail_rows)}"
    )


def main() -> int:
    args = parse_args()
    if args.inside_blender:
        scene_dir = Path(os.environ.get("NO_CARPET_SCENE_DIR", args.path))
        rows = rows_from_open_blend(scene_dir)
        print("NO_CARPET_JSON:" + json.dumps({"rows": rows}))
        return 0

    output_dir = args.output_dir or args.path
    rows = collect_rows(args)
    write_reports(output_dir, rows)

    fail_count = sum(row.get("status") == "fail" for row in rows)
    unknown_count = sum(row.get("status") == "unknown" for row in rows)
    if args.allow_fail:
        return 0
    if fail_count:
        return 1
    if unknown_count:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
