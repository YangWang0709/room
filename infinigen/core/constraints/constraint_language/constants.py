# Copyright (C) 2024, Princeton University.
# This source code is licensed under the BSD 3-Clause license found in the LICENSE file in the root directory of this source tree.

# Authors:
# - Lingjie Mei

import gin
import numpy as np
import shapely
from shapely.ops import orient

from infinigen.assets.utils.shapes import (
    is_valid_polygon,
    segment_filter,
    simplify_polygon,
)
from infinigen.core import tags as t
from infinigen.core.constraints.constraint_language.levels import BuildingLevels
from infinigen.core.util.random import random_general as rg


@gin.configurable
class RoomConstants:
    def __init__(
        self,
        n_stories=("cat", 0.0, 0.5, 0.4, 0.1),
        room_type=None,
        aspect_ratio_range=(0.7, 1.0),
        fixed_contour=("bool", 0.5),
        min_rooms_per_floor=None,
        max_rooms_per_floor=None,
        building_levels=None,
        elevator_enabled=False,
        n_elevators=1,
        elevator_served_levels=None,
        elevator_shaft_width=2.5,
        elevator_shaft_depth=2.5,
        elevator_car_width=1.8,
        elevator_car_depth=1.7,
        elevator_car_height=2.3,
        elevator_door_width=1.1,
        elevator_door_height=2.1,
        elevator_wall_thickness=0.12,
        elevator_core_clearance=0.75,
        elevator_staircase_core_width=8.0,
        elevator_staircase_core_depth=8.0,
        elevator_lobby_depth=2.0,
        elevator_overlap_threshold=0.98,
        elevator_placement_attempts=100,
    ):
        self.n_stories = rg(n_stories)
        self.unit, self.segment_margin, self.wall_thickness, self.wall_height = (
            self.global_params().values()
        )
        self.door_width, self.door_margin, self.door_size = self.door_params().values()
        (
            self.max_window_length,
            self.window_height,
            self.window_margin,
            self.window_size,
            self.window_top,
        ) = self.window_params().values()
        self.staircase_snap, self.staircase_thresh = self.staircase_params().values()
        if room_type is None:
            self.room_types = self.home_room_types
        else:
            self.room_types = room_type
        self.aspect_ratio_range = aspect_ratio_range
        self.fixed_contour = rg(fixed_contour)
        if (min_rooms_per_floor is None) != (max_rooms_per_floor is None):
            raise ValueError(
                "RoomConstants.min_rooms_per_floor and max_rooms_per_floor "
                "must either both be set or both be omitted"
            )
        if min_rooms_per_floor is None:
            self.min_rooms_per_floor = None
            self.max_rooms_per_floor = None
        else:
            for name, value in (
                ("min_rooms_per_floor", min_rooms_per_floor),
                ("max_rooms_per_floor", max_rooms_per_floor),
            ):
                if isinstance(value, (bool, np.bool_)) or not isinstance(
                    value, (int, np.integer)
                ):
                    raise ValueError(f"RoomConstants.{name} must be an integer")
                if int(value) < 1:
                    raise ValueError(f"RoomConstants.{name} must be positive")
            self.min_rooms_per_floor = int(min_rooms_per_floor)
            self.max_rooms_per_floor = int(max_rooms_per_floor)
            if self.min_rooms_per_floor > self.max_rooms_per_floor:
                raise ValueError(
                    "RoomConstants.min_rooms_per_floor cannot exceed "
                    "max_rooms_per_floor"
                )
        building_levels_explicit = building_levels is not None
        if building_levels is None:
            self.building_levels = BuildingLevels.uniform(
                int(self.n_stories), self.wall_height
            )
        else:
            self.building_levels = BuildingLevels.coerce(building_levels)
            if len(self.building_levels) != self.n_stories:
                raise ValueError(
                    "RoomConstants.n_stories must match the provided BuildingLevels; "
                    f"got {self.n_stories} and {len(self.building_levels)}"
                )
        self.elevator_enabled = bool(elevator_enabled)
        # Keep the native one-to-three-story path's tag sets exactly unchanged.
        # Dynamic floor metadata is opt-in for elevators/custom stacks and is
        # mandatory only once the legacy three semantic floor tags run out.
        self.dynamic_level_tags_enabled = (
            self.elevator_enabled
            or building_levels_explicit
            or self.n_stories > len(t.Semantics.floors)
        )
        self.n_elevators = int(n_elevators)
        if self.n_elevators < 1:
            raise ValueError("RoomConstants.n_elevators must be at least one")
        if elevator_served_levels in (None, "all"):
            self.elevator_served_levels = None
        else:
            self.elevator_served_levels = tuple(int(i) for i in elevator_served_levels)
            if (
                tuple(sorted(set(self.elevator_served_levels)))
                != self.elevator_served_levels
            ):
                raise ValueError("elevator_served_levels must be sorted and unique")
            if not self.elevator_served_levels:
                raise ValueError("elevator_served_levels cannot be empty")
            if self.elevator_enabled and len(self.elevator_served_levels) < 2:
                raise ValueError(
                    "An enabled moving elevator must serve at least two levels"
                )
            if (
                self.elevator_served_levels[0] < 0
                or self.elevator_served_levels[-1] >= self.n_stories
            ):
                raise ValueError(
                    "elevator_served_levels must reference existing building levels"
                )
        positive_dimensions = {
            "elevator_shaft_width": elevator_shaft_width,
            "elevator_shaft_depth": elevator_shaft_depth,
            "elevator_car_width": elevator_car_width,
            "elevator_car_depth": elevator_car_depth,
            "elevator_car_height": elevator_car_height,
            "elevator_door_width": elevator_door_width,
            "elevator_door_height": elevator_door_height,
            "elevator_wall_thickness": elevator_wall_thickness,
            "elevator_staircase_core_width": elevator_staircase_core_width,
            "elevator_staircase_core_depth": elevator_staircase_core_depth,
            "elevator_lobby_depth": elevator_lobby_depth,
        }
        for name, value in positive_dimensions.items():
            value = float(value)
            if value <= 0:
                raise ValueError(f"{name} must be positive, got {value}")
            setattr(self, name, value)
        self.elevator_core_clearance = float(elevator_core_clearance)
        if self.elevator_core_clearance < 0:
            raise ValueError("elevator_core_clearance must be non-negative")
        self.elevator_overlap_threshold = float(elevator_overlap_threshold)
        if not 0 < self.elevator_overlap_threshold <= 1:
            raise ValueError("elevator_overlap_threshold must be in (0, 1]")
        self.elevator_placement_attempts = int(elevator_placement_attempts)
        if self.elevator_placement_attempts < 1:
            raise ValueError("elevator_placement_attempts must be positive")
        inner_shaft_width = self.elevator_shaft_width - 2 * self.elevator_wall_thickness
        inner_shaft_depth = self.elevator_shaft_depth - 2 * self.elevator_wall_thickness
        if self.elevator_car_width >= inner_shaft_width:
            raise ValueError(
                "elevator_car_width must fit inside shaft width after both walls"
            )
        if self.elevator_car_depth >= inner_shaft_depth:
            raise ValueError(
                "elevator_car_depth must fit inside shaft depth after both walls"
            )
        if self.elevator_door_width >= inner_shaft_width:
            raise ValueError(
                "elevator_door_width must fit inside shaft width after both walls"
            )

    @gin.configurable(module="RoomConstants")
    def global_params(
        self,
        unit=0.5,
        segment_margin=1.4,
        wall_thickness=("uniform", 0.2, 0.3),
        wall_height=("uniform", 2.8, 3.2),
    ):
        wall_thickness = rg(wall_thickness)
        wall_height = rg(wall_height)
        return {
            "unit": unit,
            "segment_margin": segment_margin,
            "wall_thickness": wall_thickness,
            "wall_height": wall_height,
        }

    def door_params(
        self, door_width_ratio=("uniform", 0.7, 0.8), door_size=("uniform", 2.0, 2.4)
    ):
        door_width = (self.segment_margin - self.wall_thickness) * rg(door_width_ratio)
        assert door_width > 0
        door_margin = (self.segment_margin - door_width) / 2
        door_size = rg(door_size)
        return {
            "door_width": door_width,
            "door_margin": door_margin,
            "door_size": door_size,
        }

    def window_params(
        self,
        max_window_length=("uniform", 6, 8),
        window_height=("uniform", 0.8, 1.2),
        window_margin=("uniform", 0.2, 0.25),
        window_size=("uniform", 1.0, 1.5),
    ):
        max_window_length = rg(max_window_length)
        window_height = rg(window_height)
        window_size = rg(window_size)
        window_margin = rg(window_margin)
        window_top = (
            self.wall_height - self.wall_thickness - window_height - window_size
        )
        window_top = max(self.wall_thickness / 2, window_top)
        window_size = (
            self.wall_height - self.wall_thickness - window_top - window_height
        )
        assert window_size > 0
        return {
            "max_window_length": max_window_length,
            "window_height": window_height,
            "window_margin": window_margin,
            "window_size": window_size,
            "window_top": window_top,
        }

    def staircase_params(
        self,
    ):
        return {"staircase_snap": 1.2, "staircase_thresh": 0.6}

    def unit_cast(self, x):
        x = np.round(x / self.unit) * self.unit
        if x.size == 1:
            return x.item()
        return x

    def canonicalize(self, p):
        p = p.buffer(0)
        try:
            while True:
                p_ = shapely.force_2d(simplify_polygon(p))
                if p.area == 0:
                    raise NotImplementedError("Polygon empty.")
                p = orient(p_)
                coords = np.array(
                    p.boundary.coords[:]
                    if not hasattr(p.boundary, "geoms")
                    else p.exterior.coords[:]
                )
                l = len(coords)
                rounded = np.round(coords / self.unit) * self.unit
                coords = np.where(
                    np.all(np.abs(coords - rounded) < 1e-3, -1)[:, np.newaxis],
                    rounded,
                    coords,
                )
                diff = coords[1:] - coords[:-1]
                diff = diff / (np.linalg.norm(diff, axis=-1, keepdims=True) + 1e-6)
                product = (diff[[-1] + list(range(len(diff) - 1))] * diff).sum(-1)
                valid_indices = list(range(len(coords) - 1))
                invalid_indices = np.nonzero((product < -0.8) | (product > 1 - 1e-6))[
                    0
                ].tolist()
                if len(invalid_indices) > 0:
                    i = invalid_indices[len(invalid_indices) // 2]
                    valid_indices.remove(i)
                p = shapely.Polygon(coords[valid_indices + [valid_indices[0]]])
                if len(p.exterior.coords) == l:
                    break
            if not is_valid_polygon(p):
                raise NotImplementedError("Invalid polygon")
            return orient(p)
        except AttributeError:
            raise NotImplementedError("Invalid multi polygon")

    def filter(self, ses, margin=None):
        margin = self.segment_margin if margin is None else margin
        return list(l for l, se in ses.items() if segment_filter(se, margin))

    @property
    def home_room_types(self):
        return {
            t.Semantics.Kitchen,
            t.Semantics.Bedroom,
            t.Semantics.LivingRoom,
            t.Semantics.Closet,
            t.Semantics.Hallway,
            t.Semantics.Bathroom,
            t.Semantics.Garage,
            t.Semantics.Balcony,
            t.Semantics.DiningRoom,
            t.Semantics.Utility,
            t.Semantics.StaircaseRoom,
        }

    @property
    def floors(self):
        legacy = [
            t.Semantics.GroundFloor,
            t.Semantics.SecondFloor,
            t.Semantics.ThirdFloor,
        ]
        return legacy + [t.FloorIndex(i) for i in range(3, self.n_stories)]

    def level_spec(self, index):
        return self.building_levels.by_index(index)

    def floor_tags(self, index):
        if self.dynamic_level_tags_enabled:
            return self.building_levels.tags_for(index)
        return frozenset({self.floors[index]})

    def solidifier_floor_tags(self, index):
        """Tags added to emitted room/cutter states on new level-aware paths.

        Legacy solidified states never carried a floor tag.  Returning an empty
        set on that path is required for behavior-preserving default output.
        """

        if not self.dynamic_level_tags_enabled:
            return frozenset()
        return self.building_levels.tags_for(index)

    def floor_tag(self, index):
        return self.building_levels.primary_tag(index)
