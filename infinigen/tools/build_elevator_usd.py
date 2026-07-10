"""Build post-export USD elevator articulations and a composed scene wrapper.

Example:

.. code-block:: bash

    python -m infinigen.tools.build_elevator_usd \
      --manifest outputs/scene/coarse/elevator_manifest.json \
      --building-usd outputs/scene/usd/export_scene.blend/export_scene.usdc \
      --output-dir outputs/scene/usd/elevator

Use ``--plan-only`` to validate the manifest and emit a deterministic JSON
articulation plan without importing OpenUSD.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from infinigen.core.sim.elevator_manifest import (
    ManifestValidationError,
    read_manifest,
)
from infinigen.core.sim.elevator_usd import (
    USDAuthoringError,
    USDDependencyError,
    author_elevator_usd,
    build_usd_plan,
    write_usd_plan,
    write_wrapper_usda,
)


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate an elevator manifest, author an independent USD Physics "
            "articulation layer, and compose it with a static building USD."
        )
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--building-usd",
        type=Path,
        help="Static Infinigen building USD/USDC; required unless --plan-only",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--elevator-format",
        choices=("usda", "usdc"),
        default="usda",
        help="Format for the independent elevator articulation layer",
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Only validate and write elevator_plan.json; does not import pxr",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow replacing tool-owned output files",
    )
    return parser


def run(args: argparse.Namespace) -> tuple[Path, Path | None, Path | None]:
    manifest = read_manifest(args.manifest)
    plan = build_usd_plan(manifest)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    plan_path = args.output_dir / "elevator_plan.json"
    elevator_path = args.output_dir / f"elevator_articulation.{args.elevator_format}"
    wrapper_path = args.output_dir / "scene_with_elevators.usda"
    owned_outputs = (
        [plan_path]
        if args.plan_only
        else [
            plan_path,
            elevator_path,
            wrapper_path,
        ]
    )
    if not args.overwrite:
        existing = [path for path in owned_outputs if path.exists()]
        if existing:
            raise FileExistsError(
                "refusing to overwrite existing output(s): "
                + ", ".join(str(path) for path in existing)
            )
    if args.plan_only:
        write_usd_plan(plan, plan_path)
        return plan_path, None, None
    if args.building_usd is None:
        raise USDAuthoringError("--building-usd is required unless --plan-only is used")
    if not args.building_usd.is_file():
        raise FileNotFoundError(f"building USD does not exist: {args.building_usd}")
    if args.building_usd.suffix.lower() not in {".usd", ".usda", ".usdc"}:
        raise USDAuthoringError(
            f"building input is not a USD file: {args.building_usd}"
        )
    if args.building_usd.resolve() in {
        plan_path.resolve(),
        elevator_path.resolve(),
        wrapper_path.resolve(),
    }:
        raise USDAuthoringError("tool outputs must not overwrite the building USD")

    author_elevator_usd(plan, elevator_path, overwrite=args.overwrite)
    write_wrapper_usda(
        args.building_usd,
        elevator_path,
        wrapper_path,
        overwrite=args.overwrite,
        meters_per_unit=plan.meters_per_unit,
        up_axis=plan.up_axis,
    )
    write_usd_plan(plan, plan_path)
    return plan_path, elevator_path, wrapper_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    try:
        plan_path, elevator_path, wrapper_path = run(args)
    except (
        ManifestValidationError,
        USDAuthoringError,
        USDDependencyError,
        FileExistsError,
        FileNotFoundError,
        OSError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"plan={plan_path}")
    if elevator_path is not None:
        print(f"elevator_usd={elevator_path}")
    if wrapper_path is not None:
        print(f"wrapper_usda={wrapper_path}")
    print(f"dof_count={sum(1 for _ in _iter_plan_joints(plan_path))}")
    return 0


def _iter_plan_joints(plan_path: Path):
    """Yield joints from a written plan without importing USD or bpy."""

    import json

    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    for elevator in payload["elevators"]:
        yield from elevator["joints"]


if __name__ == "__main__":
    raise SystemExit(main())
