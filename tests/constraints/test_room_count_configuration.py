# Copyright (C) 2026, Princeton University.
# This code is licensed under the BSD 3-Clause license found in the LICENSE
# file in the root directory of this source tree.

import gin

from infinigen.core.constraints import constraint_language as cl
from infinigen_examples.constraints.home import home_room_constraints


def _room_count_constraint(*, minimum=None, maximum=None):
    gin.bind_parameter("RoomConstants.n_stories", 4)
    gin.bind_parameter("RoomConstants.elevator_enabled", True)
    gin.bind_parameter("home_room_constraints.fixed_contour", True)
    if minimum is not None:
        gin.bind_parameter("RoomConstants.min_rooms_per_floor", minimum)
    if maximum is not None:
        gin.bind_parameter("RoomConstants.max_rooms_per_floor", maximum)
    problem = home_room_constraints()
    return problem.constants, problem.constraints["node"].operands[0]


def test_default_room_count_constraint_preserves_native_range_and_domain():
    constants, constraint = _room_count_constraint()

    assert constants.min_rooms_per_floor is None
    assert constants.max_rooms_per_floor is None
    assert constants.fixed_contour is True
    assert isinstance(constraint, cl.in_range)
    assert (constraint.low, constraint.high, constraint.mean) == (4, 15, 0)
    assert "-Semantics.StaircaseRoom" not in repr(constraint.val.objs)


def test_configured_room_count_is_ordinary_furnishable_room_range():
    constants, constraint = _room_count_constraint(minimum=7, maximum=8)

    assert constants.min_rooms_per_floor == 7
    assert constants.max_rooms_per_floor == 8
    assert isinstance(constraint, cl.in_range)
    assert (constraint.low, constraint.high, constraint.mean) == (7, 8, 7.5)
    domain = repr(constraint.val.objs)
    for excluded in (
        "-Semantics.StaircaseRoom",
        "-Semantics.ElevatorRoom",
        "-Semantics.ElevatorLobby",
        "-Semantics.ElevatorShaft",
    ):
        assert excluded in domain
