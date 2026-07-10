import hashlib
import json
from dataclasses import replace

import pytest

import infinigen.core.sim.elevator_runtime as runtime_module
from infinigen.core.sim.elevator_manifest import ElevatorManifest, write_manifest
from infinigen.core.sim.elevator_runtime import (
    ElevatorInterlockError,
    ElevatorRuntimePlanError,
    ElevatorStageError,
    build_runtime_command,
    load_runtime_plan,
    write_runtime_command,
)
from infinigen.core.sim.elevator_usd import (
    author_elevator_usd,
    build_usd_plan,
    write_usd_plan,
)
from infinigen.tools.control_elevator_usd import main as control_tool_main

from test_elevator_manifest import manifest_payload


def make_plan():
    return build_usd_plan(ElevatorManifest.from_dict(manifest_payload()))


def test_closed_travel_snapshot_targets_floor_and_closes_every_door():
    command = build_runtime_command(
        make_plan(), elevator_id="Lift_A", floor_id="3", door_state="closed"
    )

    assert command.lift_target == pytest.approx(9.8)
    assert len(command.targets) == 11
    assert command.targets[0].role == "lift"
    assert command.targets[0].target_name == "floor:3"
    doors = command.targets[1:]
    assert all(target.target_name == "closed" for target in doors)
    assert all(target.target_position == pytest.approx(0.0) for target in doors)

    payload = command.to_dict()
    assert payload["operation"] == "move_with_doors_closed"
    assert payload["interlocks"]["all_doors_closed_for_motion"] is True
    assert payload["interlocks"]["all_non_target_landing_doors_closed"] is True
    assert payload["interlocks"]["open_landing_floors"] == []


def test_open_snapshot_opens_only_car_and_aligned_current_landing():
    command = build_runtime_command(
        make_plan(),
        elevator_id="Lift_A",
        floor_id="2",
        door_state="open",
        car_position=6.3505,
        alignment_tolerance=1e-3,
    )

    car_doors = [target for target in command.targets if target.role.startswith("car_")]
    landing_doors = [
        target for target in command.targets if target.role.startswith("landing_")
    ]
    assert len(car_doors) == 2
    assert {target.target_position for target in car_doors} == {-0.56, 0.56}
    assert all(target.target_name == "open" for target in car_doors)

    selected = [target for target in landing_doors if target.floor_id == "2"]
    other = [target for target in landing_doors if target.floor_id != "2"]
    assert len(selected) == 2
    assert {target.target_position for target in selected} == {-0.56, 0.56}
    assert all(target.target_name == "open" for target in selected)
    assert len(other) == 6
    assert all(target.target_name == "closed" for target in other)
    assert all(target.target_position == 0.0 for target in other)

    payload = command.to_dict()
    assert payload["operation"] == "open_at_aligned_floor"
    assert payload["interlocks"]["car_aligned_to_target"] is True
    assert payload["interlocks"]["all_non_target_landing_doors_closed"] is True
    assert payload["interlocks"]["open_landing_floors"] == ["2"]


@pytest.mark.parametrize(
    "car_position, message",
    [
        (None, "requires a measured car_position"),
        (3.05, "cannot open"),
        (float("nan"), "finite number"),
        (100.0, "outside CabinLift limits"),
    ],
)
def test_open_interlock_rejects_missing_misaligned_or_invalid_position(
    car_position, message
):
    with pytest.raises(ElevatorInterlockError, match=message):
        build_runtime_command(
            make_plan(),
            elevator_id="Lift_A",
            floor_id="2",
            door_state="open",
            car_position=car_position,
        )


def test_selection_floor_ids_and_incomplete_joint_contract_fail_closed():
    plan = make_plan()
    service = build_runtime_command(
        plan, elevator_id="ServiceLift", floor_id=2, door_state="closed"
    )
    assert service.floor_id == "2"
    assert service.lift_target == pytest.approx(6.35)

    with pytest.raises(ElevatorRuntimePlanError, match="was not found"):
        build_runtime_command(plan, elevator_id="missing", floor_id="2")
    with pytest.raises(ElevatorRuntimePlanError, match="is not served"):
        build_runtime_command(plan, elevator_id="ServiceLift", floor_id="1")

    lift = plan.elevators[0]
    incomplete_lift = replace(lift, joints=lift.joints[:-1])
    incomplete_plan = replace(plan, elevators=(incomplete_lift, *plan.elevators[1:]))
    with pytest.raises(ElevatorRuntimePlanError, match="incomplete door joints"):
        build_runtime_command(incomplete_plan, elevator_id="Lift_A", floor_id="G")


def test_manually_constructed_command_cannot_bypass_interlocks():
    command = build_runtime_command(
        make_plan(), elevator_id="Lift_A", floor_id="2", door_state="closed"
    )
    rogue_index = next(
        index
        for index, target in enumerate(command.targets)
        if target.role == "landing_door_left" and target.floor_id == "1"
    )
    rogue = replace(
        command.targets[rogue_index], target_name="open", target_position=-0.56
    )
    targets = list(command.targets)
    targets[rogue_index] = rogue

    with pytest.raises(ElevatorInterlockError, match="must close every"):
        replace(command, targets=tuple(targets))
    with pytest.raises(ElevatorInterlockError, match="requires measured"):
        replace(command, door_state="open", car_position=None)


def test_existing_plan_is_verified_exactly_against_manifest(tmp_path):
    manifest = ElevatorManifest.from_dict(manifest_payload())
    manifest_path = write_manifest(manifest, tmp_path / "elevator_manifest.json")
    plan_path = write_usd_plan(
        build_usd_plan(manifest), tmp_path / "elevator_plan.json"
    )

    assert load_runtime_plan(manifest_path, plan_path) == build_usd_plan(manifest)

    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    payload["elevators"][0]["joints"][0]["upper_limit"] += 1.0
    plan_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ElevatorRuntimePlanError, match="does not match"):
        load_runtime_plan(manifest_path, plan_path)


def test_cli_dry_run_is_json_and_never_loads_pxr(tmp_path, monkeypatch, capsys):
    manifest = ElevatorManifest.from_dict(manifest_payload())
    manifest_path = write_manifest(manifest, tmp_path / "elevator_manifest.json")
    plan_path = write_usd_plan(
        build_usd_plan(manifest), tmp_path / "elevator_plan.json"
    )

    def forbidden_pxr():
        raise AssertionError("dry-run imported pxr")

    monkeypatch.setattr(runtime_module, "load_pxr_modules", forbidden_pxr)
    result = control_tool_main(
        [
            "--manifest",
            str(manifest_path),
            "--plan",
            str(plan_path),
            "--elevator",
            "Lift_A",
            "--floor",
            "3",
            "--door-state",
            "closed",
            "--dry-run",
        ]
    )

    assert result == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "PASS"
    assert report["dry_run"] is True
    assert report["command"]["target_count"] == 11
    assert report["command"]["interlocks"]["all_doors_closed_for_motion"]


def test_cli_interlock_failure_is_json_and_distinct_nonzero_exit(tmp_path, capsys):
    manifest_path = write_manifest(
        ElevatorManifest.from_dict(manifest_payload()),
        tmp_path / "elevator_manifest.json",
    )

    result = control_tool_main(
        [
            "--manifest",
            str(manifest_path),
            "--elevator",
            "Lift_A",
            "--floor",
            "2",
            "--door-state",
            "open",
            "--car-position",
            "3.05",
            "--dry-run",
        ]
    )

    assert result == 3
    report = json.loads(capsys.readouterr().err)
    assert report["status"] == "FAIL"
    assert report["error_type"] == "interlock"


def test_write_api_requires_explicit_safe_mode_before_loading_pxr(
    tmp_path, monkeypatch
):
    input_path = tmp_path / "elevator.usda"
    input_path.touch()
    command = build_runtime_command(make_plan(), elevator_id="Lift_A", floor_id="G")

    def forbidden_pxr():
        raise AssertionError("path safety should run before pxr")

    monkeypatch.setattr(runtime_module, "load_pxr_modules", forbidden_pxr)
    with pytest.raises(ElevatorStageError, match="choose exactly one"):
        write_runtime_command(input_path, command)
    with pytest.raises(ElevatorStageError, match="must differ from input"):
        write_runtime_command(input_path, command, output_usd=input_path)

    existing = tmp_path / "existing.usda"
    existing.touch()
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        write_runtime_command(input_path, command, output_usd=existing)


def test_real_pxr_copy_and_in_place_modes_preserve_interlocks(tmp_path):
    Usd = pytest.importorskip("pxr.Usd", reason="OpenUSD pxr bindings are absent")
    UsdPhysics = pytest.importorskip("pxr.UsdPhysics")

    plan = make_plan()
    input_path = author_elevator_usd(plan, tmp_path / "elevator.usda")
    original_hash = hashlib.sha256(input_path.read_bytes()).hexdigest()
    opened = build_runtime_command(
        plan,
        elevator_id="Lift_A",
        floor_id="2",
        door_state="open",
        car_position=6.35,
    )
    incomplete = replace(opened, targets=opened.targets[:-2])
    preflight_stage = Usd.Stage.Open(str(input_path))
    with pytest.raises(ElevatorStageError, match="cover every prismatic joint"):
        runtime_module.apply_runtime_command(preflight_stage, incomplete)
    unchanged_car_door = UsdPhysics.DriveAPI.Get(
        preflight_stage.GetPrimAtPath(opened.targets[1].joint_path), "linear"
    ).GetTargetPositionAttr()
    assert unchanged_car_door.Get() == pytest.approx(0.0)

    output_path = write_runtime_command(
        input_path, opened, output_usd=tmp_path / "controlled.usda"
    )

    assert hashlib.sha256(input_path.read_bytes()).hexdigest() == original_hash
    source_stage = Usd.Stage.Open(str(input_path))
    output_stage = Usd.Stage.Open(str(output_path))
    assert source_stage and output_stage
    for target in opened.targets:
        source_prim = source_stage.GetPrimAtPath(target.joint_path)
        output_prim = output_stage.GetPrimAtPath(target.joint_path)
        source_value = (
            UsdPhysics.DriveAPI.Get(source_prim, "linear").GetTargetPositionAttr().Get()
        )
        output_value = (
            UsdPhysics.DriveAPI.Get(output_prim, "linear").GetTargetPositionAttr().Get()
        )
        assert source_value == pytest.approx(0.0)
        assert output_value == pytest.approx(target.target_position)

    closed = build_runtime_command(
        plan, elevator_id="Lift_A", floor_id="3", door_state="closed"
    )
    assert write_runtime_command(input_path, closed, in_place=True) == input_path
    saved_stage = Usd.Stage.Open(str(input_path))
    assert saved_stage
    for target in closed.targets:
        value = (
            UsdPhysics.DriveAPI.Get(
                saved_stage.GetPrimAtPath(target.joint_path), "linear"
            )
            .GetTargetPositionAttr()
            .Get()
        )
        assert value == pytest.approx(target.target_position)
