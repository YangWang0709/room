# Copyright (C) 2026, Princeton University.
# This source code is licensed under the BSD 3-Clause license found in the
# LICENSE file in the root directory of this source tree.

"""Indoor-scene integration for generated elevator cores and moving assets."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import bpy
import numpy as np

from infinigen.assets.objects.elements.elevators import (
    ElevatorBuildMode,
    ElevatorSpec,
    ElevatorTiming,
    build_elevator_asset,
)
from infinigen.assets.utils.mesh import prepare_for_boolean
from infinigen.assets.utils.object import new_cube
from infinigen.core import tagging
from infinigen.core import tags as t
from infinigen.core.constraints.example_solver.geometry import parse_scene
from infinigen.core.constraints.example_solver.state_def import ObjectState, State
from infinigen.core.sim.elevator_manifest import (
    CabinConfig,
    DoorConfig,
    ElevatorConfig,
    ElevatorManifest,
    ElevatorStop,
    ShaftConfig,
    write_manifest,
)
from infinigen.core.util import blender as butil
from infinigen.core.util.math import int_hash

from .base import room_level

_SIDE_TO_YAW = {"-y": 0.0, "+x": math.pi / 2, "+y": math.pi, "-x": -math.pi / 2}


@dataclass(frozen=True)
class ElevatorSceneResult:
    assets: tuple
    manifest: ElevatorManifest | None
    manifest_path: Path | None


def _instance_index(name: str) -> int:
    suffix = name.rsplit("/", 1)[1].split(".", 1)[0]
    return int(suffix)


def _served_indices(constants) -> tuple[int, ...]:
    configured = constants.elevator_served_levels
    return (
        tuple(range(constants.n_stories)) if configured is None else tuple(configured)
    )


def _room_states(state: State, semantic: t.Semantics):
    return {
        name: obj_state
        for name, obj_state in state.objs.items()
        if semantic in obj_state.tags
    }


def _shaft_polygon(state: State, elevator_index: int):
    registry = getattr(state, "vertical_cores", None)
    if registry is not None:
        core_id = f"elevator_{elevator_index}"
        try:
            return registry[core_id].polygon
        except KeyError:
            pass

    rooms = [
        obj_state.polygon
        for name, obj_state in _room_states(state, t.Semantics.ElevatorRoom).items()
        if _instance_index(name) == elevator_index
    ]
    if not rooms:
        raise ValueError(f"Missing ElevatorRoom polygons for elevator {elevator_index}")
    reference = rooms[0]
    for polygon in rooms[1:]:
        union_area = reference.union(polygon).area
        iou = reference.intersection(polygon).area / union_area
        if iou < 0.98:
            raise ValueError(
                f"ElevatorRoom alignment for elevator {elevator_index} is too low: "
                f"IoU={iou:.6f}"
            )
    return reference


def _door_side(state: State, elevator_index: int, shaft_polygon) -> str:
    registry = getattr(state, "vertical_cores", None)
    if registry is not None:
        try:
            return registry[f"elevator_{elevator_index}"].door_side
        except KeyError:
            pass

    deltas = []
    shaft_center = np.asarray(shaft_polygon.centroid.coords[0])
    for name, obj_state in _room_states(state, t.Semantics.ElevatorLobby).items():
        if _instance_index(name) != elevator_index:
            continue
        deltas.append(np.asarray(obj_state.polygon.centroid.coords[0]) - shaft_center)
    if not deltas:
        raise ValueError(f"Missing ElevatorLobby for elevator {elevator_index}")
    dx, dy = np.mean(deltas, axis=0)
    if abs(dx) > abs(dy):
        return "+x" if dx > 0 else "-x"
    return "+y" if dy > 0 else "-y"


def install_elevator_clearance_proxies(state: State, constants) -> tuple[str, ...]:
    """Reserve shaft and landing space before ordinary furniture solving."""

    if not constants.elevator_enabled or constants.n_stories <= 1:
        return ()

    collection = butil.get_collection("placeholders:elevator_clearance")
    collection.hide_render = True
    created = []

    for elevator_index in range(constants.n_elevators):
        shaft = _shaft_polygon(state, elevator_index)
        x0, y0, x1, y1 = shaft.bounds
        levels = constants.building_levels
        z_min = levels[0].elevation
        top = levels[-1]
        z_max = top.elevation + top.height
        proxy = new_cube()
        proxy.name = f"elevator-clearance-shaft_{elevator_index}"
        proxy.dimensions = (
            max(x1 - x0 - 2 * constants.elevator_wall_thickness, 0.1),
            max(y1 - y0 - 2 * constants.elevator_wall_thickness, 0.1),
            z_max - z_min,
        )
        proxy.location = ((x0 + x1) / 2, (y0 + y1) / 2, (z_min + z_max) / 2)
        butil.apply_transform(proxy, scale=True)
        butil.put_in_collection(proxy, collection)
        proxy.hide_render = True
        key = proxy.name
        state.objs[key] = ObjectState(
            obj=proxy,
            tags={t.Semantics.ElevatorClearance, t.Semantics.NoChildren},
        )
        parse_scene.add_to_scene(state.trimesh_scene, proxy, preprocess=True)
        created.append(key)

    for name, obj_state in list(state.objs.items()):
        if t.Semantics.ElevatorLandingDoor not in obj_state.tags:
            continue
        lobby_targets = [
            state.objs[relation.target_name]
            for relation in obj_state.relations
            if relation.target_name in state.objs
            and t.Semantics.ElevatorLobby in state.objs[relation.target_name].tags
        ]
        if not lobby_targets:
            continue
        door_xy = np.asarray(obj_state.obj.location[:2], dtype=float)
        lobby_xy = np.asarray(lobby_targets[0].polygon.centroid.coords[0])
        delta = lobby_xy - door_xy
        if abs(delta[0]) > abs(delta[1]):
            direction = np.array([np.sign(delta[0]), 0.0])
            dimensions = (
                constants.elevator_lobby_depth,
                constants.elevator_door_width + 2 * constants.elevator_core_clearance,
                constants.elevator_door_height,
            )
        else:
            direction = np.array([0.0, np.sign(delta[1])])
            dimensions = (
                constants.elevator_door_width + 2 * constants.elevator_core_clearance,
                constants.elevator_lobby_depth,
                constants.elevator_door_height,
            )
        proxy = new_cube()
        floor_index = int(obj_state.obj.get("floor_index", room_level(name)))
        elevator_id = str(obj_state.obj.get("elevator_id", "elevator_0"))
        proxy.name = f"elevator-clearance-landing_{floor_index}/{elevator_id}"
        proxy.dimensions = dimensions
        proxy.location = (
            door_xy[0] + direction[0] * constants.elevator_lobby_depth / 2,
            door_xy[1] + direction[1] * constants.elevator_lobby_depth / 2,
            obj_state.obj.location.z,
        )
        butil.apply_transform(proxy, scale=True)
        butil.put_in_collection(proxy, collection)
        proxy.hide_render = True
        key = proxy.name
        state.objs[key] = ObjectState(
            obj=proxy,
            tags={t.Semantics.ElevatorClearance, t.Semantics.NoChildren},
        )
        parse_scene.add_to_scene(state.trimesh_scene, proxy, preprocess=True)
        created.append(key)

    return tuple(created)


def open_elevator_room_shells(state: State, constants) -> None:
    """Cut the exact shaft void while retaining its walls, pit, and top cap.

    A random ``ElevatorRoom`` segment may be larger than the registered core
    placeholder.  Deleting its whole floor/ceiling faces would therefore turn
    usable room area into an oversized opening.  Instead, one building-height
    cutter follows the configured shaft footprint, inset by the dedicated
    shaft-wall thickness, and is applied to every aligned core room.
    """

    if not constants.elevator_enabled or constants.n_stories <= 1:
        return
    grouped: dict[int, list[tuple[int, bpy.types.Object]]] = {}
    for name, obj_state in _room_states(state, t.Semantics.ElevatorRoom).items():
        obj = obj_state.obj
        if obj is None:
            continue
        grouped.setdefault(_instance_index(name), []).append((room_level(name), obj))

    if len(grouped) != constants.n_elevators:
        raise ValueError(
            f"Expected {constants.n_elevators} elevator shaft groups, got {len(grouped)}"
        )
    for elevator_index, level_objects in grouped.items():
        level_objects.sort(key=lambda item: item[0])
        expected = list(range(constants.n_stories))
        actual = [level for level, _ in level_objects]
        if actual != expected:
            raise ValueError(
                f"Elevator {elevator_index} shaft levels must be {expected}, got {actual}"
            )
        shaft = _shaft_polygon(state, elevator_index)
        x0, y0, x1, y1 = shaft.bounds
        wall = constants.elevator_wall_thickness
        inner_width = x1 - x0 - 2 * wall
        inner_depth = y1 - y0 - 2 * wall
        if inner_width <= 0 or inner_depth <= 0:
            raise ValueError(
                f"Elevator {elevator_index} shaft footprint {shaft.bounds} is too "
                f"small for wall thickness {wall}"
            )

        levels = constants.building_levels
        bottom = levels[0].elevation
        top = levels[-1].elevation + levels[-1].height
        # The dedicated asset supplies the pit and top slabs.  Extend slightly
        # beyond the native room volumes so no support/ceiling face survives in
        # the car sweep, including at the first and last floors.
        cutter_margin = max(wall, 1e-3)
        void_bottom = bottom - cutter_margin
        void_top = top + cutter_margin
        void_height = void_top - void_bottom
        if void_height <= 0:
            raise ValueError("Elevator shaft has no positive interior height")

        cutter = new_cube()
        cutter.name = f"elevator-shaft-void-cutter_{elevator_index}"
        cutter.dimensions = (inner_width, inner_depth, void_height)
        cutter.location = (
            (x0 + x1) / 2,
            (y0 + y1) / 2,
            (void_bottom + void_top) / 2,
        )
        butil.apply_transform(cutter, scale=True)
        prepare_for_boolean(cutter)
        try:
            for _, obj in level_objects:
                prepare_for_boolean(obj)
                butil.modify_mesh(
                    obj,
                    "BOOLEAN",
                    object=cutter,
                    operation="DIFFERENCE",
                    use_self=True,
                    use_hole_tolerant=True,
                )
                prepare_for_boolean(obj)
                tagging.tag_object(obj)
        finally:
            butil.delete(cutter)


def _tag_asset_mesh(obj: bpy.types.Object) -> None:
    role = str(obj.get("elevator_role", ""))
    tagging.tag_object(obj, t.Subpart.Visible)
    tagging.tag_object(obj, t.Subpart.Interior)
    if any(token in role for token in ("floor", "threshold", "slab_bottom")):
        tagging.tag_object(obj, t.Subpart.SupportSurface)
    elif any(token in role for token in ("ceiling", "slab_top")):
        tagging.tag_object(obj, t.Subpart.Ceiling)
    else:
        tagging.tag_object(obj, t.Subpart.Wall)

    if role.startswith("landing_door"):
        for semantic in (
            t.Semantics.Door,
            t.Semantics.ElevatorDoor,
            t.Semantics.ElevatorLandingDoor,
        ):
            tagging.tag_object(obj, semantic)
    elif role.startswith("car_door"):
        for semantic in (
            t.Semantics.Door,
            t.Semantics.ElevatorDoor,
            t.Semantics.ElevatorCarDoor,
        ):
            tagging.tag_object(obj, semantic)
    elif role in {"car_control_panel", "landing_call_station"}:
        tagging.tag_object(obj, t.Semantics.ElevatorControlPanel)
    elif role.startswith("car_") or role in {"cabin"}:
        tagging.tag_object(obj, t.Semantics.ElevatorCar)
    else:
        tagging.tag_object(obj, t.Semantics.ElevatorShaft)


def _manifest_for_assets(assets, scene_seed: int, scene_id: str) -> ElevatorManifest:
    configs = []
    for index, asset in enumerate(assets):
        spec = asset.spec
        root = asset.root
        bpy.context.view_layer.update()
        origin = root.matrix_world.translation
        yaw = math.degrees(root.matrix_world.to_euler("XYZ").z)
        stops = tuple(
            ElevatorStop(str(level), root.location.z + stop_z)
            for level, stop_z in zip(spec.served_levels, spec.stop_z)
        )
        panel = spec.car_panel_thickness
        door = DoorConfig(
            width=spec.door_width,
            height=spec.door_height,
            thickness=spec.door_thickness,
            travel=spec.door_width / 2,
        )
        cabin = CabinConfig(
            inner_size=(
                spec.car_width - 2 * panel,
                spec.car_depth - 2 * panel,
                spec.car_height - panel,
            ),
            wall_thickness=panel,
            floor_thickness=panel,
            door=door,
        )
        configs.append(
            ElevatorConfig(
                elevator_id=f"elevator_{index}",
                origin_xy=(float(origin.x), float(origin.y)),
                yaw_degrees=yaw,
                shaft=ShaftConfig(
                    inner_size=(spec.shaft_width, spec.shaft_depth),
                    z_min=root.location.z + spec.shaft_bottom_z,
                    z_max=root.location.z + spec.shaft_top_z,
                ),
                cabin=cabin,
                served_floors=stops,
            )
        )
    manifest = ElevatorManifest(
        elevators=tuple(configs),
        scene_id=scene_id,
        seed=int(scene_seed),
    )
    return ElevatorManifest.from_dict(manifest.to_dict())


def build_scene_elevators(
    state: State,
    constants,
    *,
    output_folder: Path,
    scene_seed: int,
    mode: str = "static",
    initial_level: int | str | None = None,
    animation_route="all",
    animation_fps: float = 24.0,
    car_speed: float = 1.0,
    car_acceleration: float = 1.0,
    door_open_time: float = 0.8,
    door_close_time: float = 0.8,
    dwell_time: float = 1.5,
    static_doors_open: bool = False,
) -> ElevatorSceneResult:
    """Build all configured elevators and write their validated manifest."""

    if not constants.elevator_enabled or constants.n_stories <= 1:
        return ElevatorSceneResult((), None, None)

    mode = ElevatorBuildMode(mode)
    served_indices = _served_indices(constants)
    levels = constants.building_levels
    served_ids = tuple(levels.by_index(index).level_id for index in served_indices)
    # Native room support surfaces are inset by half the structural slab
    # thickness.  Cabin-floor Z and landing thresholds must use that finished
    # surface, not the lower shell datum stored in ``LevelSpec.elevation``.
    stop_z = tuple(
        levels.by_index(index).elevation + constants.wall_thickness / 2
        for index in served_indices
    )
    building_bottom_z = levels[0].elevation
    building_top_z = levels[-1].elevation + levels[-1].height
    if initial_level is None:
        initial_id = (
            served_ids[0]
            if mode == ElevatorBuildMode.ANIMATED
            else served_ids[
                int_hash(("elevator-initial-level", int(scene_seed))) % len(served_ids)
            ]
        )
    elif isinstance(initial_level, int):
        initial_id = levels.by_index(initial_level).level_id
    else:
        initial_id = str(initial_level)
    if initial_id not in served_ids:
        raise ValueError(
            f"Elevator initial level {initial_id!r} is not served: {served_ids}"
        )

    if animation_route in (None, "all"):
        route = tuple(level for level in served_ids if level != initial_id)
    else:
        route = tuple(
            levels.by_index(level).level_id if isinstance(level, int) else str(level)
            for level in animation_route
        )
    if any(level not in served_ids for level in route):
        raise ValueError(f"Animation route {route} leaves served levels {served_ids}")

    timing = ElevatorTiming(
        travel_speed=float(car_speed),
        travel_acceleration=float(car_acceleration),
        door_open_time=float(door_open_time),
        door_close_time=float(door_close_time),
        door_dwell_time=float(dwell_time),
    )
    assets = []
    for elevator_index in range(constants.n_elevators):
        shaft = _shaft_polygon(state, elevator_index)
        x0, y0, x1, y1 = shaft.bounds
        side = _door_side(state, elevator_index, shaft)
        if side in {"-x", "+x"}:
            outer_width, outer_depth = y1 - y0, x1 - x0
        else:
            outer_width, outer_depth = x1 - x0, y1 - y0
        shaft_width = outer_width - 2 * constants.elevator_wall_thickness
        shaft_depth = outer_depth - 2 * constants.elevator_wall_thickness
        if shaft_width <= 0 or shaft_depth <= 0:
            raise ValueError(
                f"Elevator {elevator_index} core is too small for configured shaft walls"
            )
        spec = ElevatorSpec(
            stop_z=stop_z,
            served_levels=served_ids,
            shaft_width=shaft_width,
            shaft_depth=shaft_depth,
            shaft_wall_thickness=constants.elevator_wall_thickness,
            pit_depth=stop_z[0] - building_bottom_z + 0.25,
            overhead=max(
                0.1,
                building_top_z - stop_z[-1] - constants.elevator_car_height,
            ),
            car_width=constants.elevator_car_width,
            car_depth=constants.elevator_car_depth,
            car_height=constants.elevator_car_height,
            door_width=constants.elevator_door_width,
            door_height=constants.elevator_door_height,
        )
        seed = int_hash(("elevator", int(scene_seed), elevator_index))
        asset = build_elevator_asset(
            spec,
            seed=seed,
            name=f"ElevatorSystem_{elevator_index:02d}",
            mode=mode,
            initial_level=initial_id,
            static_doors_open=static_doors_open,
            animation_requests=route if mode == ElevatorBuildMode.ANIMATED else (),
            timing=timing,
            fps=animation_fps,
        )
        asset.root.location = ((x0 + x1) / 2, (y0 + y1) / 2, 0.0)
        asset.root.rotation_euler.z = _SIDE_TO_YAW[side]
        asset.root["elevator_id"] = f"elevator_{elevator_index}"
        asset.root["elevator_door_side"] = side
        for obj in asset.all_objects():
            if obj.type == "MESH":
                _tag_asset_mesh(obj)
        assets.append(asset)

    manifest = _manifest_for_assets(assets, scene_seed, output_folder.name)
    manifest_path = write_manifest(manifest, output_folder / "elevator_manifest.json")
    registry = getattr(state, "vertical_cores", None)
    if registry is not None:
        with (output_folder / "vertical_core_manifest.json").open("w") as file:
            json.dump(
                {"schema_version": 1, "vertical_cores": registry.to_manifest_dict()},
                file,
                indent=2,
                sort_keys=True,
            )
    return ElevatorSceneResult(tuple(assets), manifest, manifest_path)
