# Copyright (C) 2026, Princeton University.
# This source code is licensed under the BSD 3-Clause license found in the
# LICENSE file in the root directory of this source tree.

"""Blender smoke tests for the isolated elevator asset builder."""

from __future__ import annotations

import bpy
import bmesh
import pytest
import shapely

from infinigen.assets.objects.elements.elevators.blender import (
    ElevatorFactory,
    build_elevator_asset,
)
from infinigen.assets.objects.elements.elevators.model import (
    ElevatorBuildMode,
    ElevatorPhase,
    ElevatorSpec,
    ElevatorTiming,
)
from infinigen.assets.utils.object import new_cube
from infinigen.core.constraints.constraint_language.constants import RoomConstants
from infinigen.core.constraints.example_solver.room.elevator import (
    build_scene_elevators,
    open_elevator_room_shells,
)
from infinigen.core.constraints.example_solver.room.vertical_core import (
    VerticalCorePlacement,
    VerticalCoreRegistry,
    VerticalCoreSpec,
)
from infinigen.core.constraints.example_solver.state_def import ObjectState, State
from infinigen.core.tags import Semantics
from infinigen.core.util import blender as butil


def _roles(asset):
    return [obj.get("elevator_role") for obj in asset.all_objects()]


def _location_curve(obj, index):
    if obj.animation_data is None or obj.animation_data.action is None:
        return None
    return next(
        (
            curve
            for curve in obj.animation_data.action.fcurves
            if curve.data_path == "location" and curve.array_index == index
        ),
        None,
    )


def test_static_four_stop_asset_has_stable_hierarchy_and_linked_open_doors():
    spec = ElevatorSpec(
        stop_z=(0.0, 3.05, 6.4, 10.0),
        served_levels=("G", "M", 2, "Roof deck"),
    )
    asset = build_elevator_asset(
        spec,
        seed=2026,
        name="FourStopLift",
        mode=ElevatorBuildMode.STATIC,
        initial_level=2,
        static_doors_open=True,
    )
    bpy.context.view_layer.update()

    assert asset.root["elevator_role"] == "system"
    assert asset.root["elevator_schema_version"] == 1
    assert asset.root["elevator_seed"] == "2026"
    assert asset.root["elevator_coordinate_space"] == "root_local"
    assert asset.root["elevator_stop_reference"] == "finished_car_floor"
    assert tuple(asset.root["elevator_stop_z"]) == pytest.approx(spec.stop_z)
    assert asset.root["elevator_phase"] == ElevatorPhase.OPEN_DWELL.value
    assert asset.root["elevator_mode"] == ElevatorBuildMode.STATIC.value
    assert asset.car_root.parent == asset.root
    assert asset.shaft_root.parent == asset.root
    assert asset.cabin_root.parent == asset.car_root
    assert asset.car_door_root.parent == asset.car_root
    assert len(asset.landing_roots) == 4
    assert len(asset.landing_door_panels) == 4
    assert asset.object_by_path("Car") == asset.car_root
    assert asset.object_by_path("Shaft.Landings") == asset.landings_root

    roles = _roles(asset)
    assert roles.count("landing") == 4
    assert roles.count("landing_door_panel_left") == 4
    assert roles.count("landing_door_panel_right") == 4
    assert roles.count("landing_call_station") == 4

    assert asset.car_root.location.z == pytest.approx(spec.z_for_level(2))
    car_floor = next(
        obj for obj in asset.all_objects() if obj.get("elevator_role") == "car_floor"
    )
    assert car_floor.location.z + car_floor.dimensions.z / 2 == pytest.approx(0.0)
    for level, stop_z in zip(spec.served_levels, spec.stop_z):
        landing = asset.landing_roots[level]
        assert landing.parent == asset.landings_root
        assert landing.matrix_world.translation.z == pytest.approx(stop_z)
        left, right = asset.landing_door_panels[level]
        if level == 2:
            assert left.location.x == pytest.approx(-3 * spec.door_width / 4)
            assert right.location.x == pytest.approx(3 * spec.door_width / 4)
        else:
            assert left.location.x == pytest.approx(-spec.door_width / 4)
            assert right.location.x == pytest.approx(spec.door_width / 4)

    assert all(obj.animation_data is None for obj in asset.all_objects())


def test_asset_factory_placement_keeps_descendant_name_prefix_and_paths():
    spec = ElevatorSpec.evenly_spaced(
        4, floor_height=3.0, served_levels=("G", "1", "2", "3")
    )
    factory = ElevatorFactory(factory_seed=17, spec=spec)

    root = factory.spawn_asset(
        i=3,
        distance=1.0,
        loc=(4.0, -2.0, 0.0),
        rot=(0.0, 0.0, 0.25),
    )
    asset = factory.last_build

    assert asset is not None
    assert root == asset.root
    assert int(root["elevator_seed"]) > 2**31 - 1
    assert tuple(root.location) == pytest.approx((4.0, -2.0, 0.0))
    assert root.rotation_euler.z == pytest.approx(0.25)
    assert asset.object_by_path("Car") == asset.car_root
    assert asset.car_root.parent == root
    assert all(obj.name.startswith(root.name) for obj in asset.all_objects()[1:])


def test_animated_asset_keys_car_linked_doors_and_state_metadata():
    spec = ElevatorSpec(
        stop_z=(0.0, 2.8, 5.8),
        served_levels=("G", "1", "R"),
    )
    timing = ElevatorTiming(
        travel_speed=8.0,
        leveling_time=0.1,
        door_open_time=0.1,
        door_dwell_time=0.1,
        door_close_time=0.1,
    )
    asset = build_elevator_asset(
        spec,
        seed=91,
        name="AnimatedLift",
        mode=ElevatorBuildMode.ANIMATED,
        initial_level="G",
        animation_requests=("R", "G"),
        timing=timing,
        fps=10.0,
        frame_start=7,
    )

    assert asset.animation_plan is not None
    assert asset.animation_plan.snapshots[-1].current_level == "G"
    assert asset.animation_plan.snapshots[-1].phase == ElevatorPhase.IDLE_CLOSED
    assert asset.root["elevator_animation_frame_start"] == 7
    assert asset.root["elevator_animation_frame_end"] > 7
    assert _location_curve(asset.car_root, 2) is not None
    assert all(_location_curve(panel, 0) is not None for panel in asset.car_door_panels)
    assert all(
        _location_curve(panel, 0) is not None
        for panels in asset.landing_door_panels.values()
        for panel in panels
    )

    root_action = asset.root.animation_data.action
    root_paths = {curve.data_path for curve in root_action.fcurves}
    assert '["elevator_phase_code"]' in root_paths
    assert '["elevator_current_stop_index"]' in root_paths
    assert '["elevator_door_fraction"]' in root_paths
    assert all(
        keyframe.interpolation == "CONSTANT"
        for curve in root_action.fcurves
        for keyframe in curve.keyframe_points
    )

    car_z_curve = _location_curve(asset.car_root, 2)
    keyed_z = [point.co.y for point in car_z_curve.keyframe_points]
    assert min(keyed_z) == pytest.approx(spec.stop_z[0])
    assert max(keyed_z) == pytest.approx(spec.stop_z[-1])
    assert all(
        snapshot.car_door_fraction == pytest.approx(0.0)
        for snapshot in asset.animation_plan.snapshots
        if snapshot.phase in {ElevatorPhase.MOVING, ElevatorPhase.LEVELING}
    )


def _core_registry(n_stories, polygon):
    levels = tuple(range(n_stories))
    spec = VerticalCoreSpec(
        core_id="elevator_0",
        room_type=Semantics.ElevatorRoom,
        placeholder_tag=Semantics.ElevatorShaft,
        instance_index=0,
        width=polygon.bounds[2] - polygon.bounds[0],
        depth=polygon.bounds[3] - polygon.bounds[1],
        span_levels=levels,
        served_levels=levels,
        lobby_room_type=Semantics.ElevatorLobby,
        lobby_depth=1.0,
        door_width=1.0,
    )
    return VerticalCoreRegistry((VerticalCorePlacement(spec, polygon, "+x"),))


def _mesh_volume(obj):
    mesh = bmesh.new()
    try:
        mesh.from_mesh(obj.data)
        return abs(mesh.calc_volume())
    finally:
        mesh.free()


def test_scene_asset_uses_finished_floor_z_and_core_inner_dimensions(tmp_path):
    constants = RoomConstants(
        n_stories=4,
        elevator_enabled=True,
        fixed_contour=False,
    )
    core = shapely.box(0.0, 0.0, 2.5, 2.5)
    state = State()
    state.vertical_cores = _core_registry(constants.n_stories, core)

    result = build_scene_elevators(
        state,
        constants,
        output_folder=tmp_path,
        scene_seed=302,
    )
    asset = result.assets[0]

    assert asset.spec.stop_z == pytest.approx(
        tuple(
            level.elevation + constants.wall_thickness / 2
            for level in constants.building_levels
        )
    )
    assert asset.spec.shaft_width == pytest.approx(
        2.5 - 2 * constants.elevator_wall_thickness
    )
    assert asset.spec.shaft_depth == pytest.approx(
        2.5 - 2 * constants.elevator_wall_thickness
    )
    assert result.manifest.elevators[0].served_floors[0].stop_z == pytest.approx(
        constants.wall_thickness / 2
    )

    butil.delete(list(asset.all_objects()))


def test_shaft_boolean_preserves_oversized_random_room_area():
    constants = RoomConstants(
        n_stories=3,
        elevator_enabled=True,
        fixed_contour=False,
    )
    core = shapely.box(0.75, 0.75, 3.25, 3.25)
    state = State()
    state.vertical_cores = _core_registry(constants.n_stories, core)
    rooms = []
    for level in constants.building_levels:
        obj = new_cube()
        obj.name = f"elevator-room_{level.index}/0"
        obj.dimensions = (4.0, 4.0, level.height)
        obj.location = (2.0, 2.0, level.elevation + level.height / 2)
        butil.apply_transform(obj, scale=True)
        rooms.append(obj)
        state.objs[obj.name] = ObjectState(
            obj=obj,
            polygon=shapely.box(0.0, 0.0, 4.0, 4.0),
            tags={Semantics.ElevatorRoom},
        )

    open_elevator_room_shells(state, constants)

    inner_side = 2.5 - 2 * constants.elevator_wall_thickness
    for room, level in zip(rooms, constants.building_levels):
        expected = (16.0 - inner_side**2) * level.height
        assert _mesh_volume(room) == pytest.approx(expected, rel=2e-4, abs=2e-4)

    butil.delete(rooms)
