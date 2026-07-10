"""Plan and author post-export USD elevator articulations.

The planning layer has no OpenUSD dependency and is suitable for unit tests or
``--plan-only`` workflows.  OpenUSD modules are imported only when an elevator
stage is actually authored, because the normal Infinigen Blender environment
does not necessarily provide ``pxr``.
"""

from __future__ import annotations

import importlib
import json
import math
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from infinigen.core.sim.elevator_manifest import (
    DriveConfig,
    ElevatorConfig,
    ElevatorManifest,
    validate_manifest,
)

Vec3 = tuple[float, float, float]
Color3 = tuple[float, float, float]
_USD_SUFFIXES = {".usd", ".usda", ".usdc"}
_TOKEN_CLEANUP = re.compile(r"[^A-Za-z0-9_]+")


class USDDependencyError(RuntimeError):
    """Raised when USD authoring is requested without the pxr bindings."""


class USDAuthoringError(RuntimeError):
    """Raised for invalid USD output or composition requests."""


@dataclass(frozen=True)
class BoxPlan:
    """A visual box and matching simple collision proxy under one rigid link."""

    name: str
    dimensions: Vec3
    translation: Vec3
    color: Color3

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "dimensions": list(self.dimensions),
            "translation": list(self.translation),
            "color": list(self.color),
        }


@dataclass(frozen=True)
class RigidLinkPlan:
    """A sibling rigid-body link in an elevator articulation."""

    name: str
    path: str
    translation: Vec3
    mass_kg: float
    boxes: tuple[BoxPlan, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "translation": list(self.translation),
            "mass_kg": self.mass_kg,
            "boxes": [box.to_dict() for box in self.boxes],
        }


@dataclass(frozen=True)
class PrismaticJointPlan:
    """A powered, one-DOF linear joint with named controller targets."""

    name: str
    path: str
    body0: str
    body1: str
    axis: str
    lower_limit: float
    upper_limit: float
    local_pos0: Vec3
    local_pos1: Vec3
    drive: DriveConfig
    targets: tuple[tuple[str, float], ...]
    initial_target: float = 0.0
    joint_type: str = "prismatic"
    drive_type: str = "linear"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "joint_type": self.joint_type,
            "drive_type": self.drive_type,
            "body0": self.body0,
            "body1": self.body1,
            "axis": self.axis,
            "lower_limit": self.lower_limit,
            "upper_limit": self.upper_limit,
            "local_pos0": list(self.local_pos0),
            "local_pos1": list(self.local_pos1),
            "drive": self.drive.to_dict(),
            "targets": dict(self.targets),
            "initial_target": self.initial_target,
        }


@dataclass(frozen=True)
class ElevatorArticulationPlan:
    """Complete link/joint plan for one independently controlled elevator."""

    elevator_id: str
    root_path: str
    origin_xy: tuple[float, float]
    yaw_degrees: float
    base_link_path: str
    links: tuple[RigidLinkPlan, ...]
    joints: tuple[PrismaticJointPlan, ...]
    stop_targets: tuple[tuple[str, float], ...]

    @property
    def dof_count(self) -> int:
        return len(self.joints)

    def to_dict(self) -> dict[str, Any]:
        return {
            "elevator_id": self.elevator_id,
            "root_path": self.root_path,
            "origin_xy": list(self.origin_xy),
            "yaw_degrees": self.yaw_degrees,
            "base_link_path": self.base_link_path,
            "dof_count": self.dof_count,
            "stop_targets": dict(self.stop_targets),
            "links": [link.to_dict() for link in self.links],
            "joints": [joint.to_dict() for joint in self.joints],
        }


@dataclass(frozen=True)
class ElevatorUSDPlan:
    """A dependency-free plan for every elevator in one USD layer."""

    meters_per_unit: float
    up_axis: str
    elevators: tuple[ElevatorArticulationPlan, ...]
    world_path: str = "/World"
    systems_path: str = "/World/ElevatorSystems"

    @property
    def dof_count(self) -> int:
        return sum(elevator.dof_count for elevator in self.elevators)

    def to_dict(self) -> dict[str, Any]:
        return {
            "meters_per_unit": self.meters_per_unit,
            "up_axis": self.up_axis,
            "world_path": self.world_path,
            "systems_path": self.systems_path,
            "dof_count": self.dof_count,
            "elevators": [elevator.to_dict() for elevator in self.elevators],
        }


def _floor_token(index: int, floor_id: str) -> str:
    token = _TOKEN_CLEANUP.sub("_", floor_id).strip("_") or "floor"
    if token[0].isdigit():
        token = f"f_{token}"
    return f"Stop_{index:02d}_{token}"


def _door_joint(
    *,
    root: str,
    name: str,
    body0: str,
    body1: str,
    local_pos0: Vec3,
    direction: str,
    drive: DriveConfig,
    travel: float,
) -> PrismaticJointPlan:
    if direction == "left":
        lower, upper, open_target = -travel, 0.0, -travel
    elif direction == "right":
        lower, upper, open_target = 0.0, travel, travel
    else:
        raise ValueError(f"unsupported door direction {direction!r}")
    return PrismaticJointPlan(
        name=name,
        path=f"{root}/Joints/{name}",
        body0=body0,
        body1=body1,
        axis="X",
        lower_limit=lower,
        upper_limit=upper,
        local_pos0=local_pos0,
        local_pos1=(0.0, 0.0, 0.0),
        drive=drive,
        targets=(("closed", 0.0), ("open", open_target)),
    )


def _plan_one_elevator(config: ElevatorConfig) -> ElevatorArticulationPlan:
    root = f"/World/ElevatorSystems/{config.elevator_id}"
    links_root = f"{root}/Links"
    base_path = f"{links_root}/Base"
    cabin_path = f"{links_root}/Cabin"
    ordered_stops = config.ordered_stops
    minimum_stop_z = ordered_stops[0].stop_z
    maximum_stop_z = ordered_stops[-1].stop_z
    stop_targets = tuple(
        (stop.floor_id, stop.stop_z - minimum_stop_z) for stop in ordered_stops
    )

    cabin_width, cabin_depth, cabin_height = config.cabin.inner_size
    wall = config.cabin.wall_thickness
    floor_thickness = config.cabin.floor_thickness
    outer_width = cabin_width + 2 * wall
    outer_depth = cabin_depth + 2 * wall
    cabin_color = (0.42, 0.46, 0.52)
    door_color = (0.22, 0.26, 0.31)
    cabin_boxes = (
        BoxPlan(
            "Floor",
            (outer_width, outer_depth, floor_thickness),
            (0.0, 0.0, -floor_thickness / 2),
            cabin_color,
        ),
        BoxPlan(
            "Ceiling",
            (outer_width, outer_depth, wall),
            (0.0, 0.0, cabin_height + wall / 2),
            cabin_color,
        ),
        BoxPlan(
            "LeftWall",
            (wall, outer_depth, cabin_height),
            (-(cabin_width + wall) / 2, 0.0, cabin_height / 2),
            cabin_color,
        ),
        BoxPlan(
            "RightWall",
            (wall, outer_depth, cabin_height),
            ((cabin_width + wall) / 2, 0.0, cabin_height / 2),
            cabin_color,
        ),
        BoxPlan(
            "BackWall",
            (outer_width, wall, cabin_height),
            (0.0, (cabin_depth + wall) / 2, cabin_height / 2),
            cabin_color,
        ),
    )

    links: list[RigidLinkPlan] = [
        RigidLinkPlan(
            name="Base",
            path=base_path,
            translation=(0.0, 0.0, 0.0),
            mass_kg=1.0,
            boxes=(),
        ),
        RigidLinkPlan(
            name="Cabin",
            path=cabin_path,
            translation=(0.0, 0.0, minimum_stop_z),
            mass_kg=config.cabin.mass_kg,
            boxes=cabin_boxes,
        ),
    ]
    joints: list[PrismaticJointPlan] = [
        PrismaticJointPlan(
            name="CabinLift",
            path=f"{root}/Joints/CabinLift",
            body0=base_path,
            body1=cabin_path,
            axis="Z",
            lower_limit=0.0,
            upper_limit=maximum_stop_z - minimum_stop_z,
            local_pos0=(0.0, 0.0, minimum_stop_z),
            local_pos1=(0.0, 0.0, 0.0),
            drive=config.lift_drive,
            targets=tuple((f"floor:{key}", value) for key, value in stop_targets),
        )
    ]

    door = config.cabin.door
    cabin_door_y = -(cabin_depth + wall) / 2 - door.thickness / 2
    door_center_z = door.height / 2
    for direction, sign in (("left", -1.0), ("right", 1.0)):
        side = direction.title()
        name = f"CabinDoor{side}"
        link_path = f"{links_root}/{name}"
        translation = (
            sign * door.width / 4,
            cabin_door_y,
            minimum_stop_z + door_center_z,
        )
        links.append(
            RigidLinkPlan(
                name=name,
                path=link_path,
                translation=translation,
                mass_kg=door.leaf_mass_kg,
                boxes=(
                    BoxPlan(
                        "Leaf",
                        (door.leaf_width, door.thickness, door.height),
                        (0.0, 0.0, 0.0),
                        door_color,
                    ),
                ),
            )
        )
        joints.append(
            _door_joint(
                root=root,
                name=name,
                body0=cabin_path,
                body1=link_path,
                local_pos0=(translation[0], translation[1], door_center_z),
                direction=direction,
                drive=config.door_drive,
                travel=door.travel,
            )
        )

    landing_door_y = cabin_door_y - door.thickness - door.landing_gap
    for stop_index, stop in enumerate(ordered_stops):
        stop_token = _floor_token(stop_index, stop.floor_id)
        for direction, sign in (("left", -1.0), ("right", 1.0)):
            side = direction.title()
            name = f"LandingDoor_{stop_token}_{side}"
            link_path = f"{links_root}/{name}"
            translation = (
                sign * door.width / 4,
                landing_door_y,
                stop.stop_z + door_center_z,
            )
            links.append(
                RigidLinkPlan(
                    name=name,
                    path=link_path,
                    translation=translation,
                    mass_kg=door.leaf_mass_kg,
                    boxes=(
                        BoxPlan(
                            "Leaf",
                            (door.leaf_width, door.thickness, door.height),
                            (0.0, 0.0, 0.0),
                            door_color,
                        ),
                    ),
                )
            )
            joints.append(
                _door_joint(
                    root=root,
                    name=name,
                    body0=base_path,
                    body1=link_path,
                    local_pos0=translation,
                    direction=direction,
                    drive=config.door_drive,
                    travel=door.travel,
                )
            )

    return ElevatorArticulationPlan(
        elevator_id=config.elevator_id,
        root_path=root,
        origin_xy=config.origin_xy,
        yaw_degrees=config.yaw_degrees,
        base_link_path=base_path,
        links=tuple(links),
        joints=tuple(joints),
        stop_targets=stop_targets,
    )


def build_usd_plan(manifest: ElevatorManifest) -> ElevatorUSDPlan:
    """Build a deterministic, pxr-free articulation plan from a manifest."""

    if not isinstance(manifest, ElevatorManifest):
        raise TypeError("manifest must be an ElevatorManifest")
    manifest = validate_manifest(manifest)
    return ElevatorUSDPlan(
        meters_per_unit=manifest.meters_per_unit,
        up_axis=manifest.up_axis,
        elevators=tuple(_plan_one_elevator(config) for config in manifest.elevators),
    )


def dumps_usd_plan(plan: ElevatorUSDPlan) -> str:
    """Serialize an articulation plan for inspection or build provenance."""

    return json.dumps(plan.to_dict(), indent=2, sort_keys=True) + "\n"


def write_usd_plan(plan: ElevatorUSDPlan, path: str | Path) -> Path:
    """Atomically write a dependency-free articulation plan as JSON."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(dumps_usd_plan(plan))
    temporary.replace(path)
    return path


def load_pxr_modules() -> dict[str, Any]:
    """Load OpenUSD lazily and return the modules used by the authoring path."""

    modules: dict[str, Any] = {}
    try:
        for name in ("Gf", "Sdf", "Usd", "UsdGeom", "UsdPhysics"):
            modules[name] = importlib.import_module(f"pxr.{name}")
    except (ImportError, ModuleNotFoundError) as exc:
        raise USDDependencyError(
            "OpenUSD Python bindings are required to author the elevator stage, "
            "but 'pxr' could not be imported. Run this command from an Isaac "
            "Sim/Omniverse Python environment or install the Infinigen 'sim' "
            "extra (pip install -e '.[sim]'). The --plan-only mode does not "
            "require pxr."
        ) from exc
    return modules


def _set_box_xform(
    schema: Any,
    translation: Vec3,
    dimensions: Vec3,
    Gf: Any,
    UsdGeom: Any,
) -> None:
    xformable = UsdGeom.Xformable(schema.GetPrim())
    xformable.AddTranslateOp().Set(Gf.Vec3d(*translation))
    xformable.AddScaleOp().Set(Gf.Vec3f(*dimensions))


def _define_box_pair(
    stage: Any,
    link: RigidLinkPlan,
    box: BoxPlan,
    modules: dict[str, Any],
) -> None:
    Gf = modules["Gf"]
    UsdGeom = modules["UsdGeom"]
    UsdPhysics = modules["UsdPhysics"]

    visual_scope_path = f"{link.path}/Visuals"
    collision_scope_path = f"{link.path}/Collisions"
    UsdGeom.Scope.Define(stage, visual_scope_path)
    collision_scope = UsdGeom.Scope.Define(stage, collision_scope_path)
    collision_scope.CreateVisibilityAttr().Set(UsdGeom.Tokens.invisible)

    visual = UsdGeom.Cube.Define(stage, f"{visual_scope_path}/{box.name}")
    visual.CreateSizeAttr().Set(1.0)
    _set_box_xform(visual, box.translation, box.dimensions, Gf, UsdGeom)
    color = UsdGeom.Gprim(visual.GetPrim()).CreateDisplayColorPrimvar(
        UsdGeom.Tokens.constant
    )
    color.Set([Gf.Vec3f(*box.color)])

    collision = UsdGeom.Cube.Define(stage, f"{collision_scope_path}/{box.name}")
    collision.CreateSizeAttr().Set(1.0)
    _set_box_xform(collision, box.translation, box.dimensions, Gf, UsdGeom)
    collision_prim = collision.GetPrim()
    collision_api = UsdPhysics.CollisionAPI.Apply(collision_prim)
    collision_api.CreateCollisionEnabledAttr().Set(True)


def _filter_body_pair(
    stage: Any, body0: str, body1: str, Sdf: Any, UsdPhysics: Any
) -> None:
    for source, target in ((body0, body1), (body1, body0)):
        prim = stage.GetPrimAtPath(source)
        UsdPhysics.FilteredPairsAPI.Apply(prim)
        relation = prim.CreateRelationship("physics:filteredPairs")
        relation.AddTarget(Sdf.Path(target))


def _define_prismatic_joint(
    stage: Any, joint_plan: PrismaticJointPlan, modules: dict[str, Any]
) -> None:
    Gf = modules["Gf"]
    Sdf = modules["Sdf"]
    UsdPhysics = modules["UsdPhysics"]
    joint = UsdPhysics.PrismaticJoint.Define(stage, joint_plan.path)
    joint.CreateBody0Rel().SetTargets([Sdf.Path(joint_plan.body0)])
    joint.CreateBody1Rel().SetTargets([Sdf.Path(joint_plan.body1)])
    joint.CreateAxisAttr().Set(joint_plan.axis)
    joint.CreateLowerLimitAttr().Set(joint_plan.lower_limit)
    joint.CreateUpperLimitAttr().Set(joint_plan.upper_limit)
    identity = Gf.Quatf(1.0, 0.0, 0.0, 0.0)
    joint.CreateLocalPos0Attr().Set(Gf.Vec3f(*joint_plan.local_pos0))
    joint.CreateLocalPos1Attr().Set(Gf.Vec3f(*joint_plan.local_pos1))
    joint.CreateLocalRot0Attr().Set(identity)
    joint.CreateLocalRot1Attr().Set(identity)

    # Prismatic drives are linear.  Do not copy the current generic exporter,
    # which applies the "angular" drive instance to every joint type.
    drive = UsdPhysics.DriveAPI.Apply(joint.GetPrim(), "linear")
    drive.CreateTypeAttr().Set("force")
    drive.CreateTargetPositionAttr().Set(joint_plan.initial_target)
    drive.CreateTargetVelocityAttr().Set(0.0)
    drive.CreateStiffnessAttr().Set(joint_plan.drive.stiffness)
    drive.CreateDampingAttr().Set(joint_plan.drive.damping)
    drive.CreateMaxForceAttr().Set(joint_plan.drive.max_force)
    _filter_body_pair(
        stage, joint_plan.body0, joint_plan.body1, Sdf=Sdf, UsdPhysics=UsdPhysics
    )


def _define_one_articulation(
    stage: Any, plan: ElevatorArticulationPlan, modules: dict[str, Any]
) -> None:
    Gf = modules["Gf"]
    Sdf = modules["Sdf"]
    UsdGeom = modules["UsdGeom"]
    UsdPhysics = modules["UsdPhysics"]

    root = UsdGeom.Xform.Define(stage, plan.root_path)
    root.AddTranslateOp().Set(Gf.Vec3d(plan.origin_xy[0], plan.origin_xy[1], 0.0))
    root.AddRotateZOp().Set(plan.yaw_degrees)
    UsdPhysics.ArticulationRootAPI.Apply(root.GetPrim())
    UsdGeom.Scope.Define(stage, f"{plan.root_path}/Links")
    UsdGeom.Scope.Define(stage, f"{plan.root_path}/Joints")

    for link_plan in plan.links:
        link = UsdGeom.Xform.Define(stage, link_plan.path)
        link.AddTranslateOp().Set(Gf.Vec3d(*link_plan.translation))
        rigid_api = UsdPhysics.RigidBodyAPI.Apply(link.GetPrim())
        rigid_api.CreateRigidBodyEnabledAttr().Set(True)
        mass_api = UsdPhysics.MassAPI.Apply(link.GetPrim())
        mass_api.CreateMassAttr().Set(link_plan.mass_kg)
        for box in link_plan.boxes:
            _define_box_pair(stage, link_plan, box, modules)

    fixed = UsdPhysics.FixedJoint.Define(stage, f"{plan.root_path}/Joints/RootFixed")
    fixed.CreateBody1Rel().SetTargets([Sdf.Path(plan.base_link_path)])
    world_anchor = (plan.origin_xy[0], plan.origin_xy[1], 0.0)
    fixed.CreateLocalPos0Attr().Set(Gf.Vec3f(*world_anchor))
    fixed.CreateLocalPos1Attr().Set(Gf.Vec3f(0.0, 0.0, 0.0))
    half_yaw = math.radians(plan.yaw_degrees) / 2
    fixed.CreateLocalRot0Attr().Set(
        Gf.Quatf(math.cos(half_yaw), 0.0, 0.0, math.sin(half_yaw))
    )
    fixed.CreateLocalRot1Attr().Set(Gf.Quatf(1.0, 0.0, 0.0, 0.0))

    for joint_plan in plan.joints:
        _define_prismatic_joint(stage, joint_plan, modules)


def author_elevator_usd(
    plan: ElevatorUSDPlan,
    output_path: str | Path,
    *,
    overwrite: bool = False,
) -> Path:
    """Author an independent elevator USD layer using lazy-loaded pxr APIs."""

    if not isinstance(plan, ElevatorUSDPlan):
        raise TypeError("plan must be an ElevatorUSDPlan")
    output_path = Path(output_path)
    if output_path.suffix.lower() not in _USD_SUFFIXES:
        raise USDAuthoringError(
            f"elevator USD output must end in .usd, .usda, or .usdc: {output_path}"
        )
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite existing USD: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    modules = load_pxr_modules()
    Usd = modules["Usd"]
    UsdGeom = modules["UsdGeom"]
    UsdPhysics = modules["UsdPhysics"]
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, plan.meters_per_unit)
    UsdPhysics.SetStageKilogramsPerUnit(stage, 1.0)
    world = UsdGeom.Xform.Define(stage, plan.world_path)
    stage.SetDefaultPrim(world.GetPrim())
    UsdGeom.Scope.Define(stage, plan.systems_path)
    for elevator in plan.elevators:
        _define_one_articulation(stage, elevator, modules)
    if not stage.GetRootLayer().Export(str(output_path)):
        raise USDAuthoringError(
            f"OpenUSD failed to export elevator stage {output_path}"
        )
    return output_path


def _asset_path_for_layer(target: Path, layer_dir: Path) -> str:
    relative = os.path.relpath(target.resolve(), start=layer_dir.resolve())
    result = Path(relative).as_posix()
    if "@" in result or "\n" in result or "\r" in result:
        raise USDAuthoringError(
            f"USD asset path contains unsupported delimiter characters: {result!r}"
        )
    return result


def wrapper_usda_text(
    building_usd: str | Path,
    elevator_usd: str | Path,
    wrapper_path: str | Path,
    *,
    meters_per_unit: float = 1.0,
    up_axis: str = "Z",
) -> str:
    """Return a small root layer that sublayers static building and elevators."""

    wrapper_path = Path(wrapper_path)
    building_usd = Path(building_usd)
    elevator_usd = Path(elevator_usd)
    if not math.isfinite(meters_per_unit) or meters_per_unit <= 0:
        raise USDAuthoringError("wrapper meters_per_unit must be a positive number")
    if up_axis != "Z":
        raise USDAuthoringError("wrapper up_axis must be 'Z'")
    building_ref = _asset_path_for_layer(building_usd, wrapper_path.parent)
    elevator_ref = _asset_path_for_layer(elevator_usd, wrapper_path.parent)
    return (
        "#usda 1.0\n"
        "(\n"
        '    defaultPrim = "World"\n'
        "    kilogramsPerUnit = 1\n"
        f"    metersPerUnit = {meters_per_unit:.17g}\n"
        f'    upAxis = "{up_axis}"\n'
        "    subLayers = [\n"
        f"        @{building_ref}@,\n"
        f"        @{elevator_ref}@\n"
        "    ]\n"
        ")\n"
    )


def write_wrapper_usda(
    building_usd: str | Path,
    elevator_usd: str | Path,
    wrapper_path: str | Path,
    *,
    overwrite: bool = False,
    require_inputs: bool = True,
    meters_per_unit: float = 1.0,
    up_axis: str = "Z",
) -> Path:
    """Write a non-destructive wrapper around static building and elevator USD."""

    building_usd = Path(building_usd)
    elevator_usd = Path(elevator_usd)
    wrapper_path = Path(wrapper_path)
    if wrapper_path.suffix.lower() != ".usda":
        raise USDAuthoringError("wrapper output must use the text .usda format")
    if require_inputs:
        for label, path in (("building", building_usd), ("elevator", elevator_usd)):
            if not path.is_file():
                raise FileNotFoundError(f"{label} USD does not exist: {path}")
            if path.suffix.lower() not in _USD_SUFFIXES:
                raise USDAuthoringError(f"{label} input is not a USD file: {path}")
    if wrapper_path.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite existing wrapper: {wrapper_path}")
    if wrapper_path.resolve() in {building_usd.resolve(), elevator_usd.resolve()}:
        raise USDAuthoringError("wrapper output must not overwrite an input layer")

    wrapper_path.parent.mkdir(parents=True, exist_ok=True)
    text = wrapper_usda_text(
        building_usd,
        elevator_usd,
        wrapper_path,
        meters_per_unit=meters_per_unit,
        up_axis=up_axis,
    )
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=wrapper_path.parent,
        prefix=f".{wrapper_path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(text)
    temporary.replace(wrapper_path)
    return wrapper_path
