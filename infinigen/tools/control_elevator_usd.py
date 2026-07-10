"""Plan or author one interlocked elevator USD drive-target snapshot.

Examples
--------
Preview a travel command without importing OpenUSD::

    python -m infinigen.tools.control_elevator_usd \
      --manifest elevator_manifest.json --plan elevator_plan.json \
      --elevator elevator_0 --floor F3 --door-state closed --dry-run

Open doors only with measured lift-joint alignment evidence::

    python -m infinigen.tools.control_elevator_usd \
      --manifest elevator_manifest.json --plan elevator_plan.json \
      --usd elevator_articulation.usda --elevator elevator_0 --floor F3 \
      --door-state open --car-position 8.837846 --output controlled.usda

The command never overwrites its USD input unless ``--in-place`` is supplied
explicitly.  A generic pxr stage only stores drive targets; it does not step
physics or prove that an elevator completed the requested motion.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from infinigen.core.sim.elevator_manifest import ManifestValidationError
from infinigen.core.sim.elevator_runtime import (
    ElevatorInterlockError,
    ElevatorRuntimeError,
    build_runtime_command,
    load_runtime_plan,
    write_runtime_command,
)
from infinigen.core.sim.elevator_usd import USDDependencyError


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a complete, interlocked elevator drive-target snapshot and "
            "optionally author it into an offline USD stage."
        )
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--plan",
        type=Path,
        help="Optional elevator_plan.json to verify against the manifest",
    )
    parser.add_argument(
        "--usd",
        type=Path,
        help="Input elevator or composed USD; required for a write mode",
    )
    parser.add_argument("--elevator", required=True, help="Manifest elevator id")
    parser.add_argument("--floor", required=True, help="Served floor id")
    parser.add_argument("--door-state", choices=("closed", "open"), default="closed")
    parser.add_argument(
        "--car-position",
        type=float,
        help=(
            "Measured CabinLift joint position in stage units; mandatory when "
            "opening doors"
        ),
    )
    parser.add_argument("--alignment-tolerance", type=float, default=1e-3)

    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument(
        "--dry-run",
        action="store_true",
        help="Emit target JSON without importing pxr or opening a USD",
    )
    modes.add_argument(
        "--output",
        type=Path,
        help="Write a new flattened USD copy; an existing path is refused",
    )
    modes.add_argument(
        "--in-place",
        action="store_true",
        help="Explicitly write targets into the input USD root layer",
    )
    return parser


def run(args: argparse.Namespace) -> dict[str, Any]:
    plan = load_runtime_plan(args.manifest, args.plan)
    command = build_runtime_command(
        plan,
        elevator_id=args.elevator,
        floor_id=args.floor,
        door_state=args.door_state,
        car_position=args.car_position,
        alignment_tolerance=args.alignment_tolerance,
    )

    report: dict[str, Any] = {
        "status": "PASS",
        "manifest_path": str(args.manifest.resolve()),
        "plan_path": None if args.plan is None else str(args.plan.resolve()),
        "plan_verified": args.plan is not None,
        "dry_run": bool(args.dry_run),
        "input_usd": None if args.usd is None else str(args.usd.resolve()),
        "output_usd": None,
        "in_place": bool(args.in_place),
        "command": command.to_dict(),
    }
    if args.dry_run:
        return report
    if args.usd is None:
        raise ElevatorRuntimeError("--usd is required with --output or --in-place")

    written = write_runtime_command(
        args.usd,
        command,
        output_usd=args.output,
        in_place=args.in_place,
    )
    report["output_usd"] = str(written.resolve())
    report["applied_target_count"] = len(command.targets)
    return report


def _error_report(exc: Exception, error_type: str) -> dict[str, Any]:
    return {
        "status": "FAIL",
        "error_type": error_type,
        "error": str(exc),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    try:
        report = run(args)
    except ElevatorInterlockError as exc:
        print(
            json.dumps(_error_report(exc, "interlock"), indent=2, sort_keys=True),
            file=sys.stderr,
        )
        return 3
    except (
        ManifestValidationError,
        ElevatorRuntimeError,
        USDDependencyError,
        FileNotFoundError,
        OSError,
        TypeError,
        ValueError,
    ) as exc:
        print(
            json.dumps(_error_report(exc, "input_or_stage"), indent=2, sort_keys=True),
            file=sys.stderr,
        )
        return 2

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
