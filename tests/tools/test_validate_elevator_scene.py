import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

import infinigen.tools.validate_elevator_scene as validator
from infinigen.core.sim.elevator_manifest import ElevatorManifest, write_manifest

TAG_MAPPING = {
    "elevator-shaft.interior.visible.wall": 1,
    "elevator-car.interior.support-surface.visible": 2,
    "door.elevator-door.elevator-landing-door.interior.visible.wall": 3,
    "door.elevator-car-door.elevator-door.interior.visible.wall": 4,
    "elevator-control-panel.interior.visible.wall": 5,
}


class Vector:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)

    def __getitem__(self, index):
        return (self.x, self.y, self.z)[index]


class MaskValue:
    def __init__(self, value):
        self.value = value


class IDPropertyArrayLike:
    """Iterable Blender custom-property stand-in that is not a Sequence."""

    def __init__(self, values):
        self.values = values

    def __iter__(self):
        return iter(self.values)


class FakeObject(dict):
    def __init__(
        self,
        name,
        *,
        role,
        node_path,
        parent=None,
        location=(0.0, 0.0, 0.0),
        dimensions=(0.0, 0.0, 0.0),
        mask_id=None,
        **properties,
    ):
        super().__init__(elevator_role=role, elevator_node_path=node_path, **properties)
        self.name = name
        self.parent = parent
        self.children = []
        self.location = Vector(*location)
        self.dimensions = Vector(*dimensions)
        if parent is None:
            world = self.location
        else:
            parent.children.append(self)
            p = parent.matrix_world.translation
            world = Vector(
                p.x + self.location.x, p.y + self.location.y, p.z + self.location.z
            )
        self.matrix_world = SimpleNamespace(translation=world)
        self.animation_data = None
        if mask_id is None:
            self.type = "EMPTY"
            self.data = None
        else:
            self.type = "MESH"
            attribute = SimpleNamespace(domain="FACE", data=[MaskValue(mask_id)] * 6)
            self.data = SimpleNamespace(
                attributes={"MaskTag": attribute}, polygons=[object()] * 6
            )


def _set_curves(obj, curves):
    obj.animation_data = SimpleNamespace(
        action=SimpleNamespace(
            fcurves=[
                SimpleNamespace(data_path=path, array_index=index)
                for path, index in curves
            ]
        )
    )


def manifest_payload():
    return {
        "schema_version": 1,
        "elevators": [
            {
                "id": "elevator_0",
                "origin_xy": [2.0, -1.0],
                "yaw_degrees": 0.0,
                "shaft": {
                    "inner_size": [2.4, 2.3],
                    "z_min": -0.4,
                    "z_max": 9.4,
                },
                "cabin": {
                    "inner_size": [1.8, 1.7, 2.3],
                    "door": {"width": 1.0, "travel": 0.55},
                },
                "served_floors": [
                    {"floor_id": "G", "stop_z": 0.0},
                    {"floor_id": "1", "stop_z": 3.15},
                    {"floor_id": "2", "stop_z": 6.6},
                ],
            }
        ],
    }


def make_scene(mode="static"):
    manifest = ElevatorManifest.from_dict(manifest_payload())
    config = manifest.elevators[0]
    root = FakeObject(
        "ElevatorSystem_00",
        role="system",
        node_path="",
        location=(2.0, -1.0, 0.0),
        elevator_id="elevator_0",
        elevator_schema_version=1,
        elevator_coordinate_space="root_local",
        elevator_stop_reference="finished_car_floor",
        elevator_stop_z=[stop.stop_z for stop in config.ordered_stops],
        elevator_served_levels_json=json.dumps(
            [stop.floor_id for stop in config.ordered_stops]
        ),
        elevator_mode=mode,
        elevator_phase="idle_closed",
        elevator_phase_code=0,
        elevator_current_stop_index=0,
        elevator_target_stop_index=-1,
        elevator_car_z=0.0,
        elevator_velocity=0.0,
        elevator_door_fraction=0.0,
    )
    shaft = FakeObject("Shaft", role="shaft", node_path="Shaft", parent=root)
    structure = FakeObject(
        "Structure",
        role="shaft_structure",
        node_path="Shaft.Structure",
        parent=shaft,
    )
    landings_root = FakeObject(
        "Landings",
        role="landings",
        node_path="Shaft.Landings",
        parent=shaft,
    )
    slab_thickness = 0.12
    FakeObject(
        "BottomSlab",
        role="shaft_slab_bottom",
        node_path="Shaft.Structure.Slab.Bottom",
        parent=structure,
        location=(0.0, 0.0, config.shaft.z_min - slab_thickness / 2),
        dimensions=(2.6, 2.5, slab_thickness),
        mask_id=1,
    )
    FakeObject(
        "TopSlab",
        role="shaft_slab_top",
        node_path="Shaft.Structure.Slab.Top",
        parent=structure,
        location=(0.0, 0.0, config.shaft.z_max + slab_thickness / 2),
        dimensions=(2.6, 2.5, slab_thickness),
        mask_id=1,
    )

    landing_panels = []
    native_cutters = []
    for index, stop in enumerate(config.ordered_stops):
        token = f"{index:03d}_{stop.floor_id}"
        prefix = f"Shaft.Landings.Landing.{token}"
        landing = FakeObject(
            f"Landing{index}",
            role="landing",
            node_path=prefix,
            parent=landings_root,
            location=(0.0, 0.0, stop.stop_z),
            elevator_level_index=index,
            elevator_level_id=stop.floor_id,
            elevator_stop_z=stop.stop_z,
        )
        door = FakeObject(
            f"LandingDoor{index}",
            role="landing_door",
            node_path=f"{prefix}.Door",
            parent=landing,
            elevator_level_index=index,
        )
        for side, role in (
            ("Left", "landing_door_panel_left"),
            ("Right", "landing_door_panel_right"),
        ):
            landing_panels.append(
                FakeObject(
                    f"Landing{index}{side}",
                    role=role,
                    node_path=f"{prefix}.Door.Panel.{side}",
                    parent=door,
                    dimensions=(0.5, 0.05, 2.1),
                    mask_id=3,
                    elevator_level_index=index,
                )
            )
        FakeObject(
            f"CallStation{index}",
            role="landing_call_station",
            node_path=f"{prefix}.CallStation",
            parent=landing,
            dimensions=(0.1, 0.04, 0.2),
            mask_id=1,
            elevator_level_index=index,
        )
        native_cutters.append(
            FakeObject(
                f"elevator-landing-door_{index}/0",
                role="",
                node_path="",
                location=(0.0, 0.0, stop.stop_z + 1.05),
                dimensions=(1.0, 0.2, 2.1),
                elevator_landing_door=True,
                elevator_id="elevator_0",
                floor_index=index,
            )
        )

    car = FakeObject("Car", role="car", node_path="Car", parent=root)
    cabin = FakeObject("Cabin", role="cabin", node_path="Car.Cabin", parent=car)
    FakeObject(
        "CarFloor",
        role="car_floor",
        node_path="Car.Cabin.Floor",
        parent=cabin,
        dimensions=(1.8, 1.7, 0.08),
        mask_id=2,
    )
    FakeObject(
        "ControlPanel",
        role="car_control_panel",
        node_path="Car.Cabin.ControlPanel",
        parent=cabin,
        dimensions=(0.04, 0.2, 0.6),
        mask_id=5,
    )
    car_door = FakeObject("CarDoor", role="car_door", node_path="Car.Door", parent=car)
    car_panels = [
        FakeObject(
            "CarDoorLeft",
            role="car_door_panel_left",
            node_path="Car.Door.Panel.Left",
            parent=car_door,
            dimensions=(0.5, 0.05, 2.1),
            mask_id=4,
        ),
        FakeObject(
            "CarDoorRight",
            role="car_door_panel_right",
            node_path="Car.Door.Panel.Right",
            parent=car_door,
            dimensions=(0.5, 0.05, 2.1),
            mask_id=4,
        ),
    ]

    if mode == "animated":
        root["elevator_animation_frame_start"] = 1
        root["elevator_animation_frame_end"] = 120
        root["elevator_animation_duration"] = 5.0
        _set_curves(
            root,
            [(f'["{name}"]', 0) for name in validator.ANIMATED_ROOT_CURVES],
        )
        _set_curves(car, [("location", 2)])
        for panel in [*car_panels, *landing_panels]:
            _set_curves(panel, [("location", 0)])

    return manifest, (*validator._object_tree(root), *native_cutters)


@pytest.mark.parametrize("mode", ["static", "animated"])
def test_valid_static_and_animated_elevator_scenes_pass(mode):
    manifest, objects = make_scene(mode)

    report = validator.validate_scene_objects(
        manifest, objects, tag_mapping=TAG_MAPPING
    )

    assert report["status"] == "PASS"
    assert report["summary"]["failed_check_count"] == 0
    assert report["elevators"][0]["status"] == "PASS"


def test_corrupt_hierarchy_alignment_and_semantics_are_reported_together():
    manifest, objects = make_scene("static")
    objects = list(objects)
    landing = next(obj for obj in objects if obj.get("elevator_role") == "landing")
    landing.matrix_world.translation.z += 0.25
    left = next(
        obj for obj in objects if obj.get("elevator_role") == "car_door_panel_left"
    )
    right = next(
        obj for obj in objects if obj.get("elevator_role") == "car_door_panel_right"
    )
    right["elevator_node_path"] = left["elevator_node_path"]
    del left.data.attributes["MaskTag"]
    objects.append(FakeObject("OrphanCar", role="car", node_path="Orphan.Car"))

    report = validator.validate_scene_objects(
        manifest, objects, tag_mapping=TAG_MAPPING
    )
    failed = {
        check["name"]
        for check in report["elevators"][0]["checks"]
        if check["status"] == "FAIL"
    }

    assert report["status"] == "FAIL"
    assert "not parented" in " ".join(report["global_errors"])
    assert {
        "stable_roles_and_node_paths",
        "landing_stop_alignment",
        "mesh_masktag",
    } <= failed


def test_idproperty_stop_array_is_accepted_and_bad_panel_index_is_a_failure():
    manifest, objects = make_scene("static")
    root = next(obj for obj in objects if obj.get("elevator_role") == "system")
    root["elevator_stop_z"] = IDPropertyArrayLike(root["elevator_stop_z"])

    passing = validator.validate_scene_objects(
        manifest, objects, tag_mapping=TAG_MAPPING
    )
    assert passing["status"] == "PASS"

    panel = next(
        obj for obj in objects if obj.get("elevator_role") == "landing_door_panel_left"
    )
    panel["elevator_level_index"] = None
    failing = validator.validate_scene_objects(
        manifest, objects, tag_mapping=TAG_MAPPING
    )
    failed = {
        check["name"]
        for check in failing["elevators"][0]["checks"]
        if check["status"] == "FAIL"
    }
    assert "landing_panel_indices" in failed


def test_native_landing_opening_misalignment_is_reported():
    manifest, objects = make_scene("static")
    cutter = next(obj for obj in objects if obj.get("elevator_landing_door", False))
    cutter.location.z += 0.2

    report = validator.validate_scene_objects(
        manifest, objects, tag_mapping=TAG_MAPPING
    )
    failed = {
        check["name"]
        for check in report["elevators"][0]["checks"]
        if check["status"] == "FAIL"
    }

    assert "native_landing_opening_alignment" in failed


def test_cli_writes_fail_json_and_returns_nonzero(tmp_path, monkeypatch, capsys):
    manifest, objects = make_scene("static")
    objects = list(objects)
    objects.pop(
        next(
            index
            for index, obj in enumerate(objects)
            if obj.get("elevator_role") == "landing_door_panel_right"
        )
    )
    # Remove from the hierarchy as Blender's bpy.data.objects and root traversal
    # should agree on the missing object.
    root = next(obj for obj in objects if obj.get("elevator_role") == "system")
    missing_names = {obj.name for obj in validator._object_tree(root)} - {
        obj.name for obj in objects
    }
    if missing_names:
        for parent in objects:
            parent.children[:] = [
                child for child in parent.children if child.name not in missing_names
            ]

    manifest_path = write_manifest(manifest, tmp_path / "elevator_manifest.json")
    blend_path = tmp_path / "scene.blend"
    blend_path.touch()
    masktag_path = tmp_path / "MaskTag.json"
    masktag_path.write_text(json.dumps(TAG_MAPPING), encoding="utf-8")
    output_path = tmp_path / "validation.json"
    monkeypatch.setattr(validator, "open_blend_objects", lambda _: tuple(objects))

    exit_code = validator.main(
        [
            "--blend",
            str(blend_path),
            "--manifest",
            str(manifest_path),
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 1
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["status"] == "FAIL"
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"


def test_cli_refuses_to_overwrite_an_input(tmp_path, capsys):
    manifest = ElevatorManifest.from_dict(manifest_payload())
    manifest_path = write_manifest(manifest, tmp_path / "elevator_manifest.json")
    blend_path = tmp_path / "scene.blend"
    blend_path.write_bytes(b"unchanged")

    exit_code = validator.main(
        [
            "--blend",
            str(blend_path),
            "--manifest",
            str(manifest_path),
            "--output",
            str(blend_path),
        ]
    )

    assert exit_code == 2
    assert blend_path.read_bytes() == b"unchanged"
    report = json.loads(capsys.readouterr().out)
    assert report["fatal"] is True
    assert "overwrite" in report["errors"][0]


def test_real_blender_asset_roundtrips_through_cli(tmp_path, capfd):
    bpy = pytest.importorskip("bpy")

    from infinigen.assets.objects.elements.elevators.blender import (
        build_elevator_asset,
    )
    from infinigen.assets.objects.elements.elevators.model import ElevatorSpec
    from infinigen.core import tagging
    from infinigen.core.constraints.example_solver.room.elevator import (
        _manifest_for_assets,
        _tag_asset_mesh,
    )

    bpy.ops.wm.read_factory_settings(use_empty=True)
    tagging.tag_system.clear()
    spec = ElevatorSpec.evenly_spaced(
        4,
        floor_height=3.1,
        served_levels=("F0", "F1", "F2", "F3"),
    )
    asset = build_elevator_asset(spec, seed=20260710, name="ValidatedLift")
    asset.root["elevator_id"] = "elevator_0"
    asset.root.location = (2.0, -1.0, 0.0)
    asset.root.rotation_euler.z = 0.25
    bpy.context.view_layer.update()

    for obj in asset.all_objects():
        if obj.type == "MESH":
            _tag_asset_mesh(obj)
    tagging.tag_system.relabel_obj(asset.root)

    manifest = _manifest_for_assets(
        [asset], scene_seed=20260710, scene_id="validator_blender_smoke"
    )
    manifest_path = write_manifest(manifest, tmp_path / "elevator_manifest.json")
    tagging.tag_system.save_tag(str(tmp_path / "MaskTag.json"))
    blend_path = tmp_path / "scene.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    capfd.readouterr()

    output_path = tmp_path / "elevator_validation.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(validator.__file__),
            "--blend",
            str(blend_path),
            "--manifest",
            str(manifest_path),
            "--output",
            str(output_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert completed.returncode == 0, completed.stderr or json.dumps(report, indent=2)
    assert report["status"] == "PASS"
    assert json.loads(completed.stdout)["status"] == "PASS"
