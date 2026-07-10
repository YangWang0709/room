# Copyright (C) 2026, Princeton University.
# This source code is licensed under the BSD 3-Clause license found in the
# LICENSE file in the root directory of this source tree.

"""Shared vertical-core placement primitives for multi-floor buildings.

The original indoor solver carries one staircase polygon through all levels.
This module generalizes that contract without making the room solver aware of
specific assets.  A core has a room semantic, a placeholder semantic, a set of
levels that it spans, and a deterministic XY placement shared by those levels.

The placement code deliberately uses a local ``numpy.random.Generator``.  It
must never advance Infinigen's global RNG stream when the optional elevator
feature is disabled.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import reduce
from typing import Iterable, Mapping, Sequence

import numpy as np
import shapely
from shapely.geometry import Polygon, box

from infinigen.core.tags import Tag

_DIRECTIONS = ("-y", "+x", "+y", "-x")


@dataclass(frozen=True)
class VerticalCoreSpec:
    """Configuration for one vertical-core instance.

    ``span_levels`` describes every floor crossed by the physical shaft.  The
    smaller ``served_levels`` set controls where a lobby/landing is required.
    They are separate so express elevators can pass through floors without
    creating a landing door.
    """

    core_id: str
    room_type: Tag
    placeholder_tag: Tag
    instance_index: int
    width: float
    depth: float
    span_levels: tuple[int, ...]
    served_levels: tuple[int, ...]
    lobby_room_type: Tag | None = None
    overlap_threshold: float = 0.98
    lobby_overlap_threshold: float = 0.5
    clearance: float = 0.5
    lobby_depth: float = 1.8
    door_width: float = 1.1

    def __post_init__(self):
        if not self.core_id:
            raise ValueError("Vertical core id cannot be empty")
        if self.instance_index < 0:
            raise ValueError("Vertical core instance_index must be non-negative")
        if self.width <= 0 or self.depth <= 0:
            raise ValueError("Vertical core footprint dimensions must be positive")
        if not self.span_levels:
            raise ValueError("Vertical core must span at least one level")
        if tuple(sorted(set(self.span_levels))) != self.span_levels:
            raise ValueError("span_levels must be sorted and unique")
        if tuple(sorted(set(self.served_levels))) != self.served_levels:
            raise ValueError("served_levels must be sorted and unique")
        if not set(self.served_levels).issubset(self.span_levels):
            raise ValueError("served_levels must be a subset of span_levels")
        if not 0 < self.overlap_threshold <= 1:
            raise ValueError("overlap_threshold must be in (0, 1]")
        if not 0 < self.lobby_overlap_threshold <= 1:
            raise ValueError("lobby_overlap_threshold must be in (0, 1]")
        if self.clearance < 0 or self.lobby_depth < 0:
            raise ValueError("Vertical core clearances must be non-negative")
        if not 0 < self.door_width <= max(self.width, self.depth):
            raise ValueError("door_width must fit at least one shaft side")

    def room_key(self, level: int) -> str:
        return f"{self.room_type.value}_{level}/{self.instance_index}"

    def placeholder_key(self, level: int) -> str:
        return f"{self.placeholder_tag.value}_{level}/{self.instance_index}"

    def lobby_key(self, level: int) -> str | None:
        if self.lobby_room_type is None or level not in self.served_levels:
            return None
        return f"{self.lobby_room_type.value}_{level}/{self.instance_index}"


@dataclass(frozen=True)
class VerticalCorePlacement:
    """A resolved, building-local placement shared by all spanned floors."""

    spec: VerticalCoreSpec
    polygon: Polygon
    door_side: str

    def __post_init__(self):
        if self.door_side not in _DIRECTIONS:
            raise ValueError(f"Unsupported vertical-core door side {self.door_side!r}")
        if self.polygon.is_empty or not self.polygon.is_valid:
            raise ValueError("Vertical-core polygon must be non-empty and valid")

    @property
    def lobby_polygon(self) -> Polygon:
        """Return the required clear landing area immediately outside the door."""

        x0, y0, x1, y1 = self.polygon.bounds
        depth = self.spec.lobby_depth
        if self.door_side == "-y":
            return box(x0, y0 - depth, x1, y0)
        if self.door_side == "+y":
            return box(x0, y1, x1, y1 + depth)
        if self.door_side == "-x":
            return box(x0 - depth, y0, x0, y1)
        return box(x1, y0, x1 + depth, y1)

    @property
    def required_polygon(self) -> Polygon:
        return shapely.union(self.polygon, self.lobby_polygon)


class VerticalCoreRegistry:
    """Immutable lookup and validation wrapper around resolved placements."""

    def __init__(self, placements: Iterable[VerticalCorePlacement] = ()):
        placements = tuple(placements)
        ids = [placement.spec.core_id for placement in placements]
        if len(ids) != len(set(ids)):
            raise ValueError(f"Duplicate vertical-core ids: {ids}")
        self._placements = placements
        self._by_id = {placement.spec.core_id: placement for placement in placements}

    def __iter__(self):
        return iter(self._placements)

    def __len__(self):
        return len(self._placements)

    def __bool__(self):
        return bool(self._placements)

    def __getitem__(self, core_id: str) -> VerticalCorePlacement:
        return self._by_id[core_id]

    @property
    def placements(self) -> tuple[VerticalCorePlacement, ...]:
        return self._placements

    def for_level(self, level: int) -> tuple[VerticalCorePlacement, ...]:
        return tuple(
            placement
            for placement in self._placements
            if level in placement.spec.span_levels
        )

    def for_room_key(self, room_key: str, level: int) -> VerticalCorePlacement | None:
        for placement in self.for_level(level):
            if placement.spec.room_key(level) == room_key:
                return placement
        return None

    def validate(self, contours: Sequence[Polygon], tolerance: float = 1e-6) -> None:
        """Raise when a core leaves its levels or intersects another core."""

        for placement in self._placements:
            for level in placement.spec.span_levels:
                try:
                    contour = contours[level]
                except IndexError as exc:
                    raise ValueError(
                        f"Core {placement.spec.core_id!r} references missing level {level}"
                    ) from exc
                required = (
                    placement.required_polygon
                    if level in placement.spec.served_levels
                    else placement.polygon
                )
                if not contour.buffer(tolerance).covers(required):
                    raise ValueError(
                        f"Core {placement.spec.core_id!r} leaves contour at level {level}"
                    )

        for i, left in enumerate(self._placements):
            for right in self._placements[i + 1 :]:
                common_levels = set(left.spec.span_levels).intersection(
                    right.spec.span_levels
                )
                if not common_levels:
                    continue
                margin = max(left.spec.clearance, right.spec.clearance)
                if left.polygon.buffer(margin - tolerance).intersects(right.polygon):
                    raise ValueError(
                        f"Vertical cores {left.spec.core_id!r} and "
                        f"{right.spec.core_id!r} overlap or violate clearance"
                    )

    def to_manifest_dict(self) -> list[dict]:
        """Return JSON-safe structural data; no Shapely objects escape."""

        result = []
        for placement in self._placements:
            spec = placement.spec
            result.append(
                {
                    "core_id": spec.core_id,
                    "room_type": spec.room_type.value,
                    "placeholder_tag": spec.placeholder_tag.value,
                    "lobby_room_type": (
                        None
                        if spec.lobby_room_type is None
                        else spec.lobby_room_type.value
                    ),
                    "instance_index": spec.instance_index,
                    "span_levels": list(spec.span_levels),
                    "served_levels": list(spec.served_levels),
                    "footprint_xy": [
                        [float(x), float(y)]
                        for x, y in placement.polygon.exterior.coords[:-1]
                    ],
                    "door_side": placement.door_side,
                    "clearance": spec.clearance,
                    "lobby_depth": spec.lobby_depth,
                    "door_width": spec.door_width,
                }
            )
        return result


def _common_contour(contours: Sequence[Polygon], levels: Sequence[int]):
    try:
        selected = [contours[level] for level in levels]
    except IndexError as exc:
        raise ValueError("Vertical core references a missing building level") from exc
    common = reduce(shapely.intersection, selected)
    if common.is_empty:
        raise ValueError(f"Levels {tuple(levels)} have no common core footprint")
    return common


def _candidate_lobby(shaft: Polygon, side: str, lobby_depth: float) -> Polygon:
    x0, y0, x1, y1 = shaft.bounds
    if side == "-y":
        return box(x0, y0 - lobby_depth, x1, y0)
    if side == "+y":
        return box(x0, y1, x1, y1 + lobby_depth)
    if side == "-x":
        return box(x0 - lobby_depth, y0, x0, y1)
    return box(x1, y0, x1 + lobby_depth, y1)


def place_vertical_core(
    contours: Sequence[Polygon],
    spec: VerticalCoreSpec,
    *,
    occupied: Iterable[VerticalCorePlacement] = (),
    seed: int,
    unit: float = 0.5,
    max_trials: int = 4000,
) -> VerticalCorePlacement:
    """Place one core deterministically in the common contour of its levels."""

    if unit <= 0:
        raise ValueError("Core placement grid unit must be positive")
    common = _common_contour(contours, spec.span_levels)
    minx, miny, maxx, maxy = common.bounds
    occupied = tuple(occupied)
    rng = np.random.default_rng(seed)

    orientations = [(spec.width, spec.depth)]
    if not np.isclose(spec.width, spec.depth):
        orientations.append((spec.depth, spec.width))

    candidates: list[tuple[float, float, float, float, str]] = []
    for width, depth in orientations:
        x0 = np.ceil(minx / unit) * unit
        y0 = np.ceil(miny / unit) * unit
        xs = np.arange(x0, maxx - width + unit * 0.25, unit)
        ys = np.arange(y0, maxy - depth + unit * 0.25, unit)
        for x in xs:
            for y in ys:
                for side in _DIRECTIONS:
                    side_length = width if side in {"-y", "+y"} else depth
                    if spec.door_width > side_length:
                        continue
                    candidates.append((float(x), float(y), width, depth, side))

    if not candidates:
        raise ValueError(
            f"No grid candidates for vertical core {spec.core_id!r} in common contour"
        )
    order = rng.permutation(len(candidates))[:max_trials]
    for candidate_index in order:
        x, y, width, depth, side = candidates[int(candidate_index)]
        shaft = box(x, y, x + width, y + depth)
        lobby = _candidate_lobby(shaft, side, spec.lobby_depth)
        required = shapely.union(shaft, lobby)
        if not common.buffer(1e-8).covers(required):
            continue
        if any(
            shaft.buffer(max(spec.clearance, other.spec.clearance)).intersects(
                other.polygon
            )
            for other in occupied
            if set(spec.span_levels).intersection(other.spec.span_levels)
        ):
            continue
        placement = VerticalCorePlacement(spec, shaft, side)
        return placement

    raise ValueError(
        f"Unable to place vertical core {spec.core_id!r} after "
        f"{min(len(candidates), max_trials)} deterministic candidates"
    )


def place_vertical_cores(
    contours: Sequence[Polygon],
    specs: Sequence[VerticalCoreSpec],
    *,
    seed: int,
    unit: float = 0.5,
    preplaced: Iterable[VerticalCorePlacement] = (),
) -> VerticalCoreRegistry:
    """Place several cores in stable order with isolated per-core RNG streams."""

    placements = list(preplaced)
    for index, spec in enumerate(specs):
        # SeedSequence avoids Python's process-randomized hash and does not touch
        # the global NumPy RNG used by the legacy floor-plan solver.
        child_seed = int(
            np.random.SeedSequence(
                [int(seed), index, spec.instance_index]
            ).generate_state(1, dtype=np.uint32)[0]
        )
        placements.append(
            place_vertical_core(
                contours,
                spec,
                occupied=placements,
                seed=child_seed,
                unit=unit,
            )
        )
    registry = VerticalCoreRegistry(placements)
    registry.validate(contours)
    return registry


def core_candidate_segments(
    segments: Mapping[int, Polygon], placement: VerticalCorePlacement
) -> set[int]:
    """Return segments satisfying the configured placeholder overlap ratio."""

    placeholder = placement.polygon
    return {
        index
        for index, segment in segments.items()
        if segment.intersection(placeholder).area / placeholder.area
        > placement.spec.overlap_threshold
    }


def lobby_candidate_segments(
    segments: Mapping[int, Polygon], placement: VerticalCorePlacement
) -> set[int]:
    """Return candidates covering the landing-clearance polygon."""

    lobby = placement.lobby_polygon
    if lobby.area <= 0:
        return set()
    return {
        index
        for index, segment in segments.items()
        if segment.intersection(lobby).area / lobby.area
        > placement.spec.lobby_overlap_threshold
    }
