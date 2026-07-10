import importlib
import json

import pytest

import infinigen.core.sim.elevator_usd as elevator_usd_module
from infinigen.core.sim.elevator_manifest import ElevatorManifest
from infinigen.core.sim.elevator_usd import (
    USDAuthoringError,
    USDDependencyError,
    build_usd_plan,
    load_pxr_modules,
    wrapper_usda_text,
    write_wrapper_usda,
)
from infinigen.tools.build_elevator_usd import main as elevator_tool_main

from test_elevator_manifest import manifest_payload


def test_plan_generates_linear_prismatic_dofs_for_only_served_floors():
    manifest = ElevatorManifest.from_dict(manifest_payload())
    plan = build_usd_plan(manifest)
    lift_a, service = plan.elevators

    assert lift_a.dof_count == 3 + 2 * 4
    assert service.dof_count == 3 + 2 * 2
    assert plan.dof_count == 18
    assert all(
        joint.joint_type == "prismatic"
        for elevator in plan.elevators
        for joint in elevator.joints
    )
    assert all(
        joint.drive_type == "linear"
        for elevator in plan.elevators
        for joint in elevator.joints
    )

    assert lift_a.joints[0].axis == "Z"
    assert dict(lift_a.stop_targets) == {
        "G": 0.0,
        "1": 3.05,
        "2": 6.35,
        "3": 9.8,
    }
    assert dict(lift_a.joints[0].targets) == {
        "floor:G": 0.0,
        "floor:1": 3.05,
        "floor:2": 6.35,
        "floor:3": 9.8,
    }
    assert sum("LandingDoor" in joint.name for joint in lift_a.joints) == 8
    assert sum("LandingDoor" in joint.name for joint in service.joints) == 4
    assert all(
        joint.axis == "X"
        for elevator in plan.elevators
        for joint in elevator.joints[1:]
    )


def test_nonuniform_absolute_stop_z_becomes_relative_drive_targets():
    payload = manifest_payload()
    stops = payload["elevators"][0]["served_floors"]
    stops[0]["stop_z"] = -0.1
    payload["elevators"][0]["shaft"]["z_min"] = -0.3
    manifest = ElevatorManifest.from_dict(payload)

    elevator = build_usd_plan(manifest).elevators[0]

    targets = dict(elevator.stop_targets)
    assert set(targets) == {"G", "1", "2", "3"}
    assert targets["G"] == pytest.approx(0.0)
    assert targets["1"] == pytest.approx(3.15)
    assert targets["2"] == pytest.approx(6.45)
    assert targets["3"] == pytest.approx(9.9)
    assert elevator.joints[0].upper_limit == pytest.approx(9.9)


def test_plan_uses_unique_sibling_link_and_joint_paths():
    plan = build_usd_plan(ElevatorManifest.from_dict(manifest_payload()))

    for elevator in plan.elevators:
        link_paths = [link.path for link in elevator.links]
        joint_paths = [joint.path for joint in elevator.joints]
        assert len(link_paths) == len(set(link_paths))
        assert len(joint_paths) == len(set(joint_paths))
        assert all(
            path.startswith(f"{elevator.root_path}/Links/") for path in link_paths
        )
        assert all(
            path.startswith(f"{elevator.root_path}/Joints/") for path in joint_paths
        )
        assert len(elevator.links) == 4 + 2 * len(elevator.stop_targets)


def test_wrapper_is_pxr_free_and_uses_relative_sublayers(tmp_path):
    export_dir = tmp_path / "static" / "export_scene.blend"
    export_dir.mkdir(parents=True)
    building = export_dir / "export_scene.usdc"
    building.touch()
    elevator_dir = tmp_path / "post"
    elevator_dir.mkdir()
    elevator = elevator_dir / "elevator_articulation.usda"
    elevator.touch()
    wrapper = elevator_dir / "scene_with_elevators.usda"

    path = write_wrapper_usda(building, elevator, wrapper)
    text = path.read_text(encoding="utf-8")

    assert text.startswith("#usda 1.0\n")
    assert 'defaultPrim = "World"' in text
    assert "metersPerUnit = 1" in text
    assert 'upAxis = "Z"' in text
    assert "subLayers = [" in text
    assert "@../static/export_scene.blend/export_scene.usdc@" in text
    assert "@elevator_articulation.usda@" in text
    assert wrapper_usda_text(building, elevator, wrapper) == text


def test_missing_pxr_reports_actionable_error(monkeypatch):
    real_import = importlib.import_module

    def fail_pxr(name, *args, **kwargs):
        if name.startswith("pxr."):
            raise ModuleNotFoundError("test forced missing pxr")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", fail_pxr)

    with pytest.raises(USDDependencyError, match=r"--plan-only.*does not require pxr"):
        load_pxr_modules()


def test_cli_plan_only_validates_without_building_or_pxr(tmp_path, capsys):
    manifest_path = tmp_path / "elevator_manifest.json"
    manifest_path.write_text(json.dumps(manifest_payload()), encoding="utf-8")
    output_dir = tmp_path / "planned"

    result = elevator_tool_main(
        [
            "--manifest",
            str(manifest_path),
            "--output-dir",
            str(output_dir),
            "--plan-only",
        ]
    )

    assert result == 0
    plan_payload = json.loads(
        (output_dir / "elevator_plan.json").read_text(encoding="utf-8")
    )
    assert plan_payload["dof_count"] == 18
    output = capsys.readouterr().out
    assert "dof_count=18" in output
    assert "elevator_usd=" not in output


def test_cli_missing_pxr_fails_clearly_without_partial_outputs(
    tmp_path, capsys, monkeypatch
):
    manifest_path = tmp_path / "elevator_manifest.json"
    manifest_path.write_text(json.dumps(manifest_payload()), encoding="utf-8")
    building = tmp_path / "building.usdc"
    building.touch()
    output_dir = tmp_path / "post"

    def missing_pxr():
        raise USDDependencyError("forced missing pxr; use --plan-only")

    monkeypatch.setattr(elevator_usd_module, "load_pxr_modules", missing_pxr)
    result = elevator_tool_main(
        [
            "--manifest",
            str(manifest_path),
            "--building-usd",
            str(building),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert result == 2
    assert "use --plan-only" in capsys.readouterr().err
    assert not (output_dir / "elevator_plan.json").exists()
    assert not (output_dir / "elevator_articulation.usda").exists()
    assert not (output_dir / "scene_with_elevators.usda").exists()


def test_wrapper_refuses_to_overwrite_input(tmp_path):
    building = tmp_path / "building.usda"
    elevator = tmp_path / "elevator.usda"
    building.touch()
    elevator.touch()

    with pytest.raises(USDAuthoringError, match="must not overwrite an input layer"):
        write_wrapper_usda(building, elevator, building, overwrite=True)
