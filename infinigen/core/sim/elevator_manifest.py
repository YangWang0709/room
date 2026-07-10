"""Validated, simulator-agnostic manifests for post-export elevator systems.

All distances are expressed in stage units.  ``meters_per_unit`` records the
conversion to metres and the current implementation requires a Z-up stage.
The ``stop_z`` values are absolute stage Z coordinates for the finished cabin
floor at each served landing; they are intentionally not inferred from a
nominal storey height.
"""

from __future__ import annotations

import json
import math
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
_USD_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_STOP_EPSILON = 1e-6


class ManifestValidationError(ValueError):
    """Raised when an elevator manifest is malformed or internally invalid."""


def _mapping(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ManifestValidationError(f"{context} must be a JSON object")
    return value


def _keys(
    value: Mapping[str, Any],
    *,
    required: set[str],
    optional: set[str],
    context: str,
) -> None:
    missing = sorted(required.difference(value))
    if missing:
        raise ManifestValidationError(
            f"{context} is missing required field(s): {', '.join(missing)}"
        )
    unknown = sorted(set(value).difference(required | optional))
    if unknown:
        raise ManifestValidationError(
            f"{context} has unknown field(s): {', '.join(unknown)}"
        )


def _number(value: Any, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ManifestValidationError(f"{context} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ManifestValidationError(f"{context} must be a finite number")
    return result


def _positive(value: Any, context: str, *, allow_zero: bool = False) -> float:
    result = _number(value, context)
    invalid = result < 0 if allow_zero else result <= 0
    if invalid:
        qualifier = "non-negative" if allow_zero else "positive"
        raise ManifestValidationError(f"{context} must be {qualifier}")
    return result


def _vector(value: Any, length: int, context: str) -> tuple[float, ...]:
    if (
        isinstance(value, (str, bytes))
        or not isinstance(value, Sequence)
        or len(value) != length
    ):
        raise ManifestValidationError(
            f"{context} must be an array containing exactly {length} numbers"
        )
    return tuple(_number(v, f"{context}[{i}]") for i, v in enumerate(value))


def _integer(value: Any, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ManifestValidationError(f"{context} must be an integer")
    return value


@dataclass(frozen=True)
class DriveConfig:
    """USD Physics drive gains for a single family of linear joints."""

    stiffness: float
    damping: float
    max_force: float

    @classmethod
    def from_dict(
        cls, value: Mapping[str, Any], context: str = "drive"
    ) -> "DriveConfig":
        value = _mapping(value, context)
        _keys(
            value,
            required={"stiffness", "damping", "max_force"},
            optional=set(),
            context=context,
        )
        return cls(
            stiffness=_positive(
                value["stiffness"], f"{context}.stiffness", allow_zero=True
            ),
            damping=_positive(value["damping"], f"{context}.damping", allow_zero=True),
            max_force=_positive(value["max_force"], f"{context}.max_force"),
        )

    def to_dict(self) -> dict[str, float]:
        return {
            "stiffness": self.stiffness,
            "damping": self.damping,
            "max_force": self.max_force,
        }


DEFAULT_LIFT_DRIVE = DriveConfig(
    stiffness=120_000.0, damping=20_000.0, max_force=250_000.0
)
DEFAULT_DOOR_DRIVE = DriveConfig(stiffness=5_000.0, damping=500.0, max_force=10_000.0)


@dataclass(frozen=True)
class DoorConfig:
    """Shared geometry for the two-leaf cabin and landing doors."""

    width: float = 1.0
    height: float = 2.1
    thickness: float = 0.05
    travel: float = 0.55
    overlap: float = 0.025
    landing_gap: float = 0.08
    leaf_mass_kg: float = 25.0

    @classmethod
    def from_dict(cls, value: Mapping[str, Any], context: str = "door") -> "DoorConfig":
        value = _mapping(value, context)
        defaults = cls()
        _keys(
            value,
            required=set(),
            optional={
                "width",
                "height",
                "thickness",
                "travel",
                "overlap",
                "landing_gap",
                "leaf_mass_kg",
            },
            context=context,
        )
        result = cls(
            width=_positive(value.get("width", defaults.width), f"{context}.width"),
            height=_positive(value.get("height", defaults.height), f"{context}.height"),
            thickness=_positive(
                value.get("thickness", defaults.thickness),
                f"{context}.thickness",
            ),
            travel=_positive(value.get("travel", defaults.travel), f"{context}.travel"),
            overlap=_positive(
                value.get("overlap", defaults.overlap),
                f"{context}.overlap",
                allow_zero=True,
            ),
            landing_gap=_positive(
                value.get("landing_gap", defaults.landing_gap),
                f"{context}.landing_gap",
                allow_zero=True,
            ),
            leaf_mass_kg=_positive(
                value.get("leaf_mass_kg", defaults.leaf_mass_kg),
                f"{context}.leaf_mass_kg",
            ),
        )
        if result.travel + _STOP_EPSILON < result.width / 2:
            raise ManifestValidationError(
                f"{context}.travel must be at least half of {context}.width "
                "so that the two leaves can clear the opening"
            )
        return result

    @property
    def leaf_width(self) -> float:
        return self.width / 2 + self.overlap

    def to_dict(self) -> dict[str, float]:
        return {
            "width": self.width,
            "height": self.height,
            "thickness": self.thickness,
            "travel": self.travel,
            "overlap": self.overlap,
            "landing_gap": self.landing_gap,
            "leaf_mass_kg": self.leaf_mass_kg,
        }


@dataclass(frozen=True)
class CabinConfig:
    """Cabin interior dimensions and simple collision-proxy parameters."""

    inner_size: tuple[float, float, float]
    wall_thickness: float = 0.08
    floor_thickness: float = 0.12
    mass_kg: float = 500.0
    door: DoorConfig = field(default_factory=DoorConfig)

    @classmethod
    def from_dict(
        cls, value: Mapping[str, Any], context: str = "cabin"
    ) -> "CabinConfig":
        value = _mapping(value, context)
        defaults = cls(inner_size=(1.8, 1.8, 2.3))
        _keys(
            value,
            required={"inner_size"},
            optional={"wall_thickness", "floor_thickness", "mass_kg", "door"},
            context=context,
        )
        inner_size = _vector(value["inner_size"], 3, f"{context}.inner_size")
        if any(component <= 0 for component in inner_size):
            raise ManifestValidationError(
                f"{context}.inner_size components must all be positive"
            )
        return cls(
            inner_size=inner_size,
            wall_thickness=_positive(
                value.get("wall_thickness", defaults.wall_thickness),
                f"{context}.wall_thickness",
            ),
            floor_thickness=_positive(
                value.get("floor_thickness", defaults.floor_thickness),
                f"{context}.floor_thickness",
            ),
            mass_kg=_positive(
                value.get("mass_kg", defaults.mass_kg), f"{context}.mass_kg"
            ),
            door=DoorConfig.from_dict(value.get("door", {}), f"{context}.door"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "inner_size": list(self.inner_size),
            "wall_thickness": self.wall_thickness,
            "floor_thickness": self.floor_thickness,
            "mass_kg": self.mass_kg,
            "door": self.door.to_dict(),
        }


@dataclass(frozen=True)
class ShaftConfig:
    """Axis-aligned shaft bounds in an elevator's local XY frame."""

    inner_size: tuple[float, float]
    z_min: float
    z_max: float

    @classmethod
    def from_dict(
        cls, value: Mapping[str, Any], context: str = "shaft"
    ) -> "ShaftConfig":
        value = _mapping(value, context)
        _keys(
            value,
            required={"inner_size", "z_min", "z_max"},
            optional=set(),
            context=context,
        )
        inner_size = _vector(value["inner_size"], 2, f"{context}.inner_size")
        if any(component <= 0 for component in inner_size):
            raise ManifestValidationError(
                f"{context}.inner_size components must both be positive"
            )
        z_min = _number(value["z_min"], f"{context}.z_min")
        z_max = _number(value["z_max"], f"{context}.z_max")
        if z_max <= z_min:
            raise ManifestValidationError(f"{context}.z_max must exceed z_min")
        return cls(inner_size=inner_size, z_min=z_min, z_max=z_max)

    def to_dict(self) -> dict[str, Any]:
        return {
            "inner_size": list(self.inner_size),
            "z_min": self.z_min,
            "z_max": self.z_max,
        }


@dataclass(frozen=True)
class ElevatorStop:
    """A served floor and its measured cabin-floor elevation."""

    floor_id: str
    stop_z: float

    @classmethod
    def from_dict(
        cls, value: Mapping[str, Any], context: str = "served_floor"
    ) -> "ElevatorStop":
        value = _mapping(value, context)
        _keys(
            value,
            required={"floor_id", "stop_z"},
            optional=set(),
            context=context,
        )
        floor_value = value["floor_id"]
        if isinstance(floor_value, bool) or not isinstance(floor_value, (str, int)):
            raise ManifestValidationError(
                f"{context}.floor_id must be a string or integer"
            )
        floor_id = str(floor_value).strip()
        if not floor_id:
            raise ManifestValidationError(f"{context}.floor_id must not be empty")
        return cls(
            floor_id=floor_id,
            stop_z=_number(value["stop_z"], f"{context}.stop_z"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"floor_id": self.floor_id, "stop_z": self.stop_z}


@dataclass(frozen=True)
class ElevatorConfig:
    """One elevator and the subset of floors that it serves."""

    elevator_id: str
    origin_xy: tuple[float, float]
    yaw_degrees: float
    shaft: ShaftConfig
    cabin: CabinConfig
    served_floors: tuple[ElevatorStop, ...]
    lift_drive: DriveConfig = DEFAULT_LIFT_DRIVE
    door_drive: DriveConfig = DEFAULT_DOOR_DRIVE

    @classmethod
    def from_dict(
        cls, value: Mapping[str, Any], context: str = "elevator"
    ) -> "ElevatorConfig":
        value = _mapping(value, context)
        _keys(
            value,
            required={"id", "origin_xy", "shaft", "cabin", "served_floors"},
            optional={"yaw_degrees", "lift_drive", "door_drive"},
            context=context,
        )
        elevator_id = value["id"]
        if not isinstance(elevator_id, str) or not _USD_IDENTIFIER.fullmatch(
            elevator_id
        ):
            raise ManifestValidationError(
                f"{context}.id must be a valid USD identifier matching "
                "[A-Za-z_][A-Za-z0-9_]*"
            )

        raw_stops = value["served_floors"]
        if isinstance(raw_stops, (str, bytes)) or not isinstance(raw_stops, Sequence):
            raise ManifestValidationError(f"{context}.served_floors must be an array")
        if len(raw_stops) < 2:
            raise ManifestValidationError(
                f"{context}.served_floors must contain at least two stops"
            )
        stops = tuple(
            ElevatorStop.from_dict(stop, f"{context}.served_floors[{i}]")
            for i, stop in enumerate(raw_stops)
        )
        floor_ids = [stop.floor_id for stop in stops]
        if len(set(floor_ids)) != len(floor_ids):
            raise ManifestValidationError(
                f"{context}.served_floors contains duplicate floor_id values"
            )
        sorted_z = sorted(stop.stop_z for stop in stops)
        if any(
            right - left <= _STOP_EPSILON
            for left, right in zip(sorted_z[:-1], sorted_z[1:])
        ):
            raise ManifestValidationError(
                f"{context}.served_floors contains duplicate or indistinguishable "
                "stop_z values"
            )

        shaft = ShaftConfig.from_dict(value["shaft"], f"{context}.shaft")
        cabin = CabinConfig.from_dict(value["cabin"], f"{context}.cabin")
        result = cls(
            elevator_id=elevator_id,
            origin_xy=_vector(value["origin_xy"], 2, f"{context}.origin_xy"),
            yaw_degrees=_number(
                value.get("yaw_degrees", 0.0), f"{context}.yaw_degrees"
            ),
            shaft=shaft,
            cabin=cabin,
            served_floors=stops,
            lift_drive=DriveConfig.from_dict(
                value.get("lift_drive", DEFAULT_LIFT_DRIVE.to_dict()),
                f"{context}.lift_drive",
            ),
            door_drive=DriveConfig.from_dict(
                value.get("door_drive", DEFAULT_DOOR_DRIVE.to_dict()),
                f"{context}.door_drive",
            ),
        )
        result.validate_geometry(context)
        return result

    def validate_geometry(self, context: str = "elevator") -> None:
        cabin_width, cabin_depth, cabin_height = self.cabin.inner_size
        shaft_width, shaft_depth = self.shaft.inner_size
        outer_width = cabin_width + 2 * self.cabin.wall_thickness
        outer_depth = cabin_depth + 2 * self.cabin.wall_thickness
        if outer_width >= shaft_width or outer_depth >= shaft_depth:
            raise ManifestValidationError(
                f"{context}.cabin outer XY size must be smaller than the shaft "
                "inner_size on both axes"
            )
        if self.cabin.door.width > cabin_width + _STOP_EPSILON:
            raise ManifestValidationError(
                f"{context}.cabin.door.width must not exceed cabin inner width"
            )
        if self.cabin.door.height > cabin_height + _STOP_EPSILON:
            raise ManifestValidationError(
                f"{context}.cabin.door.height must not exceed cabin inner height"
            )
        for i, stop in enumerate(self.served_floors):
            bottom = stop.stop_z - self.cabin.floor_thickness
            top = stop.stop_z + cabin_height + self.cabin.wall_thickness
            if bottom < self.shaft.z_min - _STOP_EPSILON:
                raise ManifestValidationError(
                    f"{context}.served_floors[{i}].stop_z places the cabin below "
                    "shaft.z_min"
                )
            if top > self.shaft.z_max + _STOP_EPSILON:
                raise ManifestValidationError(
                    f"{context}.served_floors[{i}].stop_z places the cabin above "
                    "shaft.z_max"
                )

    @property
    def ordered_stops(self) -> tuple[ElevatorStop, ...]:
        return tuple(sorted(self.served_floors, key=lambda stop: stop.stop_z))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.elevator_id,
            "origin_xy": list(self.origin_xy),
            "yaw_degrees": self.yaw_degrees,
            "shaft": self.shaft.to_dict(),
            "cabin": self.cabin.to_dict(),
            "served_floors": [stop.to_dict() for stop in self.served_floors],
            "lift_drive": self.lift_drive.to_dict(),
            "door_drive": self.door_drive.to_dict(),
        }


@dataclass(frozen=True)
class ElevatorManifest:
    """Top-level manifest supporting one or more independent elevators."""

    elevators: tuple[ElevatorConfig, ...]
    schema_version: int = SCHEMA_VERSION
    meters_per_unit: float = 1.0
    up_axis: str = "Z"
    scene_id: str | None = None
    seed: int | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ElevatorManifest":
        value = _mapping(value, "manifest")
        _keys(
            value,
            required={"schema_version", "elevators"},
            optional={"meters_per_unit", "up_axis", "scene_id", "seed"},
            context="manifest",
        )
        schema_version = _integer(value["schema_version"], "manifest.schema_version")
        if schema_version != SCHEMA_VERSION:
            raise ManifestValidationError(
                f"manifest.schema_version={schema_version} is unsupported; "
                f"expected {SCHEMA_VERSION}"
            )
        up_axis = value.get("up_axis", "Z")
        if up_axis != "Z":
            raise ManifestValidationError(
                "manifest.up_axis must be 'Z' for the elevator USD builder"
            )
        meters_per_unit = _positive(
            value.get("meters_per_unit", 1.0), "manifest.meters_per_unit"
        )

        raw_elevators = value["elevators"]
        if (
            isinstance(raw_elevators, (str, bytes))
            or not isinstance(raw_elevators, Sequence)
            or not raw_elevators
        ):
            raise ManifestValidationError(
                "manifest.elevators must be a non-empty array"
            )
        elevators = tuple(
            ElevatorConfig.from_dict(item, f"manifest.elevators[{i}]")
            for i, item in enumerate(raw_elevators)
        )
        ids = [elevator.elevator_id for elevator in elevators]
        if len(set(ids)) != len(ids):
            raise ManifestValidationError(
                "manifest.elevators contains duplicate elevator id values"
            )

        scene_id = value.get("scene_id")
        if scene_id is not None and (
            not isinstance(scene_id, str) or not scene_id.strip()
        ):
            raise ManifestValidationError(
                "manifest.scene_id must be a non-empty string when provided"
            )
        seed = value.get("seed")
        if seed is not None:
            seed = _integer(seed, "manifest.seed")

        return cls(
            elevators=elevators,
            schema_version=schema_version,
            meters_per_unit=meters_per_unit,
            up_axis=up_axis,
            scene_id=scene_id,
            seed=seed,
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": self.schema_version,
            "meters_per_unit": self.meters_per_unit,
            "up_axis": self.up_axis,
            "elevators": [elevator.to_dict() for elevator in self.elevators],
        }
        if self.scene_id is not None:
            result["scene_id"] = self.scene_id
        if self.seed is not None:
            result["seed"] = self.seed
        return result


def loads_manifest(text: str) -> ElevatorManifest:
    """Parse and validate an elevator manifest from JSON text."""

    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ManifestValidationError(
            f"invalid elevator manifest JSON at line {exc.lineno}, "
            f"column {exc.colno}: {exc.msg}"
        ) from exc
    return ElevatorManifest.from_dict(value)


def read_manifest(path: str | Path) -> ElevatorManifest:
    """Read and validate an elevator manifest file."""

    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestValidationError(
            f"could not read elevator manifest {path}: {exc}"
        ) from exc
    return loads_manifest(text)


def validate_manifest(manifest: ElevatorManifest) -> ElevatorManifest:
    """Validate a manifest, including instances assembled programmatically."""

    if not isinstance(manifest, ElevatorManifest):
        raise TypeError("manifest must be an ElevatorManifest")
    return ElevatorManifest.from_dict(manifest.to_dict())


def dumps_manifest(manifest: ElevatorManifest) -> str:
    """Serialize a validated manifest in a deterministic canonical form."""

    manifest = validate_manifest(manifest)
    return json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n"


def write_manifest(manifest: ElevatorManifest, path: str | Path) -> Path:
    """Atomically write a validated elevator manifest."""

    manifest = validate_manifest(manifest)
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
        handle.write(dumps_manifest(manifest))
    temporary.replace(path)
    return path
