# Copyright (C) 2026, Princeton University.
# This source code is licensed under the BSD 3-Clause license found in the LICENSE file in the root directory
# of this source tree.

"""Floor metadata shared by the indoor room graph and solidifier.

Room names continue to encode a non-negative, bottom-up integer index.  Physical
elevation and user-facing identifiers live here instead of being overloaded into
that index, which keeps the existing ``{room_type}_{level}/{room_id}`` schema
backwards compatible while allowing basements and non-uniform floor spacing.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from math import isclose, isfinite
from numbers import Integral

from infinigen.core.tags import FloorIndex, Semantics, Tag


@dataclass(frozen=True)
class LevelSpec:
    """Description of one building level.

    ``index`` is always the continuous internal index, counted from the lowest
    level upwards.  Basements therefore still have non-negative indices and are
    represented through a negative ``elevation`` and a descriptive ``level_id``.
    """

    index: int
    elevation: float
    height: float
    level_id: str | None = None

    def __post_init__(self):
        if isinstance(self.index, bool) or not isinstance(self.index, Integral):
            raise TypeError(f"Level index must be an integer, got {self.index!r}")
        if self.index < 0:
            raise ValueError(f"Level index must be non-negative, got {self.index}")

        elevation = float(self.elevation)
        height = float(self.height)
        if not isfinite(elevation):
            raise ValueError(f"Level elevation must be finite, got {self.elevation!r}")
        if not isfinite(height) or height <= 0:
            raise ValueError(
                f"Level height must be finite and positive, got {self.height!r}"
            )

        level_id = f"F{self.index}" if self.level_id is None else self.level_id
        if not isinstance(level_id, str) or not level_id.strip():
            raise ValueError(f"level_id must be a non-empty string, got {level_id!r}")
        level_id = level_id.strip()

        object.__setattr__(self, "elevation", elevation)
        object.__setattr__(self, "height", height)
        object.__setattr__(self, "level_id", level_id)
        object.__setattr__(self, "index", int(self.index))

    @property
    def floor_index(self) -> FloorIndex:
        return FloorIndex(self.index)


@dataclass(frozen=True)
class BuildingLevels(Sequence[LevelSpec]):
    """Validated, bottom-up sequence of building levels."""

    levels: tuple[LevelSpec, ...]

    def __post_init__(self):
        levels = tuple(self.levels)
        if not levels:
            raise ValueError("A building must contain at least one level")
        if not all(isinstance(level, LevelSpec) for level in levels):
            invalid = [
                type(level).__name__
                for level in levels
                if not isinstance(level, LevelSpec)
            ]
            raise TypeError(
                f"BuildingLevels only accepts LevelSpec values, got {invalid}"
            )

        indices = [level.index for level in levels]
        expected = list(range(len(levels)))
        if indices != expected:
            raise ValueError(
                "Level indices must be unique, continuous, and ordered bottom-up; "
                f"expected {expected}, got {indices}"
            )

        elevations = [level.elevation for level in levels]
        if any(upper <= lower for lower, upper in zip(elevations, elevations[1:])):
            raise ValueError(
                "Level elevations must be strictly increasing bottom-up, "
                f"got {elevations}"
            )

        level_ids = [level.level_id for level in levels]
        if len(set(level_ids)) != len(level_ids):
            raise ValueError(f"Level IDs must be unique, got {level_ids}")

        object.__setattr__(self, "levels", levels)

    @classmethod
    def uniform(
        cls,
        n_levels: int,
        height: float,
        base_elevation: float = 0.0,
    ) -> BuildingLevels:
        if isinstance(n_levels, bool) or not isinstance(n_levels, Integral):
            raise TypeError(f"n_levels must be an integer, got {n_levels!r}")
        if n_levels < 1:
            raise ValueError(f"n_levels must be positive, got {n_levels}")
        height = float(height)
        base_elevation = float(base_elevation)
        n_levels = int(n_levels)
        return cls(
            tuple(
                LevelSpec(
                    index=index,
                    elevation=base_elevation + index * height,
                    height=height,
                )
                for index in range(n_levels)
            )
        )

    @classmethod
    def coerce(
        cls,
        value: BuildingLevels | Iterable[LevelSpec | Mapping],
    ) -> BuildingLevels:
        if isinstance(value, cls):
            return value
        levels = tuple(
            LevelSpec(**level) if isinstance(level, Mapping) else level
            for level in value
        )
        return cls(levels)

    def __len__(self) -> int:
        return len(self.levels)

    def __iter__(self) -> Iterator[LevelSpec]:
        return iter(self.levels)

    def __getitem__(self, index: int | slice) -> LevelSpec | tuple[LevelSpec, ...]:
        return self.levels[index]

    def by_index(self, index: int | FloorIndex) -> LevelSpec:
        if isinstance(index, FloorIndex):
            index = index.index
        if isinstance(index, bool) or not isinstance(index, Integral):
            raise TypeError(f"Level index must be an integer, got {index!r}")
        index = int(index)
        if index < 0:
            raise KeyError(f"Unknown level index {index}")
        try:
            return self.levels[index]
        except IndexError as exc:
            raise KeyError(f"Unknown level index {index}") from exc

    def by_id(self, level_id: str) -> LevelSpec:
        for level in self.levels:
            if level.level_id == level_id:
                return level
        raise KeyError(f"Unknown level ID {level_id!r}")

    @property
    def stop_z(self) -> list[float]:
        """Physical floor elevations, ordered from the lowest level upwards."""

        return [level.elevation for level in self.levels]

    @property
    def ground_index(self) -> int:
        """Index carrying the legacy ``GroundFloor`` semantic.

        Custom stacks normally express the ground datum with elevation zero. If
        they do not contain that datum, the lowest level retains legacy behavior
        and is treated as ground.
        """

        for level in self.levels:
            if isclose(level.elevation, 0.0, abs_tol=1e-9):
                return level.index
        return 0

    def legacy_tag(self, index: int | FloorIndex) -> Semantics | None:
        level = self.by_index(index)
        above_ground = level.index - self.ground_index
        if 0 <= above_ground < len(Semantics.floors):
            return Semantics.floors[above_ground]
        return None

    def tags_for(self, index: int | FloorIndex) -> frozenset[Tag]:
        level = self.by_index(index)
        tags: set[Tag] = {level.floor_index}
        legacy = self.legacy_tag(level.index)
        if legacy is not None:
            tags.add(legacy)
        return frozenset(tags)

    def primary_tag(self, index: int | FloorIndex) -> Tag:
        level = self.by_index(index)
        return self.legacy_tag(level.index) or level.floor_index
