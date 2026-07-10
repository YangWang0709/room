"""Interlocked runtime targets for authored elevator USD articulations.

The planning API is intentionally independent of OpenUSD.  It converts the
validated elevator manifest/plan contract into a complete drive-target
snapshot, including closed targets for every non-selected landing door.
OpenUSD is imported lazily only when a caller applies that snapshot to a
stage or writes an offline USD result.

``car_position`` is the measured CabinLift joint position, relative to the
lowest served stop.  Opening doors requires this value and rejects the
command unless it is aligned with the requested floor.  A USD drive target is
not treated as proof of physical alignment.
"""

from __future__ import annotations

import json
import math
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from infinigen.core.sim.elevator_manifest import read_manifest
from infinigen.core.sim.elevator_usd import (
    ElevatorArticulationPlan,
    ElevatorUSDPlan,
    PrismaticJointPlan,
    build_usd_plan,
    load_pxr_modules,
)

RUNTIME_SCHEMA_VERSION = 1
DRIVE_TARGET_ATTRIBUTE = "drive:linear:physics:targetPosition"
VALID_DOOR_STATES = {"closed", "open"}
_USD_SUFFIXES = {".usd", ".usda", ".usdc"}
_LANDING_JOINT = re.compile(
    r"^LandingDoor_Stop_(?P<index>[0-9]+)_.+_(?P<side>Left|Right)$"
)


class ElevatorRuntimeError(RuntimeError):
    """Base error for runtime command planning or USD application."""


class ElevatorRuntimePlanError(ElevatorRuntimeError):
    """Raised when a selected elevator/plan does not match the USD contract."""


class ElevatorInterlockError(ElevatorRuntimeError):
    """Raised when a requested drive state violates a safety interlock."""


class ElevatorStageError(ElevatorRuntimeError):
    """Raised when a stage is missing the expected joints or cannot be written."""


@dataclass(frozen=True)
class LinearDriveTarget:
    """One validated linear-drive target in a complete elevator snapshot."""

    joint_name: str
    joint_path: str
    role: str
    axis: str
    body0: str
    body1: str
    target_name: str
    target_position: float
    lower_limit: float
    upper_limit: float
    floor_id: str | None = None

    @property
    def attribute_path(self) -> str:
        return f"{self.joint_path}.{DRIVE_TARGET_ATTRIBUTE}"

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "joint_name": self.joint_name,
            "joint_path": self.joint_path,
            "attribute_path": self.attribute_path,
            "drive_type": "linear",
            "role": self.role,
            "axis": self.axis,
            "body0": self.body0,
            "body1": self.body1,
            "target_name": self.target_name,
            "target_position": self.target_position,
            "lower_limit": self.lower_limit,
            "upper_limit": self.upper_limit,
        }
        if self.floor_id is not None:
            result["floor_id"] = self.floor_id
        return result


@dataclass(frozen=True)
class ElevatorRuntimeCommand:
    """An immutable, interlocked target snapshot for one elevator."""

    elevator_id: str
    floor_id: str
    door_state: str
    lift_target: float
    car_position: float | None
    alignment_tolerance: float
    meters_per_unit: float
    up_axis: str
    targets: tuple[LinearDriveTarget, ...]
    schema_version: int = RUNTIME_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RUNTIME_SCHEMA_VERSION:
            raise ElevatorRuntimePlanError(
                f"unsupported runtime schema_version={self.schema_version}"
            )
        if not isinstance(self.elevator_id, str) or not self.elevator_id:
            raise ElevatorRuntimePlanError("command elevator_id must not be empty")
        if not isinstance(self.floor_id, str) or not self.floor_id:
            raise ElevatorRuntimePlanError("command floor_id must not be empty")
        if self.door_state not in VALID_DOOR_STATES:
            raise ElevatorRuntimePlanError(
                f"command door_state must be one of {sorted(VALID_DOOR_STATES)}"
            )
        for name, value in (
            ("lift_target", self.lift_target),
            ("alignment_tolerance", self.alignment_tolerance),
            ("meters_per_unit", self.meters_per_unit),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ElevatorRuntimePlanError(f"command {name} must be finite")
            if not math.isfinite(float(value)):
                raise ElevatorRuntimePlanError(f"command {name} must be finite")
        if self.alignment_tolerance < 0:
            raise ElevatorInterlockError(
                "command alignment_tolerance must be non-negative"
            )
        if self.meters_per_unit <= 0 or self.up_axis != "Z":
            raise ElevatorRuntimePlanError(
                "command requires positive meters_per_unit and Z up_axis"
            )
        if self.car_position is not None and (
            isinstance(self.car_position, bool)
            or not isinstance(self.car_position, (int, float))
            or not math.isfinite(float(self.car_position))
        ):
            raise ElevatorInterlockError("command car_position must be finite")
        if not self.targets:
            raise ElevatorRuntimePlanError("command must contain drive targets")

        paths = [target.joint_path for target in self.targets]
        if len(paths) != len(set(paths)):
            raise ElevatorRuntimePlanError("command contains duplicate joint paths")
        allowed_roles = {
            "lift",
            "car_door_left",
            "car_door_right",
            "landing_door_left",
            "landing_door_right",
        }
        for target in self.targets:
            values = (
                target.target_position,
                target.lower_limit,
                target.upper_limit,
            )
            if target.role not in allowed_roles:
                raise ElevatorRuntimePlanError(
                    f"command has unsupported target role {target.role!r}"
                )
            if not all(math.isfinite(float(value)) for value in values):
                raise ElevatorRuntimePlanError(
                    f"command target {target.joint_path} contains non-finite values"
                )
            if target.lower_limit > target.upper_limit or not (
                target.lower_limit - 1e-9
                <= target.target_position
                <= target.upper_limit + 1e-9
            ):
                raise ElevatorRuntimePlanError(
                    f"command target {target.joint_path} is outside its limits"
                )

        lift_targets = [target for target in self.targets if target.role == "lift"]
        if len(lift_targets) != 1:
            raise ElevatorRuntimePlanError(
                "command must contain exactly one lift target"
            )
        lift = lift_targets[0]
        if (
            lift.axis != "Z"
            or lift.floor_id != self.floor_id
            or lift.target_name != f"floor:{self.floor_id}"
            or not math.isclose(lift.target_position, self.lift_target, abs_tol=1e-9)
        ):
            raise ElevatorRuntimePlanError(
                "command lift target does not match its requested floor"
            )

        door_targets = [target for target in self.targets if target.role != "lift"]
        for role in ("car_door_left", "car_door_right"):
            if sum(target.role == role for target in door_targets) != 1:
                raise ElevatorRuntimePlanError(
                    f"command must contain exactly one {role} target"
                )
        landing_pairs: dict[str, list[str]] = {}
        for target in door_targets:
            if not target.role.startswith("landing_door"):
                continue
            if target.floor_id is None:
                raise ElevatorRuntimePlanError(
                    f"landing target {target.joint_path} has no floor_id"
                )
            landing_pairs.setdefault(target.floor_id, []).append(target.role)
        expected_pair = {"landing_door_left", "landing_door_right"}
        incomplete = {
            floor: sorted(expected_pair.symmetric_difference(roles))
            for floor, roles in landing_pairs.items()
            if len(roles) != 2 or set(roles) != expected_pair
        }
        if incomplete or self.floor_id not in landing_pairs:
            raise ElevatorRuntimePlanError(
                f"command has incomplete landing-door pairs: {incomplete}"
            )

        if self.door_state == "closed":
            if any(
                target.target_name != "closed"
                or not math.isclose(target.target_position, 0.0, abs_tol=1e-9)
                for target in door_targets
            ):
                raise ElevatorInterlockError(
                    "a motion command must close every car and landing door"
                )
            return

        if self.car_position is None:
            raise ElevatorInterlockError(
                "an open command requires measured car_position"
            )
        if abs(self.car_position - self.lift_target) > self.alignment_tolerance:
            raise ElevatorInterlockError(
                "an open command requires the car to be aligned with the floor"
            )
        car_doors = [
            target for target in door_targets if target.role.startswith("car_door")
        ]
        if any(target.target_name != "open" for target in car_doors):
            raise ElevatorInterlockError("an open command must open both car doors")
        for target in door_targets:
            if not target.role.startswith("landing_door"):
                continue
            expected_state = "open" if target.floor_id == self.floor_id else "closed"
            if target.target_name != expected_state:
                raise ElevatorInterlockError(
                    "only the aligned floor's landing doors may open"
                )
            if expected_state == "closed" and not math.isclose(
                target.target_position, 0.0, abs_tol=1e-9
            ):
                raise ElevatorInterlockError(
                    "non-selected landing doors must have a zero closed target"
                )

    @property
    def alignment_error(self) -> float | None:
        if self.car_position is None:
            return None
        return abs(self.car_position - self.lift_target)

    @property
    def doors_open(self) -> bool:
        return self.door_state == "open"

    def to_dict(self) -> dict[str, Any]:
        door_targets = [target for target in self.targets if target.role != "lift"]
        open_landing_floors = sorted(
            {
                target.floor_id
                for target in door_targets
                if target.role.startswith("landing_door")
                and target.target_name == "open"
                and target.floor_id is not None
            }
        )
        all_non_target_landings_closed = all(
            target.target_name == "closed" or target.floor_id == self.floor_id
            for target in door_targets
            if target.role.startswith("landing_door")
        )
        return {
            "schema_version": self.schema_version,
            "elevator_id": self.elevator_id,
            "floor_id": self.floor_id,
            "operation": (
                "open_at_aligned_floor" if self.doors_open else "move_with_doors_closed"
            ),
            "door_state": self.door_state,
            "lift_target": self.lift_target,
            "car_position": self.car_position,
            "alignment_tolerance": self.alignment_tolerance,
            "alignment_error": self.alignment_error,
            "meters_per_unit": self.meters_per_unit,
            "up_axis": self.up_axis,
            "interlocks": {
                "alignment_required": self.doors_open,
                "car_aligned_to_target": (
                    self.alignment_error is not None
                    and self.alignment_error <= self.alignment_tolerance
                    if self.doors_open
                    else None
                ),
                "all_doors_closed_for_motion": all(
                    target.target_name == "closed" for target in door_targets
                ),
                "all_non_target_landing_doors_closed": (all_non_target_landings_closed),
                "open_landing_floors": open_landing_floors,
            },
            "target_count": len(self.targets),
            "targets": [target.to_dict() for target in self.targets],
        }


def load_runtime_plan(
    manifest_path: str | Path, plan_path: str | Path | None = None
) -> ElevatorUSDPlan:
    """Read a manifest and optionally verify its previously written USD plan."""

    manifest = read_manifest(manifest_path)
    canonical = build_usd_plan(manifest)
    if plan_path is None:
        return canonical

    plan_path = Path(plan_path)
    try:
        payload = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ElevatorRuntimePlanError(
            f"could not read elevator USD plan {plan_path}: {exc}"
        ) from exc
    if payload != canonical.to_dict():
        raise ElevatorRuntimePlanError(
            f"elevator USD plan {plan_path} does not match the manifest-derived plan"
        )
    return canonical


def _select_elevator(
    plan: ElevatorUSDPlan, elevator_id: str
) -> ElevatorArticulationPlan:
    if not isinstance(plan, ElevatorUSDPlan):
        raise TypeError("plan must be an ElevatorUSDPlan")
    if not isinstance(elevator_id, str) or not elevator_id.strip():
        raise ElevatorRuntimePlanError("elevator_id must be a non-empty string")
    matches = [
        elevator for elevator in plan.elevators if elevator.elevator_id == elevator_id
    ]
    if len(matches) != 1:
        choices = sorted(elevator.elevator_id for elevator in plan.elevators)
        raise ElevatorRuntimePlanError(
            f"elevator {elevator_id!r} was not found; choices are {choices}"
        )
    return matches[0]


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ElevatorInterlockError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ElevatorInterlockError(f"{name} must be a finite number")
    return result


def _target(
    joint: PrismaticJointPlan,
    *,
    role: str,
    target_name: str,
    floor_id: str | None = None,
) -> LinearDriveTarget:
    named_targets = dict(joint.targets)
    if target_name not in named_targets:
        raise ElevatorRuntimePlanError(
            f"joint {joint.path} has no controller target {target_name!r}"
        )
    position = float(named_targets[target_name])
    if position < joint.lower_limit - 1e-9 or position > joint.upper_limit + 1e-9:
        raise ElevatorRuntimePlanError(
            f"joint {joint.path} target {target_name!r}={position} is outside "
            f"[{joint.lower_limit}, {joint.upper_limit}]"
        )
    return LinearDriveTarget(
        joint_name=joint.name,
        joint_path=joint.path,
        role=role,
        axis=joint.axis,
        body0=joint.body0,
        body1=joint.body1,
        target_name=target_name,
        target_position=position,
        lower_limit=joint.lower_limit,
        upper_limit=joint.upper_limit,
        floor_id=floor_id,
    )


def build_runtime_command(
    plan: ElevatorUSDPlan,
    *,
    elevator_id: str,
    floor_id: str | int,
    door_state: str = "closed",
    car_position: float | None = None,
    alignment_tolerance: float = 1e-3,
) -> ElevatorRuntimeCommand:
    """Build one complete drive snapshot and enforce door/lift interlocks.

    Closed commands always close both cabin doors and every landing door before
    targeting the lift.  Open commands require a measured ``car_position`` at
    the requested floor; only that floor's landing doors and the cabin doors
    receive open targets.
    """

    elevator = _select_elevator(plan, elevator_id)
    if isinstance(floor_id, bool) or not isinstance(floor_id, (str, int)):
        raise ElevatorRuntimePlanError("floor_id must be a string or integer")
    floor_id = str(floor_id).strip()
    if not floor_id:
        raise ElevatorRuntimePlanError("floor_id must not be empty")
    if door_state not in VALID_DOOR_STATES:
        raise ElevatorRuntimePlanError(
            f"door_state must be one of {sorted(VALID_DOOR_STATES)}, got {door_state!r}"
        )
    tolerance = _finite_number(alignment_tolerance, "alignment_tolerance")
    if tolerance < 0:
        raise ElevatorInterlockError("alignment_tolerance must be non-negative")

    stops = tuple(elevator.stop_targets)
    floor_ids = tuple(key for key, _ in stops)
    if floor_id not in floor_ids:
        raise ElevatorRuntimePlanError(
            f"floor {floor_id!r} is not served by {elevator_id!r}; "
            f"choices are {list(floor_ids)}"
        )
    floor_index = floor_ids.index(floor_id)

    lift_joints = [joint for joint in elevator.joints if joint.name == "CabinLift"]
    if len(lift_joints) != 1:
        raise ElevatorRuntimePlanError(
            f"{elevator_id!r} must contain exactly one CabinLift joint"
        )
    lift = lift_joints[0]
    if lift.axis != "Z" or lift.joint_type != "prismatic":
        raise ElevatorRuntimePlanError("CabinLift must be a Z prismatic joint")
    lift_target_name = f"floor:{floor_id}"
    lift_target = _target(
        lift, role="lift", target_name=lift_target_name, floor_id=floor_id
    )

    measured_position = (
        None if car_position is None else _finite_number(car_position, "car_position")
    )
    if measured_position is not None and not (
        lift.lower_limit - tolerance
        <= measured_position
        <= lift.upper_limit + tolerance
    ):
        raise ElevatorInterlockError(
            f"car_position={measured_position} is outside CabinLift limits "
            f"[{lift.lower_limit}, {lift.upper_limit}]"
        )
    if door_state == "open":
        if measured_position is None:
            raise ElevatorInterlockError(
                "opening doors requires a measured car_position; a drive target "
                "alone is not proof of alignment"
            )
        error = abs(measured_position - lift_target.target_position)
        if error > tolerance:
            raise ElevatorInterlockError(
                f"cannot open at floor {floor_id!r}: car_position={measured_position} "
                f"differs from target={lift_target.target_position} by {error}, "
                f"exceeding tolerance={tolerance}"
            )

    targets_by_path: dict[str, LinearDriveTarget] = {
        lift_target.joint_path: lift_target
    }
    cabin_roles = {
        "CabinDoorLeft": "car_door_left",
        "CabinDoorRight": "car_door_right",
    }
    landing_sides: dict[int, set[str]] = {index: set() for index in range(len(stops))}
    for joint in elevator.joints:
        if joint is lift:
            continue
        if joint.joint_type != "prismatic" or joint.drive_type != "linear":
            raise ElevatorRuntimePlanError(
                f"door joint {joint.path} must use a linear prismatic drive"
            )
        if joint.axis != "X":
            raise ElevatorRuntimePlanError(f"door joint {joint.path} must use X axis")

        if joint.name in cabin_roles:
            target_name = "open" if door_state == "open" else "closed"
            target = _target(
                joint, role=cabin_roles[joint.name], target_name=target_name
            )
        else:
            match = _LANDING_JOINT.fullmatch(joint.name)
            if match is None:
                raise ElevatorRuntimePlanError(
                    f"unsupported elevator joint naming contract: {joint.path}"
                )
            landing_index = int(match.group("index"))
            side = match.group("side").lower()
            if landing_index not in landing_sides:
                raise ElevatorRuntimePlanError(
                    f"landing joint {joint.path} refers to stop index {landing_index}, "
                    f"but {len(stops)} stops exist"
                )
            if side in landing_sides[landing_index]:
                raise ElevatorRuntimePlanError(
                    f"duplicate {side} landing-door joint for stop {landing_index}"
                )
            landing_sides[landing_index].add(side)
            landing_floor_id = stops[landing_index][0]
            target_name = (
                "open"
                if door_state == "open" and landing_index == floor_index
                else "closed"
            )
            target = _target(
                joint,
                role=f"landing_door_{side}",
                target_name=target_name,
                floor_id=landing_floor_id,
            )
        if target.joint_path in targets_by_path:
            raise ElevatorRuntimePlanError(
                f"duplicate runtime target path {target.joint_path}"
            )
        targets_by_path[target.joint_path] = target

    missing_cabin = sorted(
        set(cabin_roles).difference(
            target.joint_name for target in targets_by_path.values()
        )
    )
    incomplete_landings = {
        index: sorted({"left", "right"}.difference(sides))
        for index, sides in landing_sides.items()
        if sides != {"left", "right"}
    }
    if missing_cabin or incomplete_landings:
        raise ElevatorRuntimePlanError(
            f"incomplete door joints: missing cabin={missing_cabin}, "
            f"landing sides={incomplete_landings}"
        )
    if len(targets_by_path) != len(elevator.joints):
        raise ElevatorRuntimePlanError(
            f"expected one target for each of {len(elevator.joints)} joints, "
            f"built {len(targets_by_path)}"
        )

    ordered_targets = tuple(targets_by_path[joint.path] for joint in elevator.joints)
    return ElevatorRuntimeCommand(
        elevator_id=elevator_id,
        floor_id=floor_id,
        door_state=door_state,
        lift_target=lift_target.target_position,
        car_position=measured_position,
        alignment_tolerance=tolerance,
        meters_per_unit=plan.meters_per_unit,
        up_axis=plan.up_axis,
        targets=ordered_targets,
    )


def apply_runtime_command(
    stage: Any,
    command: ElevatorRuntimeCommand,
    *,
    usd_physics: Any | None = None,
    usd_geom: Any | None = None,
) -> int:
    """Preflight and apply every target to an already-open ``pxr.Usd.Stage``."""

    if not isinstance(command, ElevatorRuntimeCommand):
        raise TypeError("command must be an ElevatorRuntimeCommand")
    if stage is None or not hasattr(stage, "GetPrimAtPath"):
        raise TypeError("stage must be an open pxr.Usd.Stage")
    if usd_physics is None or usd_geom is None:
        modules = load_pxr_modules()
        usd_physics = usd_physics or modules["UsdPhysics"]
        usd_geom = usd_geom or modules["UsdGeom"]

    stage_up_axis = str(usd_geom.GetStageUpAxis(stage)).upper()
    stage_meters_per_unit = float(usd_geom.GetStageMetersPerUnit(stage))
    if stage_up_axis != command.up_axis or not math.isclose(
        stage_meters_per_unit, command.meters_per_unit, rel_tol=1e-9, abs_tol=1e-12
    ):
        raise ElevatorStageError(
            "stage units/up-axis do not match the runtime plan: "
            f"stage=({stage_meters_per_unit}, {stage_up_axis}), "
            f"plan=({command.meters_per_unit}, {command.up_axis})"
        )

    command_paths = {target.joint_path for target in command.targets}
    roots = {
        path.rsplit("/Joints/", 1)[0] for path in command_paths if "/Joints/" in path
    }
    if len(roots) != 1 or not hasattr(stage, "Traverse"):
        raise ElevatorStageError(
            "command targets must belong to one elevator root on a traversable stage"
        )
    root_prefix = f"{next(iter(roots))}/Joints/"
    root_path = next(iter(roots))
    root_prim = stage.GetPrimAtPath(root_path)
    if not root_prim or not root_prim.HasAPI(usd_physics.ArticulationRootAPI):
        raise ElevatorStageError(
            f"selected elevator root has no PhysicsArticulationRootAPI: {root_path}"
        )
    stage_joint_paths = {
        str(prim.GetPath())
        for prim in stage.Traverse()
        if str(prim.GetPath()).startswith(root_prefix)
        and usd_physics.PrismaticJoint(prim)
    }
    if stage_joint_paths != command_paths:
        raise ElevatorStageError(
            "command must cover every prismatic joint below the selected elevator; "
            f"missing={sorted(stage_joint_paths.difference(command_paths))}, "
            f"unexpected={sorted(command_paths.difference(stage_joint_paths))}"
        )

    prepared: list[tuple[LinearDriveTarget, Any]] = []
    for target in command.targets:
        prim = stage.GetPrimAtPath(target.joint_path)
        if not prim or not prim.IsValid():
            raise ElevatorStageError(f"stage has no joint prim at {target.joint_path}")
        joint = usd_physics.PrismaticJoint(prim)
        if not joint:
            raise ElevatorStageError(
                f"stage prim {target.joint_path} is not a PhysicsPrismaticJoint"
            )
        axis = str(joint.GetAxisAttr().Get())
        lower = joint.GetLowerLimitAttr().Get()
        upper = joint.GetUpperLimitAttr().Get()
        if lower is None or upper is None:
            raise ElevatorStageError(
                f"stage joint {target.joint_path} has no authored limits"
            )
        if axis != target.axis:
            raise ElevatorStageError(
                f"stage joint {target.joint_path} axis {axis!r} does not match "
                f"plan axis {target.axis!r}"
            )
        body0 = [str(path) for path in joint.GetBody0Rel().GetTargets()]
        body1 = [str(path) for path in joint.GetBody1Rel().GetTargets()]
        if body0 != [target.body0] or body1 != [target.body1]:
            raise ElevatorStageError(
                f"stage joint {target.joint_path} body bindings do not match plan: "
                f"body0={body0}, body1={body1}"
            )
        if not math.isclose(
            float(lower), target.lower_limit, rel_tol=1e-6, abs_tol=1e-5
        ) or not (
            math.isclose(float(upper), target.upper_limit, rel_tol=1e-6, abs_tol=1e-5)
        ):
            raise ElevatorStageError(
                f"stage joint {target.joint_path} limits [{lower}, {upper}] do not "
                f"match plan [{target.lower_limit}, {target.upper_limit}]"
            )
        drive = usd_physics.DriveAPI.Get(prim, "linear")
        if not drive:
            raise ElevatorStageError(
                f"stage joint {target.joint_path} has no linear PhysicsDriveAPI"
            )
        attribute = drive.GetTargetPositionAttr()
        if not attribute or not attribute.IsValid():
            raise ElevatorStageError(
                f"stage joint {target.joint_path} has no {DRIVE_TARGET_ATTRIBUTE}"
            )
        prepared.append((target, attribute))

    for target, attribute in prepared:
        if attribute.Set(target.target_position) is False:
            raise ElevatorStageError(
                f"could not set {target.attribute_path}={target.target_position}"
            )
    return len(prepared)


def write_runtime_command(
    input_usd: str | Path,
    command: ElevatorRuntimeCommand,
    *,
    output_usd: str | Path | None = None,
    in_place: bool = False,
) -> Path:
    """Apply a command to a USD file, explicitly in-place or as a flat copy.

    The default is deliberately non-writing: callers must choose exactly one
    of ``output_usd`` or ``in_place=True``.  Output copies are flattened by
    ``Usd.Stage.Export`` so wrapper sublayer paths remain valid regardless of
    the destination directory.
    """

    input_path = Path(input_usd)
    if not input_path.is_file():
        raise ElevatorStageError(f"input USD does not exist: {input_path}")
    if input_path.suffix.lower() not in _USD_SUFFIXES:
        raise ElevatorStageError(f"input is not a USD file: {input_path}")
    if in_place == (output_usd is not None):
        raise ElevatorStageError(
            "choose exactly one write mode: output_usd or in_place=True"
        )

    output_path = None if output_usd is None else Path(output_usd)
    if output_path is not None:
        if output_path.suffix.lower() not in _USD_SUFFIXES:
            raise ElevatorStageError(f"output is not a USD file: {output_path}")
        if output_path.resolve() == input_path.resolve():
            raise ElevatorStageError(
                "output USD must differ from input; use in_place=True explicitly"
            )
        if output_path.exists():
            raise FileExistsError(f"refusing to overwrite output USD: {output_path}")

    modules = load_pxr_modules()
    Usd = modules["Usd"]
    stage = Usd.Stage.Open(str(input_path.resolve()))
    if stage is None:
        raise ElevatorStageError(f"OpenUSD could not open stage: {input_path}")
    # A copy command must not even dirty the cached input root layer.  Author
    # its transient overrides into the session layer and flatten that composed
    # result.  Only the explicit in-place mode edits the file-backed root.
    stage.SetEditTarget(stage.GetRootLayer() if in_place else stage.GetSessionLayer())
    apply_runtime_command(
        stage,
        command,
        usd_physics=modules["UsdPhysics"],
        usd_geom=modules["UsdGeom"],
    )

    if in_place:
        if not stage.GetRootLayer().Save():
            raise ElevatorStageError(f"OpenUSD could not save stage: {input_path}")
        return input_path

    assert output_path is not None
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=output_path.parent,
        prefix=f".{output_path.stem}.",
        suffix=output_path.suffix,
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
    temporary.unlink()
    try:
        if not stage.Export(str(temporary), addSourceFileComment=False):
            raise ElevatorStageError(
                f"OpenUSD could not export controlled stage: {output_path}"
            )
        temporary.replace(output_path)
    finally:
        temporary.unlink(missing_ok=True)
    return output_path


__all__ = [
    "DRIVE_TARGET_ATTRIBUTE",
    "ElevatorInterlockError",
    "ElevatorRuntimeCommand",
    "ElevatorRuntimeError",
    "ElevatorRuntimePlanError",
    "ElevatorStageError",
    "LinearDriveTarget",
    "apply_runtime_command",
    "build_runtime_command",
    "load_runtime_plan",
    "write_runtime_command",
]
