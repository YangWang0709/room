import json
from dataclasses import replace

import pytest

from infinigen.core.sim.elevator_manifest import (
    ElevatorManifest,
    ManifestValidationError,
    dumps_manifest,
    loads_manifest,
    read_manifest,
    validate_manifest,
    write_manifest,
)


def manifest_payload():
    return {
        "schema_version": 1,
        "meters_per_unit": 1.0,
        "up_axis": "Z",
        "scene_id": "seed_123_four_storey",
        "seed": 123,
        "elevators": [
            {
                "id": "Lift_A",
                "origin_xy": [4.25, -1.5],
                "yaw_degrees": 90.0,
                "shaft": {
                    "inner_size": [2.45, 2.35],
                    "z_min": -0.5,
                    "z_max": 12.5,
                },
                "cabin": {
                    "inner_size": [1.8, 1.7, 2.3],
                    "wall_thickness": 0.08,
                    "floor_thickness": 0.12,
                    "mass_kg": 520.0,
                    "door": {
                        "width": 1.05,
                        "height": 2.1,
                        "thickness": 0.05,
                        "travel": 0.56,
                        "overlap": 0.025,
                        "landing_gap": 0.08,
                        "leaf_mass_kg": 24.0,
                    },
                },
                "served_floors": [
                    {"floor_id": "G", "stop_z": 0.0},
                    {"floor_id": "1", "stop_z": 3.05},
                    {"floor_id": "2", "stop_z": 6.35},
                    {"floor_id": "3", "stop_z": 9.8},
                ],
            },
            {
                "id": "ServiceLift",
                "origin_xy": [-3.0, 8.0],
                "shaft": {
                    "inner_size": [2.7, 2.6],
                    "z_min": -0.4,
                    "z_max": 10.0,
                },
                "cabin": {
                    "inner_size": [1.9, 1.8, 2.25],
                    "door": {"width": 1.0, "travel": 0.55},
                },
                "served_floors": [
                    {"floor_id": 0, "stop_z": 0.0},
                    {"floor_id": 2, "stop_z": 6.35},
                ],
                "lift_drive": {
                    "stiffness": 140000,
                    "damping": 22000,
                    "max_force": 300000,
                },
            },
        ],
    }


def test_manifest_round_trip_preserves_measured_stops_and_multiple_elevators():
    manifest = ElevatorManifest.from_dict(manifest_payload())

    assert [e.elevator_id for e in manifest.elevators] == ["Lift_A", "ServiceLift"]
    assert [stop.stop_z for stop in manifest.elevators[0].served_floors] == [
        0.0,
        3.05,
        6.35,
        9.8,
    ]
    assert [stop.floor_id for stop in manifest.elevators[1].served_floors] == [
        "0",
        "2",
    ]

    round_tripped = loads_manifest(dumps_manifest(manifest))
    assert round_tripped == manifest


def test_manifest_file_write_and_read_are_canonical(tmp_path):
    manifest = ElevatorManifest.from_dict(manifest_payload())
    path = write_manifest(manifest, tmp_path / "nested" / "elevator_manifest.json")

    assert read_manifest(path) == manifest
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["elevators"][0]["served_floors"][3]["stop_z"] == 9.8
    assert path.read_text(encoding="utf-8").endswith("\n")


@pytest.mark.parametrize(
    "mutate, message",
    [
        (
            lambda payload: payload["elevators"][0]["served_floors"].__setitem__(
                1, {"floor_id": "1", "stop_z": 0.0}
            ),
            "stop_z",
        ),
        (
            lambda payload: payload["elevators"][0].__setitem__(
                "served_floors", [{"floor_id": "G", "stop_z": 0.0}]
            ),
            "at least two",
        ),
        (
            lambda payload: payload["elevators"][1].__setitem__("id", "Lift_A"),
            "duplicate elevator id",
        ),
        (
            lambda payload: payload["elevators"][0]["cabin"].__setitem__(
                "inner_size", [2.4, 2.3, 2.3]
            ),
            "smaller than the shaft",
        ),
        (
            lambda payload: payload["elevators"][0].__setitem__("typo_field", 1),
            "unknown field",
        ),
        (
            lambda payload: payload.__setitem__("up_axis", "Y"),
            "must be 'Z'",
        ),
    ],
)
def test_manifest_validation_rejects_unsafe_or_ambiguous_input(mutate, message):
    payload = manifest_payload()
    mutate(payload)

    with pytest.raises(ManifestValidationError, match=message):
        ElevatorManifest.from_dict(payload)


def test_invalid_json_has_line_and_column_context():
    with pytest.raises(ManifestValidationError, match=r"line 1, column"):
        loads_manifest('{"schema_version": 1,,}')


def test_programmatically_modified_manifest_is_revalidated():
    manifest = ElevatorManifest.from_dict(manifest_payload())
    invalid = replace(manifest, meters_per_unit=0.0)

    with pytest.raises(ManifestValidationError, match="meters_per_unit"):
        validate_manifest(invalid)
