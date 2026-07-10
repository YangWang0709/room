# Copyright (C) 2026, Princeton University.
# This source code is licensed under the BSD 3-Clause license found in the LICENSE file in the root directory
# of this source tree.

from types import SimpleNamespace

import numpy as np
import pytest

from infinigen.core import tags as t
from infinigen.core.constraints.constraint_language.constants import RoomConstants
from infinigen.core.constraints.constraint_language.levels import (
    BuildingLevels,
    LevelSpec,
)
from infinigen.core.constraints.example_solver.room.base import room_level, room_name
from infinigen.core.constraints.example_solver.room.graph import GraphMaker
from infinigen.core.constraints.example_solver.room.solidifier import (
    BlueprintSolidifier,
)


@pytest.mark.parametrize("n_levels", [1, 3, 4, 8, 16])
def test_uniform_building_levels_scale_without_floor_tag_limit(n_levels):
    height = 3.25
    levels = BuildingLevels.uniform(n_levels, height)
    constants = RoomConstants(
        n_stories=n_levels,
        building_levels=levels,
        fixed_contour=False,
    )

    assert len(levels) == n_levels
    assert levels.stop_z == [i * height for i in range(n_levels)]
    assert [level.index for level in levels] == list(range(n_levels))
    assert [level.level_id for level in levels] == [f"F{i}" for i in range(n_levels)]

    for index in range(n_levels):
        tags = constants.floor_tags(index)
        assert t.FloorIndex(index) in tags
        if index < 3:
            assert t.Semantics.floors[index] in tags
        else:
            assert tags == frozenset({t.FloorIndex(index)})

    maker = GraphMaker.__new__(GraphMaker)
    maker.constants = constants
    maker.level = n_levels - 1
    assert maker.floor_tags == constants.floor_tags(n_levels - 1)
    assert maker.semantics_floor == constants.floor_tag(n_levels - 1)

    solidifier = BlueprintSolidifier(
        SimpleNamespace(constants=constants), None, n_levels - 1
    )
    assert solidifier.elevation == levels[-1].elevation
    assert solidifier.wall_height == levels[-1].height
    assert solidifier.floor_tags == levels.tags_for(n_levels - 1)

    # The historical property remains unchanged for 1-3 story callers and
    # extends dynamically only when a higher index is requested.
    assert constants.floors[:3] == t.Semantics.floors
    assert len(constants.floors) == max(3, n_levels)


def test_nonuniform_elevations_and_basement_ids():
    levels = BuildingLevels(
        (
            LevelSpec(0, -7.0, 3.0, "B2"),
            LevelSpec(1, -3.5, 3.2, "B1"),
            LevelSpec(2, 0.0, 4.0, "G"),
            LevelSpec(3, 4.2, 3.5, "L2"),
            LevelSpec(4, 8.9, 3.0, "L3"),
        )
    )
    constants = RoomConstants(
        n_stories=5,
        building_levels=levels,
        fixed_contour=False,
    )

    assert levels.stop_z == [-7.0, -3.5, 0.0, 4.2, 8.9]
    assert levels.ground_index == 2
    assert levels.by_index(t.FloorIndex(1)).level_id == "B1"
    assert levels.by_id("L2").index == 3

    assert levels.tags_for(0) == frozenset({t.FloorIndex(0)})
    assert levels.tags_for(1) == frozenset({t.FloorIndex(1)})
    assert levels.tags_for(2) == frozenset({t.FloorIndex(2), t.Semantics.GroundFloor})
    assert levels.tags_for(3) == frozenset({t.FloorIndex(3), t.Semantics.SecondFloor})
    assert levels.tags_for(4) == frozenset({t.FloorIndex(4), t.Semantics.ThirdFloor})

    for level in levels:
        solidifier = BlueprintSolidifier(
            SimpleNamespace(constants=constants), None, level.index
        )
        assert solidifier.elevation == level.elevation
        assert solidifier.wall_height == level.height
        assert solidifier.is_ground_level == (level.level_id == "G")


@pytest.mark.parametrize(
    "levels, message",
    [
        (
            (LevelSpec(0, 0, 3), LevelSpec(2, 3, 3)),
            "unique, continuous",
        ),
        (
            (LevelSpec(0, 0, 3), LevelSpec(1, 0, 3)),
            "strictly increasing",
        ),
        (
            (LevelSpec(0, 0, 3, "G"), LevelSpec(1, 3, 3, "G")),
            "unique",
        ),
    ],
)
def test_building_levels_validation(levels, message):
    with pytest.raises(ValueError, match=message):
        BuildingLevels(levels)


def test_level_spec_and_lookup_validation():
    with pytest.raises(ValueError, match="non-negative"):
        LevelSpec(-1, -3, 3)
    with pytest.raises(ValueError, match="positive"):
        LevelSpec(0, 0, 0)
    with pytest.raises(ValueError, match="non-empty"):
        LevelSpec(0, 0, 3, "")

    levels = BuildingLevels.uniform(3, 3)
    with pytest.raises(KeyError, match="Unknown level index"):
        levels.by_index(-1)
    with pytest.raises(KeyError, match="Unknown level index"):
        levels.by_index(3)
    with pytest.raises(KeyError, match="Unknown level ID"):
        levels.by_id("roof")


def test_floor_index_roundtrip_sorting_and_reasoning():
    floor = t.FloorIndex(12)
    assert repr(floor) == "FloorIndex(12)"
    assert str(floor) == "FloorIndex(12)"
    assert t.to_string(floor) == "floor-index-12"
    assert t.to_tag("floor-index-12") == floor
    assert t.to_tag("FloorIndex(12)") == floor
    assert t.to_tag("-floor-index-12") == -floor

    mixed = {
        t.Subpart.Wall,
        t.Semantics.GroundFloor,
        t.FloorIndex(10),
        t.FloorIndex(2),
    }
    assert sorted(mixed) == [
        t.FloorIndex(2),
        t.FloorIndex(10),
        t.Semantics.GroundFloor,
        t.Subpart.Wall,
    ]
    assert t.contradiction({t.FloorIndex(2), t.FloorIndex(3)})
    assert not t.contradiction({t.FloorIndex(2), t.Semantics.GroundFloor})
    assert t.satisfies({t.FloorIndex(4)}, {t.FloorIndex(4)})
    assert not t.satisfies({t.FloorIndex(4)}, {t.FloorIndex(5)})


def test_room_names_keep_nonnegative_internal_level_indices():
    level = LevelSpec(0, -6, 3, "B2")
    assert room_name(t.Semantics.Bedroom, level) == "bedroom_0/0"
    assert room_name(t.Semantics.Bedroom, t.FloorIndex(3), 2) == "bedroom_3/2"
    assert room_level("bedroom_3/2") == 3

    with pytest.raises(ValueError, match="non-negative"):
        room_name(t.Semantics.Bedroom, -1)
    with pytest.raises(ValueError, match="non-negative"):
        room_level("bedroom_-1/0")


def test_legacy_room_constants_rng_sequence_is_unchanged():
    np.random.seed(20260710)
    constants = RoomConstants(n_stories=3, fixed_contour=False)

    assert constants.n_stories == 3
    assert constants.dynamic_level_tags_enabled is False
    assert constants.floor_tags(0) == frozenset({t.Semantics.GroundFloor})
    assert constants.floor_tags(1) == frozenset({t.Semantics.SecondFloor})
    assert constants.floor_tags(2) == frozenset({t.Semantics.ThirdFloor})
    solidifier = BlueprintSolidifier(SimpleNamespace(constants=constants), None, 2)
    assert solidifier.elevation == constants.wall_height * 2
    assert solidifier.wall_height == constants.wall_height
    assert solidifier.window_top == constants.window_top
    assert solidifier.window_size == constants.window_size
    assert solidifier.floor_tags == frozenset()
    np.testing.assert_array_equal(
        np.random.random(8),
        np.array(
            [
                0.046502464019351986,
                0.45395824242033267,
                0.8608171729642291,
                0.9059387900484941,
                0.5094314882969431,
                0.15616888110509486,
                0.6723178998881375,
                0.4792172567861056,
            ]
        ),
    )


def test_room_constants_rejects_mismatched_explicit_levels():
    with pytest.raises(ValueError, match="must match"):
        RoomConstants(
            n_stories=4,
            building_levels=BuildingLevels.uniform(3, 3),
            fixed_contour=False,
        )


@pytest.mark.parametrize(
    "minimum,maximum,message",
    [
        (7, None, "both be set"),
        (None, 8, "both be set"),
        (True, 8, "must be an integer"),
        (7.5, 8, "must be an integer"),
        (0, 8, "must be positive"),
        (9, 8, "cannot exceed"),
    ],
)
def test_room_constants_validate_optional_per_floor_room_range(
    minimum, maximum, message
):
    with pytest.raises(ValueError, match=message):
        RoomConstants(
            n_stories=4,
            fixed_contour=False,
            min_rooms_per_floor=minimum,
            max_rooms_per_floor=maximum,
        )


def test_room_constants_accept_optional_per_floor_room_range():
    constants = RoomConstants(
        n_stories=4,
        fixed_contour=False,
        min_rooms_per_floor=7,
        max_rooms_per_floor=8,
    )

    assert constants.min_rooms_per_floor == 7
    assert constants.max_rooms_per_floor == 8


def test_room_constants_accepts_mapping_level_specs():
    constants = RoomConstants(
        n_stories=2,
        building_levels=[
            {"index": 0, "elevation": -3, "height": 3, "level_id": "B1"},
            {"index": 1, "elevation": 0, "height": 3, "level_id": "G"},
        ],
        fixed_contour=False,
    )
    assert constants.building_levels.stop_z == [-3.0, 0.0]
    assert constants.building_levels.by_id("G").index == 1
