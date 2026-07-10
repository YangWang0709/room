# Copyright (C) 2026, Princeton University.
# This source code is licensed under the BSD 3-Clause license found in the
# LICENSE file in the root directory of this source tree.

"""Blender geometry and keyframe builder for the isolated elevator asset.

The generated object tree is intentionally simple and stable.  Every visible
piece is a primitive child of a semantic EMPTY, which makes it straightforward
to replace visual meshes later without changing animation targets or metadata.
No room-solver, navigation, USD, or scene-composition code is imported here.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Iterable

import bpy

from infinigen.core.placement.factory import AssetFactory
from infinigen.core.util import blender as butil
from infinigen.core.util.math import int_hash

from .model import (
    ElevatorAnimationPlan,
    ElevatorBuildMode,
    ElevatorController,
    ElevatorPhase,
    ElevatorSnapshot,
    ElevatorSpec,
    ElevatorTiming,
    ElevatorVisualVariant,
    LevelId,
    build_animation_plan,
    sample_visual_variant,
)

ELEVATOR_SCHEMA_VERSION = 1
DEFAULT_COLLECTION = "unique_assets:elevators"


@dataclass
class BlenderElevatorAsset:
    """References to stable animation and semantic nodes in one built asset."""

    root: bpy.types.Object
    shaft_root: bpy.types.Object
    shaft_structure_root: bpy.types.Object
    landings_root: bpy.types.Object
    landing_roots: dict[LevelId, bpy.types.Object]
    landing_door_roots: dict[LevelId, bpy.types.Object]
    landing_door_panels: dict[LevelId, tuple[bpy.types.Object, bpy.types.Object]]
    car_root: bpy.types.Object
    cabin_root: bpy.types.Object
    car_door_root: bpy.types.Object
    car_door_panels: tuple[bpy.types.Object, bpy.types.Object]
    spec: ElevatorSpec
    variant: ElevatorVisualVariant
    materials: tuple[bpy.types.Material, ...]
    animation_plan: ElevatorAnimationPlan | None = None

    def all_objects(self) -> tuple[bpy.types.Object, ...]:
        result = []
        queue = [self.root]
        while queue:
            obj = queue.pop(0)
            result.append(obj)
            queue.extend(sorted(obj.children, key=lambda child: child.name))
        return tuple(result)

    def object_by_path(self, node_path: str) -> bpy.types.Object:
        """Resolve a hierarchy-relative path which survives root renaming."""

        matches = [
            obj
            for obj in self.all_objects()
            if obj.get("elevator_node_path") == node_path
        ]
        if len(matches) != 1:
            raise KeyError(
                f"expected one elevator object at {node_path!r}, found {len(matches)}"
            )
        return matches[0]


def _safe_token(value: object) -> str:
    token = re.sub(r"[^0-9A-Za-z_-]+", "_", str(value)).strip("_")
    return token or "level"


class _Builder:
    def __init__(
        self,
        spec: ElevatorSpec,
        seed: int,
        name: str,
        collection_name: str,
    ) -> None:
        self.spec = spec
        self.seed = int(seed)
        self.variant = sample_visual_variant(spec, seed)
        self.collection = butil.get_collection(collection_name)
        self.root = butil.spawn_empty(name, disp_type="CUBE", s=0.25)
        butil.put_in_collection(self.root, self.collection)
        self.prefix = self.root.name
        self.materials = self._create_materials()

        self.root["elevator_role"] = "system"
        self.root["elevator_node_path"] = ""
        self.root["elevator_schema_version"] = ELEVATOR_SCHEMA_VERSION
        # Blender integer ID properties are signed 32-bit values, while
        # Infinigen's int_hash spans the full uint32 range.  Decimal text keeps
        # the exact seed round-trippable for either direct or factory builds.
        self.root["elevator_seed"] = str(self.seed)
        self.root["elevator_coordinate_space"] = "root_local"
        self.root["elevator_stop_reference"] = "finished_car_floor"
        self.root["elevator_spec_json"] = json.dumps(asdict(spec), sort_keys=True)
        self.root["elevator_served_levels_json"] = json.dumps(spec.served_levels)
        self.root["elevator_stop_z"] = list(spec.stop_z)

    def _create_material(
        self,
        suffix: str,
        color: tuple[float, float, float],
        *,
        metallic: float = 0.0,
        roughness: float = 0.5,
    ) -> bpy.types.Material:
        material = bpy.data.materials.new(f"{self.prefix}.Material.{suffix}")
        material.diffuse_color = (*color, 1.0)
        material.metallic = metallic
        material.roughness = roughness
        return material

    def _create_materials(self) -> tuple[bpy.types.Material, ...]:
        return (
            self._create_material("Shaft", (0.16, 0.17, 0.18), roughness=0.82),
            self._create_material(
                "Cabin", (0.52, 0.55, 0.58), metallic=0.65, roughness=0.28
            ),
            self._create_material(
                "Doors", (0.34, 0.37, 0.40), metallic=0.8, roughness=0.22
            ),
            self._create_material(
                "Accent", self.variant.accent_rgb, metallic=0.3, roughness=0.35
            ),
            self._create_material("Threshold", (0.08, 0.08, 0.08), roughness=0.7),
        )

    @property
    def shaft_material(self) -> bpy.types.Material:
        return self.materials[0]

    @property
    def cabin_material(self) -> bpy.types.Material:
        return self.materials[1]

    @property
    def door_material(self) -> bpy.types.Material:
        return self.materials[2]

    @property
    def accent_material(self) -> bpy.types.Material:
        return self.materials[3]

    @property
    def threshold_material(self) -> bpy.types.Material:
        return self.materials[4]

    def empty(
        self,
        suffix: str,
        parent: bpy.types.Object,
        role: str,
        location=(0.0, 0.0, 0.0),
    ) -> bpy.types.Object:
        obj = butil.spawn_empty(f"{self.prefix}.{suffix}")
        butil.put_in_collection(obj, self.collection)
        obj.parent = parent
        obj.location = location
        obj["elevator_role"] = role
        obj["elevator_node_path"] = suffix
        return obj

    def box(
        self,
        suffix: str,
        parent: bpy.types.Object,
        role: str,
        dimensions: tuple[float, float, float],
        location: tuple[float, float, float],
        material: bpy.types.Material,
    ) -> bpy.types.Object:
        obj = butil.spawn_cube(size=1, name=f"{self.prefix}.{suffix}")
        obj.dimensions = dimensions
        butil.apply_transform(obj, scale=True)
        butil.put_in_collection(obj, self.collection)
        obj.parent = parent
        obj.location = location
        obj["elevator_role"] = role
        obj["elevator_node_path"] = suffix
        obj.data.materials.append(material)
        return obj

    def build_shaft(self):
        spec = self.spec
        shaft = self.empty("Shaft", self.root, "shaft")
        structure = self.empty("Shaft.Structure", shaft, "shaft_structure")
        landings = self.empty("Shaft.Landings", shaft, "landings")

        wall_t = spec.shaft_wall_thickness
        height = spec.shaft_height
        center_z = (spec.shaft_bottom_z + spec.shaft_top_z) / 2
        outer_width = spec.shaft_width + 2 * wall_t
        outer_depth = spec.shaft_depth + 2 * wall_t

        self.box(
            "Shaft.Structure.Wall.Left",
            structure,
            "shaft_wall_left",
            (wall_t, outer_depth, height),
            (-spec.shaft_width / 2 - wall_t / 2, 0.0, center_z),
            self.shaft_material,
        )
        self.box(
            "Shaft.Structure.Wall.Right",
            structure,
            "shaft_wall_right",
            (wall_t, outer_depth, height),
            (spec.shaft_width / 2 + wall_t / 2, 0.0, center_z),
            self.shaft_material,
        )
        self.box(
            "Shaft.Structure.Wall.Back",
            structure,
            "shaft_wall_back",
            (outer_width, wall_t, height),
            (0.0, spec.shaft_depth / 2 + wall_t / 2, center_z),
            self.shaft_material,
        )
        self.box(
            "Shaft.Structure.Slab.Bottom",
            structure,
            "shaft_slab_bottom",
            (outer_width, outer_depth, wall_t),
            (0.0, 0.0, spec.shaft_bottom_z - wall_t / 2),
            self.shaft_material,
        )
        self.box(
            "Shaft.Structure.Slab.Top",
            structure,
            "shaft_slab_top",
            (outer_width, outer_depth, wall_t),
            (0.0, 0.0, spec.shaft_top_z + wall_t / 2),
            self.shaft_material,
        )
        return shaft, structure, landings

    def build_landings(self, landings_root: bpy.types.Object):
        spec = self.spec
        landing_roots = {}
        door_roots = {}
        panels = {}
        front_y = -spec.shaft_depth / 2
        jamb_width = (spec.shaft_width - spec.door_width) / 2
        frame_depth = spec.landing_frame_depth
        panel_width = spec.door_width / 2

        for index, (level, stop_z, station_side) in enumerate(
            zip(
                spec.served_levels,
                spec.stop_z,
                self.variant.landing_station_sides,
            )
        ):
            token = f"{index:03d}_{_safe_token(level)}"
            landing = self.empty(
                f"Shaft.Landings.Landing.{token}",
                landings_root,
                "landing",
                location=(0.0, 0.0, stop_z),
            )
            landing["elevator_level_index"] = index
            landing["elevator_level_id"] = str(level)
            landing["elevator_stop_z"] = stop_z
            landing_roots[level] = landing

            frame = self.empty(
                f"Shaft.Landings.Landing.{token}.Frame",
                landing,
                "landing_frame",
            )
            for side, label in ((-1, "Left"), (1, "Right")):
                self.box(
                    f"Shaft.Landings.Landing.{token}.Frame.Jamb.{label}",
                    frame,
                    f"landing_frame_jamb_{label.lower()}",
                    (jamb_width, frame_depth, spec.door_height),
                    (
                        side * (spec.door_width / 2 + jamb_width / 2),
                        front_y - frame_depth / 2,
                        spec.door_height / 2,
                    ),
                    self.shaft_material,
                )
            self.box(
                f"Shaft.Landings.Landing.{token}.Frame.Header",
                frame,
                "landing_frame_header",
                (spec.shaft_width, frame_depth, spec.landing_frame_width),
                (
                    0.0,
                    front_y - frame_depth / 2,
                    spec.door_height + spec.landing_frame_width / 2,
                ),
                self.shaft_material,
            )
            self.box(
                f"Shaft.Landings.Landing.{token}.Threshold",
                landing,
                "landing_threshold",
                (spec.door_width, spec.running_clearance * 2, spec.door_thickness),
                (
                    0.0,
                    front_y,
                    -spec.door_thickness / 2,
                ),
                self.threshold_material,
            )

            door_root = self.empty(
                f"Shaft.Landings.Landing.{token}.Door",
                landing,
                "landing_door",
            )
            door_root["elevator_level_index"] = index
            door_roots[level] = door_root
            left = self.box(
                f"Shaft.Landings.Landing.{token}.Door.Panel.Left",
                door_root,
                "landing_door_panel_left",
                (panel_width, spec.door_thickness, spec.door_height),
                (
                    -spec.door_width / 4,
                    front_y - frame_depth - spec.door_thickness / 2,
                    spec.door_height / 2,
                ),
                self.door_material,
            )
            right = self.box(
                f"Shaft.Landings.Landing.{token}.Door.Panel.Right",
                door_root,
                "landing_door_panel_right",
                (panel_width, spec.door_thickness, spec.door_height),
                (
                    spec.door_width / 4,
                    front_y - frame_depth - spec.door_thickness / 2,
                    spec.door_height / 2,
                ),
                self.door_material,
            )
            left["elevator_level_index"] = index
            right["elevator_level_index"] = index
            panels[level] = (left, right)

            station_x = station_side * (
                spec.door_width / 2 + max(jamb_width * 0.45, 0.10)
            )
            station = self.box(
                f"Shaft.Landings.Landing.{token}.CallStation",
                landing,
                "landing_call_station",
                (0.09, 0.035, 0.18),
                (
                    station_x,
                    front_y - frame_depth - 0.02,
                    spec.door_height * 0.52,
                ),
                self.accent_material,
            )
            station["elevator_station_side"] = station_side
            station["elevator_level_index"] = index

        return landing_roots, door_roots, panels

    def build_car(self):
        spec = self.spec
        car = self.empty("Car", self.root, "car")
        cabin = self.empty("Car.Cabin", car, "cabin")
        panel_t = spec.car_panel_thickness

        self.box(
            "Car.Cabin.Floor",
            cabin,
            "car_floor",
            (spec.car_width, spec.car_depth, panel_t),
            (0.0, 0.0, -panel_t / 2),
            self.threshold_material,
        )
        self.box(
            "Car.Cabin.Ceiling",
            cabin,
            "car_ceiling",
            (spec.car_width, spec.car_depth, panel_t),
            (0.0, 0.0, spec.car_height - panel_t / 2),
            self.cabin_material,
        )
        self.box(
            "Car.Cabin.Wall.Back",
            cabin,
            "car_wall_back",
            (spec.car_width - 2 * panel_t, panel_t, spec.car_height),
            (0.0, spec.car_depth / 2 - panel_t / 2, spec.car_height / 2),
            self.cabin_material,
        )
        self.box(
            "Car.Cabin.Wall.Left",
            cabin,
            "car_wall_left",
            (panel_t, spec.car_depth, spec.car_height),
            (-spec.car_width / 2 + panel_t / 2, 0.0, spec.car_height / 2),
            self.cabin_material,
        )
        self.box(
            "Car.Cabin.Wall.Right",
            cabin,
            "car_wall_right",
            (panel_t, spec.car_depth, spec.car_height),
            (spec.car_width / 2 - panel_t / 2, 0.0, spec.car_height / 2),
            self.cabin_material,
        )
        self.box(
            "Car.Cabin.ControlPanel",
            cabin,
            "car_control_panel",
            (0.035, 0.22, 0.62),
            (
                spec.car_width / 2 - panel_t - 0.02,
                -spec.car_depth * 0.18,
                spec.car_height * 0.48,
            ),
            self.accent_material,
        )

        door_root = self.empty("Car.Door", car, "car_door")
        panel_width = spec.door_width / 2
        front_y = -spec.car_depth / 2 - spec.door_thickness / 2
        left = self.box(
            "Car.Door.Panel.Left",
            door_root,
            "car_door_panel_left",
            (panel_width, spec.door_thickness, spec.door_height),
            (-spec.door_width / 4, front_y, spec.door_height / 2),
            self.door_material,
        )
        right = self.box(
            "Car.Door.Panel.Right",
            door_root,
            "car_door_panel_right",
            (panel_width, spec.door_thickness, spec.door_height),
            (spec.door_width / 4, front_y, spec.door_height / 2),
            self.door_material,
        )
        return car, cabin, door_root, (left, right)


def _door_panel_x(spec: ElevatorSpec, fraction: float) -> tuple[float, float]:
    travel = fraction * spec.door_width / 2
    return -spec.door_width / 4 - travel, spec.door_width / 4 + travel


def apply_elevator_snapshot(
    asset: BlenderElevatorAsset, snapshot: ElevatorSnapshot
) -> None:
    """Apply one controller snapshot without inserting any keyframes."""

    asset.car_root.location.z = snapshot.car_z
    left_x, right_x = _door_panel_x(asset.spec, snapshot.car_door_fraction)
    asset.car_door_panels[0].location.x = left_x
    asset.car_door_panels[1].location.x = right_x
    for level, (left, right) in asset.landing_door_panels.items():
        fraction = snapshot.landing_door_fraction(level)
        left.location.x, right.location.x = _door_panel_x(asset.spec, fraction)

    root = asset.root
    root["elevator_phase"] = snapshot.phase.value
    root["elevator_phase_code"] = list(ElevatorPhase).index(snapshot.phase)
    root["elevator_current_stop_index"] = (
        -1
        if snapshot.current_level is None
        else asset.spec.level_index(snapshot.current_level)
    )
    root["elevator_target_stop_index"] = (
        -1
        if snapshot.target_level is None
        else asset.spec.level_index(snapshot.target_level)
    )
    root["elevator_car_z"] = snapshot.car_z
    root["elevator_velocity"] = snapshot.velocity
    root["elevator_door_fraction"] = snapshot.car_door_fraction


def _set_curve_interpolation(obj: bpy.types.Object, interpolation: str) -> None:
    animation_data = obj.animation_data
    if animation_data is None or animation_data.action is None:
        return
    for curve in animation_data.action.fcurves:
        for keyframe in curve.keyframe_points:
            keyframe.interpolation = interpolation


def animate_elevator_asset(
    asset: BlenderElevatorAsset,
    plan: ElevatorAnimationPlan,
    *,
    fps: float = 24.0,
    frame_start: int = 1,
) -> None:
    """Insert car, linked door, and state metadata keyframes from a safe plan."""

    if fps <= 0:
        raise ValueError(f"fps must be > 0, got {fps}")
    animated_transform_objects = [asset.car_root, *asset.car_door_panels]
    for landing_panels in asset.landing_door_panels.values():
        animated_transform_objects.extend(landing_panels)

    final_frame = frame_start
    for snapshot in plan.snapshots:
        apply_elevator_snapshot(asset, snapshot)
        frame = frame_start + int(round(snapshot.time_s * fps))
        final_frame = max(final_frame, frame)
        asset.car_root.keyframe_insert(data_path="location", frame=frame)
        for panel in asset.car_door_panels:
            panel.keyframe_insert(data_path="location", frame=frame)
        for panels in asset.landing_door_panels.values():
            for panel in panels:
                panel.keyframe_insert(data_path="location", frame=frame)

        for property_name in (
            "elevator_phase_code",
            "elevator_current_stop_index",
            "elevator_target_stop_index",
            "elevator_car_z",
            "elevator_velocity",
            "elevator_door_fraction",
        ):
            asset.root.keyframe_insert(data_path=f'["{property_name}"]', frame=frame)

    for obj in animated_transform_objects:
        _set_curve_interpolation(obj, "LINEAR")
    _set_curve_interpolation(asset.root, "CONSTANT")
    asset.root["elevator_animation_duration"] = plan.duration
    asset.root["elevator_animation_frame_start"] = frame_start
    asset.root["elevator_animation_frame_end"] = final_frame
    asset.animation_plan = plan

    bpy.context.scene.frame_start = min(bpy.context.scene.frame_start, frame_start)
    bpy.context.scene.frame_end = max(bpy.context.scene.frame_end, final_frame)
    bpy.context.scene.frame_set(frame_start)


def build_elevator_asset(
    spec: ElevatorSpec,
    *,
    seed: int = 0,
    name: str = "ElevatorSystem",
    mode: ElevatorBuildMode | str = ElevatorBuildMode.STATIC,
    initial_level: LevelId | None = None,
    static_doors_open: bool = False,
    animation_requests: Iterable[LevelId] = (),
    timing: ElevatorTiming | None = None,
    fps: float = 24.0,
    frame_start: int = 1,
    collection_name: str = DEFAULT_COLLECTION,
) -> BlenderElevatorAsset:
    """Build a standalone static or keyframed elevator in the current scene."""

    mode = ElevatorBuildMode(mode)
    timing = timing or ElevatorTiming()
    if initial_level is None:
        initial_level = spec.served_levels[0]
    spec.level_index(initial_level)
    animation_requests = tuple(animation_requests)
    for level in animation_requests:
        spec.level_index(level)
    if fps <= 0:
        raise ValueError(f"fps must be > 0, got {fps}")

    builder = _Builder(spec, seed, name, collection_name)
    shaft, structure, landings = builder.build_shaft()
    landing_roots, landing_door_roots, landing_panels = builder.build_landings(landings)
    car, cabin, car_door_root, car_panels = builder.build_car()
    asset = BlenderElevatorAsset(
        root=builder.root,
        shaft_root=shaft,
        shaft_structure_root=structure,
        landings_root=landings,
        landing_roots=landing_roots,
        landing_door_roots=landing_door_roots,
        landing_door_panels=landing_panels,
        car_root=car,
        cabin_root=cabin,
        car_door_root=car_door_root,
        car_door_panels=car_panels,
        spec=spec,
        variant=builder.variant,
        materials=builder.materials,
    )
    asset.root["elevator_mode"] = mode.value

    if mode == ElevatorBuildMode.STATIC:
        controller = ElevatorController(
            spec, initial_level=initial_level, timing=timing, seed=seed
        )
        if static_doors_open:
            controller.open_doors()
            controller.step(timing.door_open_time)
        apply_elevator_snapshot(asset, controller.snapshot())
    else:
        plan = build_animation_plan(
            spec,
            animation_requests,
            initial_level=initial_level,
            timing=timing,
            sample_period=1 / fps,
            seed=seed,
        )
        animate_elevator_asset(asset, plan, fps=fps, frame_start=frame_start)

    return asset


def build_elevator_smoke(
    *,
    n_stops: int = 4,
    floor_height: float = 3.0,
    seed: int = 0,
    animated: bool = False,
    name: str = "ElevatorSmoke",
) -> BlenderElevatorAsset:
    """Small Blender-facing smoke interface requiring no room-scene context."""

    levels = tuple(f"L{i}" for i in range(n_stops))
    spec = ElevatorSpec.evenly_spaced(
        n_stops=n_stops,
        floor_height=floor_height,
        served_levels=levels,
    )
    requests = (levels[-1], levels[0]) if animated and n_stops > 1 else ()
    return build_elevator_asset(
        spec,
        seed=seed,
        name=name,
        mode=(ElevatorBuildMode.ANIMATED if animated else ElevatorBuildMode.STATIC),
        animation_requests=requests,
    )


class ElevatorFactory(AssetFactory):
    """AssetFactory wrapper around :func:`build_elevator_asset`.

    The returned asset root is an EMPTY with a stable child hierarchy.  This
    factory is intentionally not registered with the indoor constraint solver.
    """

    def __init__(
        self,
        factory_seed=None,
        coarse=False,
        *,
        spec: ElevatorSpec | None = None,
        mode: ElevatorBuildMode | str = ElevatorBuildMode.STATIC,
        initial_level: LevelId | None = None,
        static_doors_open: bool = False,
        animation_requests: Iterable[LevelId] = (),
        timing: ElevatorTiming | None = None,
        fps: float = 24.0,
        frame_start: int = 1,
        collection_name: str = DEFAULT_COLLECTION,
    ) -> None:
        super().__init__(factory_seed=factory_seed, coarse=coarse)
        self.spec = spec or ElevatorSpec.evenly_spaced(4)
        self.mode = ElevatorBuildMode(mode)
        self.initial_level = initial_level
        self.static_doors_open = bool(static_doors_open)
        self.animation_requests = tuple(animation_requests)
        self.timing = timing or ElevatorTiming()
        self.fps = float(fps)
        self.frame_start = int(frame_start)
        self.collection_name = collection_name
        self.last_build: BlenderElevatorAsset | None = None

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        spec = self.spec
        wall_t = spec.shaft_wall_thickness
        center_z = (spec.shaft_bottom_z + spec.shaft_top_z) / 2
        placeholder = butil.spawn_cube(size=1)
        placeholder.dimensions = (
            spec.shaft_width + 2 * wall_t,
            spec.shaft_depth + 2 * wall_t,
            spec.shaft_height,
        )
        placeholder.location.z = center_z
        butil.apply_transform(placeholder, loc=True, scale=True)
        placeholder.display_type = "WIRE"
        placeholder["elevator_role"] = "placeholder"
        return placeholder

    def create_asset(self, i=0, **params) -> bpy.types.Object:
        instance_seed = int_hash((self.factory_seed, int(i)))
        self.last_build = build_elevator_asset(
            self.spec,
            seed=instance_seed,
            # AssetFactory.spawn_asset assigns this same final name after this
            # method returns.  Building with it up front keeps all descendant
            # names under the same stable prefix.
            name=f"{repr(self)}.spawn_asset({i})",
            mode=self.mode,
            initial_level=self.initial_level,
            static_doors_open=self.static_doors_open,
            animation_requests=self.animation_requests,
            timing=self.timing,
            fps=self.fps,
            frame_start=self.frame_start,
            collection_name=self.collection_name,
        )
        return self.last_build.root


__all__ = [
    "BlenderElevatorAsset",
    "DEFAULT_COLLECTION",
    "ELEVATOR_SCHEMA_VERSION",
    "ElevatorFactory",
    "animate_elevator_asset",
    "apply_elevator_snapshot",
    "build_elevator_asset",
    "build_elevator_smoke",
]
