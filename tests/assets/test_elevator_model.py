# Copyright (C) 2026, Princeton University.
# This source code is licensed under the BSD 3-Clause license found in the
# LICENSE file in the root directory of this source tree.

"""Unit tests for the Blender-independent elevator controller."""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pytest

# Load the leaf module directly so these tests exercise the controller without
# importing the Blender-facing ``elements`` package initializers.
_MODEL_PATH = (
    Path(__file__).parents[2] / "infinigen/assets/objects/elements/elevators/model.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "_elevator_model_under_test", _MODEL_PATH
)
assert _SPEC is not None and _SPEC.loader is not None
elevator = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = elevator
_SPEC.loader.exec_module(elevator)


def _four_stop_spec():
    return elevator.ElevatorSpec(
        stop_z=(0.0, 3.05, 6.4, 10.0),
        served_levels=("G", "M", 2, "Roof"),
    )


def _fast_timing():
    return elevator.ElevatorTiming(
        travel_speed=5.0,
        leveling_time=0.1,
        door_open_time=0.2,
        door_dwell_time=0.15,
        door_close_time=0.2,
    )


def _run_until_idle(controller, dt=0.05, limit=2000):
    snapshots = [controller.snapshot()]
    for _ in range(limit):
        if controller.is_idle:
            return snapshots
        snapshots.append(controller.step(dt))
    raise AssertionError("controller failed to return to idle")


def _assert_door_interlocks(snapshot):
    open_landings = [
        (level, fraction)
        for level, fraction in snapshot.landing_door_fractions
        if fraction > 1e-9
    ]
    if snapshot.car_door_fraction > 1e-9:
        assert open_landings == [(snapshot.current_level, snapshot.car_door_fraction)]
    else:
        assert open_landings == []
    if snapshot.phase in {
        elevator.ElevatorPhase.MOVING,
        elevator.ElevatorPhase.LEVELING,
    }:
        assert snapshot.car_door_fraction == pytest.approx(0.0)
        assert snapshot.current_level is None


def test_spec_supports_nonuniform_stops_and_mixed_level_ids():
    spec = _four_stop_spec()

    assert spec.n_stops == 4
    assert spec.level_index("M") == 1
    assert spec.level_index(2) == 2
    assert spec.z_for_level("Roof") == pytest.approx(10.0)
    assert spec.shaft_bottom_z < spec.stop_z[0]
    assert spec.shaft_top_z > spec.stop_z[-1] + spec.car_height


@pytest.mark.parametrize(
    "kwargs",
    [
        {"stop_z": ()},
        {"stop_z": (0.0, 3.0, 3.0)},
        {"stop_z": (0.0, 2.4)},
        {"stop_z": (0.0, 3.0), "served_levels": ("G",)},
        {"stop_z": (0.0, 3.0), "served_levels": ("G", "G")},
        {"stop_z": (0.0, 3.0), "served_levels": (False, "1")},
    ],
)
def test_spec_rejects_ambiguous_or_unsafe_layouts(kwargs):
    with pytest.raises(elevator.ElevatorConfigurationError):
        elevator.ElevatorSpec(**kwargs)


def test_visual_variant_is_seeded_without_changing_geometry():
    spec = _four_stop_spec()
    a = elevator.sample_visual_variant(spec, seed=31415)
    b = elevator.sample_visual_variant(spec, seed=31415)
    c = elevator.sample_visual_variant(spec, seed=31416)

    assert a == b
    assert a != c
    assert len(a.landing_station_sides) == spec.n_stops
    assert set(a.landing_station_sides) <= {-1, 1}
    assert spec.stop_z == (0.0, 3.05, 6.4, 10.0)


def test_request_at_current_landing_opens_only_linked_doors():
    controller = elevator.ElevatorController(
        _four_stop_spec(), initial_level="G", timing=_fast_timing()
    )
    assert controller.request("G")

    opening = controller.step(0.1)
    assert opening.phase == elevator.ElevatorPhase.OPENING
    assert opening.current_level == "G"
    assert opening.car_z == pytest.approx(0.0)
    assert opening.car_door_fraction == pytest.approx(0.5)
    _assert_door_interlocks(opening)

    snapshots = _run_until_idle(controller)
    assert any(s.phase == elevator.ElevatorPhase.OPEN_DWELL for s in snapshots)
    assert snapshots[-1].current_level == "G"
    assert snapshots[-1].car_door_fraction == pytest.approx(0.0)


def test_motion_and_landing_doors_are_interlocked_for_far_trip():
    controller = elevator.ElevatorController(
        _four_stop_spec(), initial_level="G", timing=_fast_timing()
    )
    controller.request("Roof")
    first_motion = controller.step(0.1)

    assert first_motion.phase == elevator.ElevatorPhase.MOVING
    with pytest.raises(elevator.ElevatorInterlockError, match="moving/leveling"):
        controller.open_doors()

    snapshots = [first_motion, *_run_until_idle(controller)]
    for snapshot in snapshots:
        _assert_door_interlocks(snapshot)

    assert snapshots[-1].phase == elevator.ElevatorPhase.IDLE_CLOSED
    assert snapshots[-1].current_level == "Roof"
    assert snapshots[-1].car_z == pytest.approx(10.0)


def test_queued_stops_are_served_in_request_order():
    controller = elevator.ElevatorController(
        _four_stop_spec(), initial_level="G", timing=_fast_timing(), seed=22
    )
    controller.request("Roof")
    controller.request("M")
    controller.request(2)
    assert not controller.request("M")

    snapshots = _run_until_idle(controller)
    arrivals = []
    for previous, current in zip(snapshots, snapshots[1:]):
        if (
            current.phase == elevator.ElevatorPhase.OPEN_DWELL
            and previous.phase != elevator.ElevatorPhase.OPEN_DWELL
        ):
            arrivals.append(current.current_level)

    assert arrivals == ["Roof", "M", 2]
    assert snapshots[-1].current_level == 2
    assert snapshots[-1].pending_levels == ()


def test_animation_plan_is_deterministic_and_interlock_safe():
    kwargs = dict(
        spec=_four_stop_spec(),
        requests=("Roof", "M", "G"),
        initial_level="G",
        timing=_fast_timing(),
        sample_period=0.05,
        seed=1234,
    )
    first = elevator.build_animation_plan(**kwargs)
    second = elevator.build_animation_plan(**kwargs)

    assert first == second
    assert first.duration > 0
    assert math.isclose(first.snapshots[0].time_s, 0.0)
    assert first.snapshots[-1].phase == elevator.ElevatorPhase.IDLE_CLOSED
    assert first.snapshots[-1].current_level == "G"
    for snapshot in first.snapshots:
        _assert_door_interlocks(snapshot)


def test_fault_freezes_motion_and_requires_safe_reset():
    controller = elevator.ElevatorController(
        _four_stop_spec(), initial_level="G", timing=_fast_timing()
    )
    controller.request("Roof")
    moving = controller.step(0.2)
    controller.trigger_fault("safety chain open")
    faulted = controller.step(1.0)

    assert faulted.phase == elevator.ElevatorPhase.FAULT
    assert faulted.car_z == pytest.approx(moving.car_z)
    assert faulted.velocity == pytest.approx(0.0)
    with pytest.raises(elevator.ElevatorInterlockError, match="aligned"):
        controller.reset_fault()


def test_motion_profile_respects_acceleration_and_speed_limits():
    timing = elevator.ElevatorTiming(
        travel_speed=2.0,
        travel_acceleration=0.5,
        leveling_time=0.0,
        door_open_time=0.1,
        door_dwell_time=0.0,
        door_close_time=0.1,
    )
    controller = elevator.ElevatorController(
        _four_stop_spec(), initial_level="G", timing=timing
    )
    controller.move_to_floor("Roof")
    first = controller.step(0.5)
    second = controller.step(0.5)

    assert first.velocity == pytest.approx(0.25)
    assert second.velocity == pytest.approx(0.5)
    assert abs(second.velocity) <= timing.travel_speed
    assert second.car_z > first.car_z > 0


def test_public_scene_control_interface_preserves_interlocks():
    spec = elevator.ElevatorSpec.evenly_spaced(4, served_levels=("G", "L1", "L2", "L3"))
    controller = elevator.ElevatorController(spec)

    controller.set_current_floor("L2")
    assert controller.current_level == "L2"
    assert controller.car_z == spec.z_for_level("L2")
    controller.set_car_door_open_fraction(0.5)
    snapshot = controller.snapshot()
    assert snapshot.car_door_fraction == 0.5
    assert snapshot.landing_door_fraction("L2") == 0.5
    assert snapshot.landing_door_fraction("G") == 0.0

    with pytest.raises(elevator.ElevatorInterlockError):
        controller.set_landing_door_open_fraction("L1", 0.5)

    controller.set_landing_door_open_fraction("L2", 0.0)
    assert controller.move_to_floor("L3")
