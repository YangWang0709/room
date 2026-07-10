"""Read-only validation for Blender elevator scenes and their manifests.

The module keeps scene inspection separate from validation so its core logic
can be tested without Blender.  The CLI opens the requested ``.blend`` file,
never saves it, and emits one JSON PASS/FAIL report.  Validation failures exit
with status 1; input, Blender, or JSON errors exit with status 2.
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import json
import math
import os
import sys
from array import array
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from infinigen.core.sim.elevator_manifest import (
    ElevatorConfig,
    ElevatorManifest,
    ManifestValidationError,
    read_manifest,
)

REPORT_SCHEMA_VERSION = 1
MASK_TAG_ATTRIBUTE = "MaskTag"
VALID_MODES = {"static", "animated"}
ROOT_CONTROL_PROPERTIES = (
    "elevator_phase",
    "elevator_phase_code",
    "elevator_current_stop_index",
    "elevator_target_stop_index",
    "elevator_car_z",
    "elevator_velocity",
    "elevator_door_fraction",
)
ANIMATED_ROOT_CURVES = (
    "elevator_phase_code",
    "elevator_current_stop_index",
    "elevator_target_stop_index",
    "elevator_car_z",
    "elevator_velocity",
    "elevator_door_fraction",
)
REQUIRED_ELEVATOR_LABELS = {
    "elevator-shaft",
    "elevator-car",
    "elevator-landing-door",
    "elevator-car-door",
    "elevator-control-panel",
}


class SceneValidationError(RuntimeError):
    """Raised when the scene cannot be opened or inspected."""


@contextlib.contextmanager
def _silence_native_stdout():
    """Keep Blender's delayed C-level load message out of the JSON stream."""

    try:
        stdout_fd = sys.stdout.fileno()
    except (AttributeError, OSError):
        yield
        return

    sys.stdout.flush()
    saved_fd = os.dup(stdout_fd)
    null_fd = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(null_fd, stdout_fd)
        yield
    finally:
        # Blender's ``Read blend: ...`` message may remain in libc's buffer
        # until interpreter shutdown.  Flush it while fd 1 still points at
        # /dev/null, then restore the caller's stdout descriptor.
        sys.stdout.flush()
        try:
            libc = ctypes.CDLL(None)
            libc.fflush.argtypes = [ctypes.c_void_p]
            libc.fflush.restype = ctypes.c_int
            libc.fflush(None)
        except (AttributeError, OSError):
            pass
        os.dup2(saved_fd, stdout_fd)
        os.close(null_fd)
        os.close(saved_fd)


def _property(obj: Any, key: str, default: Any = None) -> Any:
    getter = getattr(obj, "get", None)
    if getter is None:
        return default
    try:
        return getter(key, default)
    except TypeError:
        value = getter(key)
        return default if value is None else value


def _children(obj: Any) -> tuple[Any, ...]:
    return tuple(getattr(obj, "children", ()) or ())


def _object_tree(root: Any) -> tuple[Any, ...]:
    result = []
    queue = [root]
    visited = set()
    while queue:
        obj = queue.pop(0)
        identity = id(obj)
        if identity in visited:
            continue
        visited.add(identity)
        result.append(obj)
        queue.extend(sorted(_children(obj), key=lambda child: str(child.name)))
    return tuple(result)


def _component(value: Any, index: int, name: str) -> float:
    if hasattr(value, name):
        return float(getattr(value, name))
    return float(value[index])


def _world_translation(obj: Any) -> tuple[float, float, float]:
    matrix_world = getattr(obj, "matrix_world", None)
    translation = getattr(matrix_world, "translation", None)
    if translation is not None:
        return (
            _component(translation, 0, "x"),
            _component(translation, 1, "y"),
            _component(translation, 2, "z"),
        )

    location = getattr(obj, "location", (0.0, 0.0, 0.0))
    local = (
        _component(location, 0, "x"),
        _component(location, 1, "y"),
        _component(location, 2, "z"),
    )
    parent = getattr(obj, "parent", None)
    if parent is None:
        return local
    parent_world = _world_translation(parent)
    return tuple(parent_world[i] + local[i] for i in range(3))


def _dimension_z(obj: Any) -> float:
    dimensions = getattr(obj, "dimensions", None)
    if dimensions is None:
        raise SceneValidationError(f"object {obj.name!r} has no dimensions")
    return abs(_component(dimensions, 2, "z"))


def _float_sequence(value: Any) -> tuple[float, ...] | None:
    # Blender exposes numeric custom-property arrays as IDPropertyArray.  It is
    # iterable, but it is not guaranteed to register as a collections.abc
    # Sequence on every supported Blender/Python build.
    if isinstance(value, (str, bytes, Mapping)):
        return None
    try:
        result = tuple(float(item) for item in value)
    except (TypeError, ValueError):
        return None
    return result if all(math.isfinite(item) for item in result) else None


def _close(actual: float, expected: float, tolerance: float) -> bool:
    return math.isfinite(actual) and abs(actual - expected) <= tolerance


def _sequences_close(
    actual: Sequence[float], expected: Sequence[float], tolerance: float
) -> bool:
    return len(actual) == len(expected) and all(
        _close(float(a), float(e), tolerance) for a, e in zip(actual, expected)
    )


def _animation_curves(obj: Any) -> tuple[Any, ...]:
    animation_data = getattr(obj, "animation_data", None)
    action = getattr(animation_data, "action", None)
    return tuple(getattr(action, "fcurves", ()) or ())


def _has_curve(obj: Any, data_path: str, array_index: int | None = None) -> bool:
    for curve in _animation_curves(obj):
        if getattr(curve, "data_path", None) != data_path:
            continue
        if array_index is None or getattr(curve, "array_index", None) == array_index:
            return True
    return False


def _mask_values(obj: Any) -> tuple[set[int], str | None]:
    if getattr(obj, "type", None) != "MESH":
        return set(), None
    data = getattr(obj, "data", None)
    attributes = getattr(data, "attributes", None)
    if attributes is None or MASK_TAG_ATTRIBUTE not in attributes:
        return set(), f"mesh {obj.name!r} has no {MASK_TAG_ATTRIBUTE} attribute"
    attribute = attributes[MASK_TAG_ATTRIBUTE]
    domain = getattr(attribute, "domain", None)
    if domain != "FACE":
        return set(), (
            f"mesh {obj.name!r} has {MASK_TAG_ATTRIBUTE} domain {domain!r}, "
            "expected 'FACE'"
        )
    values_data = getattr(attribute, "data", ())
    expected_faces = len(getattr(data, "polygons", ()) or ())
    if len(values_data) != expected_faces:
        return set(), (
            f"mesh {obj.name!r} has {len(values_data)} MaskTag values for "
            f"{expected_faces} faces"
        )
    if not values_data:
        return set(), f"mesh {obj.name!r} has no faces to carry MaskTag semantics"
    if hasattr(values_data, "foreach_get"):
        buffer = array("i", [0]) * len(values_data)
        values_data.foreach_get("value", buffer)
        values = {int(value) for value in buffer}
    else:
        values = {int(getattr(item, "value", item)) for item in values_data}
    positive = {value for value in values if value > 0}
    invalid = sorted(value for value in values if value <= 0)
    if invalid:
        return positive, (
            f"mesh {obj.name!r} contains invalid or untagged MaskTag "
            f"value(s) {invalid}"
        )
    return positive, None


def _label_components_for_ids(
    tag_mapping: Mapping[str, int] | None, used_ids: set[int]
) -> set[str]:
    if tag_mapping is None:
        return set()
    components = set()
    for label, value in tag_mapping.items():
        if value not in used_ids:
            continue
        components.update(part.strip().lower() for part in label.split(".") if part)
    return components


def _check(
    checks: list[dict[str, Any]],
    name: str,
    condition: bool,
    message: str,
    **details: Any,
) -> None:
    row: dict[str, Any] = {
        "name": name,
        "status": "PASS" if condition else "FAIL",
        "message": message,
    }
    if details:
        row["details"] = details
    checks.append(row)


def _objects_by_role(objects: Sequence[Any]) -> dict[str, list[Any]]:
    grouped: dict[str, list[Any]] = defaultdict(list)
    for obj in objects:
        role = _property(obj, "elevator_role")
        if isinstance(role, str) and role:
            grouped[role].append(obj)
    return grouped


def _direct_translation(obj: Any) -> tuple[float, float, float]:
    """Return transform-chain translation for unlinked placeholder objects."""

    location = getattr(obj, "location", (0.0, 0.0, 0.0))
    local = (
        _component(location, 0, "x"),
        _component(location, 1, "y"),
        _component(location, 2, "z"),
    )
    parent = getattr(obj, "parent", None)
    if parent is None:
        return local
    parent_world = _direct_translation(parent)
    return tuple(parent_world[index] + local[index] for index in range(3))


def _validate_native_landings(
    checks: list[dict[str, Any]],
    config: ElevatorConfig,
    scene_objects: Sequence[Any],
    tolerance: float,
) -> None:
    cutters = [
        obj
        for obj in scene_objects
        if bool(_property(obj, "elevator_landing_door", False))
        and _property(obj, "elevator_id") == config.elevator_id
    ]
    if not cutters:
        return
    indexed = defaultdict(list)
    for cutter in cutters:
        index = _property(cutter, "floor_index")
        if isinstance(index, int) and not isinstance(index, bool):
            indexed[index].append(cutter)
    errors = []
    ordered = sorted(indexed.items())
    expected_stops = config.ordered_stops
    if len(ordered) != len(expected_stops):
        errors.append(
            f"found {len(ordered)} native landing levels for {len(expected_stops)} stops"
        )
    for ordinal, ((floor_index, matches), stop) in enumerate(
        zip(ordered, expected_stops)
    ):
        if len(matches) != 1:
            errors.append(
                f"floor index {floor_index} has {len(matches)} native landing cutters"
            )
            continue
        cutter = matches[0]
        finished_z = _direct_translation(cutter)[2] - _dimension_z(cutter) / 2
        if not _close(finished_z, stop.stop_z, tolerance):
            errors.append(
                f"stop {ordinal} ({stop.floor_id}) native opening starts at "
                f"{finished_z}, expected finished floor {stop.stop_z}"
            )
    _check(
        checks,
        "native_landing_opening_alignment",
        not errors,
        "native landing-door openings start on the manifest finished-floor Z",
        errors=errors,
        floor_indices=[floor_index for floor_index, _ in ordered],
    )


def _validate_native_shaft_void(
    checks: list[dict[str, Any]],
    config: ElevatorConfig,
    scene_objects: Sequence[Any],
    tolerance: float,
) -> None:
    try:
        elevator_index = int(config.elevator_id.rsplit("_", 1)[1])
    except (IndexError, ValueError):
        return
    prefix = "elevator-room_"
    room_surfaces = []
    for obj in scene_objects:
        name = str(getattr(obj, "name", ""))
        if getattr(obj, "type", None) != "MESH" or not name.startswith(prefix):
            continue
        stem = name[len(prefix) :]
        if (
            f"/{elevator_index}.floor" not in stem
            and f"/{elevator_index}.ceiling" not in stem
        ):
            continue
        data = getattr(obj, "data", None)
        if data is not None and getattr(data, "vertices", None) is not None:
            room_surfaces.append(obj)
    if not room_surfaces:
        return

    try:
        from mathutils import Vector
        from mathutils.bvhtree import BVHTree

        trees = []
        for obj in room_surfaces:
            vertices = [obj.matrix_world @ vertex.co for vertex in obj.data.vertices]
            polygons = [list(polygon.vertices) for polygon in obj.data.polygons]
            if not polygons:
                continue
            trees.append(
                (
                    str(obj.name),
                    BVHTree.FromPolygons(vertices, polygons, all_triangles=False),
                )
            )
    except Exception as exc:
        _check(
            checks,
            "native_shaft_void",
            False,
            "native room floor/ceiling meshes could not be inspected",
            errors=[str(exc)],
        )
        return

    width, depth = config.shaft.inner_size
    offsets = (
        (0.0, 0.0),
        (-0.3 * width, -0.3 * depth),
        (-0.3 * width, 0.3 * depth),
        (0.3 * width, -0.3 * depth),
        (0.3 * width, 0.3 * depth),
    )
    yaw = math.radians(config.yaw_degrees)
    cosine, sine = math.cos(yaw), math.sin(yaw)
    z_start = config.shaft.z_min + tolerance
    distance = config.shaft.z_max - config.shaft.z_min - 2 * tolerance
    obstructions = []
    for local_x, local_y in offsets:
        world_x = config.origin_xy[0] + cosine * local_x - sine * local_y
        world_y = config.origin_xy[1] + sine * local_x + cosine * local_y
        origin = Vector((world_x, world_y, z_start))
        for name, tree in trees:
            hit, _normal, _index, hit_distance = tree.ray_cast(
                origin, Vector((0.0, 0.0, 1.0)), distance
            )
            if hit is not None:
                obstructions.append(
                    {
                        "object": name,
                        "sample_xy": [world_x, world_y],
                        "hit_z": float(hit.z),
                        "distance": float(hit_distance),
                    }
                )
    _check(
        checks,
        "native_shaft_void",
        not obstructions,
        "native room floor/ceiling meshes leave the car sweep unobstructed",
        sampled_surface_count=len(room_surfaces),
        obstructions=obstructions,
    )


def _validate_mode(
    checks: list[dict[str, Any]],
    root: Any,
    roles: Mapping[str, list[Any]],
    mode: str,
    expected_stops: int,
) -> None:
    _check(
        checks,
        "mode",
        mode in VALID_MODES,
        f"root elevator_mode is {mode!r}",
        allowed=sorted(VALID_MODES),
    )
    missing_control = [
        name for name in ROOT_CONTROL_PROPERTIES if _property(root, name) is None
    ]
    _check(
        checks,
        "root_control_properties",
        not missing_control,
        "root carries controller state properties",
        missing=missing_control,
    )
    _check(
        checks,
        "physical_control_nodes",
        len(roles.get("car_control_panel", ())) == 1
        and len(roles.get("landing_call_station", ())) == expected_stops,
        "scene has one car control panel and one landing call station per stop",
        car_control_panels=len(roles.get("car_control_panel", ())),
        landing_call_stations=len(roles.get("landing_call_station", ())),
        expected_landings=expected_stops,
    )
    if mode == "static":
        animated = [
            obj.name
            for role in (
                "system",
                "car",
                "car_door_panel_left",
                "car_door_panel_right",
                "landing_door_panel_left",
                "landing_door_panel_right",
            )
            for obj in roles.get(role, ())
            if _animation_curves(obj)
        ]
        _check(
            checks,
            "static_has_no_control_animation",
            not animated,
            "static elevator has no car, door, or controller animation curves",
            animated_objects=animated,
        )
    elif mode == "animated":
        start = _property(root, "elevator_animation_frame_start")
        end = _property(root, "elevator_animation_frame_end")
        duration = _property(root, "elevator_animation_duration")
        valid_range = (
            isinstance(start, (int, float))
            and not isinstance(start, bool)
            and isinstance(end, (int, float))
            and not isinstance(end, bool)
            and float(end) > float(start)
            and isinstance(duration, (int, float))
            and not isinstance(duration, bool)
            and float(duration) > 0
        )
        _check(
            checks,
            "animated_frame_range",
            valid_range,
            "animated elevator has a positive duration and frame range",
            frame_start=start,
            frame_end=end,
            duration=duration,
        )

        car = roles.get("car", ())
        animated_car = len(car) == 1 and _has_curve(car[0], "location", 2)
        door_panels = [
            obj
            for role in (
                "car_door_panel_left",
                "car_door_panel_right",
                "landing_door_panel_left",
                "landing_door_panel_right",
            )
            for obj in roles.get(role, ())
        ]
        missing_door_curves = [
            obj.name for obj in door_panels if not _has_curve(obj, "location", 0)
        ]
        missing_root_curves = [
            name for name in ANIMATED_ROOT_CURVES if not _has_curve(root, f'["{name}"]')
        ]
        _check(
            checks,
            "animated_control_curves",
            animated_car and not missing_door_curves and not missing_root_curves,
            "animated elevator keys car Z, all door X transforms, and root state",
            car_z_curve=animated_car,
            missing_door_curves=missing_door_curves,
            missing_root_curves=missing_root_curves,
        )


def _validate_one_elevator(
    config: ElevatorConfig,
    root: Any,
    *,
    tag_mapping: Mapping[str, int] | None,
    z_tolerance: float,
    expected_mode: str,
    scene_objects: Sequence[Any],
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    objects = _object_tree(root)
    roles = _objects_by_role(objects)
    ordered_stops = config.ordered_stops
    expected_stop_z = tuple(stop.stop_z for stop in ordered_stops)
    expected_level_ids = tuple(stop.floor_id for stop in ordered_stops)
    root_world = _world_translation(root)

    _check(
        checks,
        "root_identity",
        _property(root, "elevator_role") == "system"
        and _property(root, "elevator_node_path") == ""
        and _property(root, "elevator_id") == config.elevator_id,
        "root has stable system role, empty node path, and manifest elevator id",
        root_name=str(root.name),
        elevator_role=_property(root, "elevator_role"),
        elevator_node_path=_property(root, "elevator_node_path"),
        elevator_id=_property(root, "elevator_id"),
    )
    _check(
        checks,
        "root_origin_xy",
        _close(root_world[0], config.origin_xy[0], z_tolerance)
        and _close(root_world[1], config.origin_xy[1], z_tolerance),
        "root world XY matches the manifest",
        actual=list(root_world[:2]),
        expected=list(config.origin_xy),
        tolerance=z_tolerance,
    )
    _validate_native_landings(checks, config, scene_objects, z_tolerance)
    _validate_native_shaft_void(checks, config, scene_objects, z_tolerance)
    _check(
        checks,
        "root_schema_metadata",
        _property(root, "elevator_schema_version") == 1
        and _property(root, "elevator_coordinate_space") == "root_local"
        and _property(root, "elevator_stop_reference") == "finished_car_floor",
        "root declares the stable elevator schema and stop coordinate convention",
        schema_version=_property(root, "elevator_schema_version"),
        coordinate_space=_property(root, "elevator_coordinate_space"),
        stop_reference=_property(root, "elevator_stop_reference"),
    )

    role_missing = [
        str(obj.name)
        for obj in objects
        if not isinstance(_property(obj, "elevator_role"), str)
        or not _property(obj, "elevator_role")
    ]
    path_missing = [
        str(obj.name)
        for obj in objects
        if obj is not root
        and (
            not isinstance(_property(obj, "elevator_node_path"), str)
            or not _property(obj, "elevator_node_path")
        )
    ]
    paths = [
        _property(obj, "elevator_node_path")
        for obj in objects
        if isinstance(_property(obj, "elevator_node_path"), str)
    ]
    duplicate_paths = sorted(
        path for path, count in Counter(paths).items() if count > 1
    )
    _check(
        checks,
        "stable_roles_and_node_paths",
        not role_missing and not path_missing and not duplicate_paths,
        "all elevator objects have roles and unique root-relative node paths",
        missing_roles=role_missing,
        missing_paths=path_missing,
        duplicate_paths=duplicate_paths,
    )

    n_stops = len(ordered_stops)
    counts = {
        role: len(roles.get(role, ()))
        for role in (
            "car",
            "landing",
            "car_door_panel_left",
            "car_door_panel_right",
            "landing_door_panel_left",
            "landing_door_panel_right",
        )
    }
    expected_counts = {
        "car": 1,
        "landing": n_stops,
        "car_door_panel_left": 1,
        "car_door_panel_right": 1,
        "landing_door_panel_left": n_stops,
        "landing_door_panel_right": n_stops,
    }
    _check(
        checks,
        "required_role_counts",
        counts == expected_counts,
        "one car, N landings, two car panels, and two landing panels per stop",
        actual=counts,
        expected=expected_counts,
    )

    root_local_stops = _float_sequence(_property(root, "elevator_stop_z"))
    absolute_root_stops = (
        tuple(root_world[2] + stop for stop in root_local_stops)
        if root_local_stops is not None
        else ()
    )
    _check(
        checks,
        "root_stop_z",
        root_local_stops is not None
        and _sequences_close(absolute_root_stops, expected_stop_z, z_tolerance),
        "root stop_z metadata matches manifest absolute landing elevations",
        actual=list(absolute_root_stops),
        expected=list(expected_stop_z),
        tolerance=z_tolerance,
    )
    try:
        served_levels_payload = json.loads(
            _property(root, "elevator_served_levels_json", "")
        )
        if not isinstance(served_levels_payload, list):
            raise ValueError("served levels must be a JSON array")
        served_levels = tuple(str(value) for value in served_levels_payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        served_levels = ()
    _check(
        checks,
        "served_levels",
        served_levels == expected_level_ids,
        "root served-level metadata matches manifest order",
        actual=list(served_levels),
        expected=list(expected_level_ids),
    )

    landings_by_index: dict[int, list[Any]] = defaultdict(list)
    for landing in roles.get("landing", ()):
        index = _property(landing, "elevator_level_index")
        if isinstance(index, int) and not isinstance(index, bool):
            landings_by_index[index].append(landing)
    landing_errors = []
    for index, stop in enumerate(ordered_stops):
        matches = landings_by_index.get(index, ())
        if len(matches) != 1:
            landing_errors.append(
                f"stop {index} expected one landing, found {len(matches)}"
            )
            continue
        landing = matches[0]
        actual_world_z = _world_translation(landing)[2]
        metadata_z = _property(landing, "elevator_stop_z")
        level_id = str(_property(landing, "elevator_level_id", ""))
        if not (
            isinstance(metadata_z, (int, float))
            and not isinstance(metadata_z, bool)
            and _close(float(metadata_z) + root_world[2], stop.stop_z, z_tolerance)
            and _close(actual_world_z, stop.stop_z, z_tolerance)
            and level_id == stop.floor_id
        ):
            landing_errors.append(
                f"stop {index} ({stop.floor_id}) has world_z={actual_world_z!r}, "
                f"metadata_z={metadata_z!r}, level_id={level_id!r}; expected "
                f"stop_z={stop.stop_z!r}"
            )
    _check(
        checks,
        "landing_stop_alignment",
        not landing_errors and set(landings_by_index) == set(range(n_stops)),
        "each indexed landing matches its manifest floor id and stop_z",
        errors=landing_errors,
        indices=sorted(landings_by_index),
    )

    panel_index_errors = []
    for role in ("landing_door_panel_left", "landing_door_panel_right"):
        indices = [
            _property(panel, "elevator_level_index") for panel in roles.get(role, ())
        ]
        valid_indices = all(
            isinstance(index, int) and not isinstance(index, bool) for index in indices
        )
        if not valid_indices or sorted(indices) != list(range(n_stops)):
            panel_index_errors.append(f"{role} indices are {indices!r}")
    _check(
        checks,
        "landing_panel_indices",
        not panel_index_errors,
        "left and right landing panels each cover exactly the served stops",
        errors=panel_index_errors,
    )

    bottom_slabs = roles.get("shaft_slab_bottom", ())
    top_slabs = roles.get("shaft_slab_top", ())
    actual_bottom = None
    actual_top = None
    if len(bottom_slabs) == 1:
        actual_bottom = (
            _world_translation(bottom_slabs[0])[2] + _dimension_z(bottom_slabs[0]) / 2
        )
    if len(top_slabs) == 1:
        actual_top = (
            _world_translation(top_slabs[0])[2] - _dimension_z(top_slabs[0]) / 2
        )
    shaft_ok = (
        actual_bottom is not None
        and actual_top is not None
        and _close(actual_bottom, config.shaft.z_min, z_tolerance)
        and _close(actual_top, config.shaft.z_max, z_tolerance)
    )
    _check(
        checks,
        "shaft_bounds",
        shaft_ok,
        "inner faces of the unique shaft bottom/top slabs match manifest bounds",
        bottom_slab_count=len(bottom_slabs),
        top_slab_count=len(top_slabs),
        actual_bottom=actual_bottom,
        expected_bottom=config.shaft.z_min,
        actual_top=actual_top,
        expected_top=config.shaft.z_max,
        tolerance=z_tolerance,
    )

    mode = str(_property(root, "elevator_mode", ""))
    if expected_mode != "auto":
        _check(
            checks,
            "expected_mode",
            mode == expected_mode,
            "root mode matches the requested validator mode",
            actual=mode,
            expected=expected_mode,
        )
    _validate_mode(checks, root, roles, mode, n_stops)

    mesh_objects = [obj for obj in objects if getattr(obj, "type", None) == "MESH"]
    used_mask_ids: set[int] = set()
    mask_errors = []
    for obj in mesh_objects:
        values, error = _mask_values(obj)
        used_mask_ids.update(values)
        if error is not None:
            mask_errors.append(error)
    _check(
        checks,
        "mesh_masktag",
        bool(mesh_objects) and not mask_errors,
        "every elevator mesh has a nonzero FACE-domain MaskTag",
        mesh_count=len(mesh_objects),
        errors=mask_errors,
    )
    used_labels = _label_components_for_ids(tag_mapping, used_mask_ids)
    missing_labels = sorted(REQUIRED_ELEVATOR_LABELS.difference(used_labels))
    _check(
        checks,
        "elevator_semantic_labels",
        tag_mapping is not None and not missing_labels,
        "MaskTag ids used by elevator meshes resolve to required elevator labels",
        missing_labels=missing_labels,
        used_elevator_labels=sorted(
            label for label in used_labels if "elevator" in label
        ),
    )

    failures = [check for check in checks if check["status"] == "FAIL"]
    return {
        "elevator_id": config.elevator_id,
        "root_name": str(root.name),
        "status": "FAIL" if failures else "PASS",
        "expected_stops": n_stops,
        "object_count": len(objects),
        "checks": checks,
    }


def validate_scene_objects(
    manifest: ElevatorManifest,
    objects: Sequence[Any],
    *,
    tag_mapping: Mapping[str, int] | None,
    z_tolerance: float = 1e-4,
    expected_mode: str = "auto",
) -> dict[str, Any]:
    """Validate already-opened Blender-like objects without mutating them."""

    if not isinstance(manifest, ElevatorManifest):
        raise TypeError("manifest must be an ElevatorManifest")
    if not math.isfinite(z_tolerance) or z_tolerance <= 0:
        raise ValueError("z_tolerance must be finite and > 0")
    if expected_mode not in {*VALID_MODES, "auto"}:
        raise ValueError("expected_mode must be auto, static, or animated")

    roots = [obj for obj in objects if _property(obj, "elevator_role") == "system"]
    roots_by_id: dict[str, list[Any]] = defaultdict(list)
    roots_without_id = []
    for root in roots:
        elevator_id = _property(root, "elevator_id")
        if isinstance(elevator_id, str) and elevator_id:
            roots_by_id[elevator_id].append(root)
        else:
            roots_without_id.append(str(root.name))

    manifest_ids = {config.elevator_id for config in manifest.elevators}
    global_errors = []
    if len(roots) != len(manifest.elevators):
        global_errors.append(
            f"expected {len(manifest.elevators)} elevator roots, found {len(roots)}"
        )
    if roots_without_id:
        global_errors.append(
            f"elevator roots missing elevator_id: {sorted(roots_without_id)}"
        )
    extra_ids = sorted(set(roots_by_id).difference(manifest_ids))
    if extra_ids:
        global_errors.append(
            f"scene contains elevator ids absent from manifest: {extra_ids}"
        )
    reachable_ids = {
        id(descendant) for root in roots for descendant in _object_tree(root)
    }
    orphan_names = sorted(
        str(obj.name)
        for obj in objects
        if isinstance(_property(obj, "elevator_role"), str)
        and _property(obj, "elevator_role")
        and id(obj) not in reachable_ids
    )
    if orphan_names:
        global_errors.append(
            "elevator-role objects are not parented below a system root: "
            f"{orphan_names}"
        )

    elevator_reports = []
    for config in manifest.elevators:
        matches = roots_by_id.get(config.elevator_id, ())
        if len(matches) != 1:
            global_errors.append(
                f"manifest elevator {config.elevator_id!r} expected one root, "
                f"found {len(matches)}"
            )
            elevator_reports.append(
                {
                    "elevator_id": config.elevator_id,
                    "root_name": None,
                    "status": "FAIL",
                    "expected_stops": len(config.served_floors),
                    "object_count": 0,
                    "checks": [
                        {
                            "name": "unique_root",
                            "status": "FAIL",
                            "message": f"expected exactly one root, found {len(matches)}",
                        }
                    ],
                }
            )
            continue
        elevator_reports.append(
            _validate_one_elevator(
                config,
                matches[0],
                tag_mapping=tag_mapping,
                z_tolerance=z_tolerance,
                expected_mode=expected_mode,
                scene_objects=objects,
            )
        )

    failed_checks = sum(
        check["status"] == "FAIL"
        for elevator in elevator_reports
        for check in elevator["checks"]
    )
    passed_checks = sum(
        check["status"] == "PASS"
        for elevator in elevator_reports
        for check in elevator["checks"]
    )
    status = (
        "PASS"
        if not global_errors
        and all(elevator["status"] == "PASS" for elevator in elevator_reports)
        else "FAIL"
    )
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "tool": "validate_elevator_scene",
        "status": status,
        "summary": {
            "manifest_elevator_count": len(manifest.elevators),
            "scene_elevator_root_count": len(roots),
            "passed_check_count": passed_checks,
            "failed_check_count": failed_checks,
            "global_error_count": len(global_errors),
        },
        "global_errors": global_errors,
        "elevators": elevator_reports,
    }


def open_blend_objects(path: str | Path) -> tuple[Any, ...]:
    """Open a Blender file for inspection and return all objects without saving."""

    path = Path(path)
    try:
        import bpy
    except ImportError as exc:
        raise SceneValidationError(
            "Blender's bpy module is required to inspect a .blend file. Run the "
            "tool with the Infinigen Blender/conda Python environment."
        ) from exc
    try:
        with _silence_native_stdout():
            bpy.ops.wm.open_mainfile(filepath=str(path.resolve()))
            bpy.context.view_layer.update()
    except Exception as exc:
        raise SceneValidationError(
            f"could not open Blender scene {path}: {exc}"
        ) from exc
    return tuple(bpy.data.objects)


def _read_tag_mapping(path: Path) -> dict[str, int]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SceneValidationError(
            f"could not read MaskTag mapping {path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise SceneValidationError(f"MaskTag mapping {path} must be a JSON object")
    result = {}
    ids_to_labels: dict[int, str] = {}
    for label, value in payload.items():
        if (
            not isinstance(label, str)
            or isinstance(value, bool)
            or not isinstance(value, int)
            or value <= 0
        ):
            raise SceneValidationError(
                f"MaskTag mapping {path} has invalid entry {label!r}: {value!r}"
            )
        if value in ids_to_labels:
            raise SceneValidationError(
                f"MaskTag mapping {path} assigns id {value} to both "
                f"{ids_to_labels[value]!r} and {label!r}"
            )
        result[label] = value
        ids_to_labels[value] = label
    return result


def discover_tag_mapping(
    blend_path: Path, manifest_path: Path, explicit_path: Path | None
) -> tuple[dict[str, int] | None, Path | None]:
    if explicit_path is not None and not explicit_path.is_file():
        raise SceneValidationError(
            f"explicit MaskTag mapping does not exist: {explicit_path}"
        )
    candidates = []
    if explicit_path is not None:
        candidates.append(explicit_path)
    candidates.extend(
        [manifest_path.parent / "MaskTag.json", blend_path.parent / "MaskTag.json"]
    )
    seen = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if candidate.is_file():
            return _read_tag_mapping(candidate), candidate
    return None, None


def _emit_report(report: Mapping[str, Any], output_path: Path | None) -> None:
    text = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    sys.stdout.write(text)
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Open a Blender scene read-only and validate its elevator hierarchy, "
            "stops, shaft bounds, animation controls, and semantic MaskTags."
        )
    )
    parser.add_argument("--blend", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--masktag-json", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--mode", choices=("auto", "static", "animated"), default="auto"
    )
    parser.add_argument("--z-tolerance", type=float, default=1e-4)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    protected_paths = [args.blend, args.manifest]
    if args.masktag_json is not None:
        protected_paths.append(args.masktag_json)
    if args.output is not None and args.output.resolve() in {
        path.resolve() for path in protected_paths
    }:
        report = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "tool": "validate_elevator_scene",
            "status": "FAIL",
            "fatal": True,
            "errors": ["--output must not overwrite an input file"],
            "blend_path": str(args.blend),
            "manifest_path": str(args.manifest),
        }
        _emit_report(report, None)
        return 2
    try:
        if not args.blend.is_file() or args.blend.suffix.lower() != ".blend":
            raise SceneValidationError(f"blend input does not exist: {args.blend}")
        if not args.manifest.is_file():
            raise SceneValidationError(
                f"elevator manifest does not exist: {args.manifest}"
            )
        manifest = read_manifest(args.manifest)
        tag_mapping, tag_path = discover_tag_mapping(
            args.blend, args.manifest, args.masktag_json
        )
        objects = open_blend_objects(args.blend)
        report = validate_scene_objects(
            manifest,
            objects,
            tag_mapping=tag_mapping,
            z_tolerance=args.z_tolerance,
            expected_mode=args.mode,
        )
        report["blend_path"] = str(args.blend.resolve())
        report["manifest_path"] = str(args.manifest.resolve())
        report["masktag_path"] = None if tag_path is None else str(tag_path.resolve())
    except (
        ManifestValidationError,
        SceneValidationError,
        FileNotFoundError,
        OSError,
        TypeError,
        ValueError,
    ) as exc:
        report = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "tool": "validate_elevator_scene",
            "status": "FAIL",
            "fatal": True,
            "errors": [str(exc)],
            "blend_path": str(args.blend),
            "manifest_path": str(args.manifest),
        }
        _emit_report(report, args.output)
        return 2

    _emit_report(report, args.output)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
