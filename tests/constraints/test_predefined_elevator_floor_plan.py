import shapely

from infinigen.core.constraints.example_solver.room.solidifier import (
    BlueprintSolidifier,
)
from infinigen_examples.configs_indoor.floor_plans.elevator import (
    make_elevator_floor_plan,
)


def test_fixed_blueprint_scales_with_floor_count():
    plan = make_elevator_floor_plan(8)

    assert len(plan["rooms"]) == 8 * 6
    assert (
        len([name for name in plan["rooms"] if name.startswith("elevator-room_")]) == 8
    )
    assert (
        len([name for name in plan["rooms"] if name.startswith("staircase-room_")]) == 8
    )
    assert (
        len(
            [
                door
                for door in plan["doors"].values()
                if door.get("semantic") == "elevator_landing"
            ]
        )
        == 8
    )


def test_fixed_blueprint_rooms_tile_each_floor_and_cores_align():
    plan = make_elevator_floor_plan(4)
    expected_contour = shapely.box(0, 0, 20, 16)
    shafts = []
    stairs = []
    for level in range(4):
        level_rooms = [
            info["shape"]
            for name, info in plan["rooms"].items()
            if f"_{level}/" in name
        ]
        assert shapely.union_all(level_rooms).equals(expected_contour)
        assert sum(room.area for room in level_rooms) == expected_contour.area
        shafts.append(plan["rooms"][f"elevator-room_{level}/0"]["shape"])
        stairs.append(plan["rooms"][f"staircase-room_{level}/0"]["shape"])

    assert all(shaft.equals(shafts[0]) for shaft in shafts)
    assert all(stair.equals(stairs[0]) for stair in stairs)
    assert shafts[0].intersection(stairs[0]).area == 0
    assert shafts[0].distance(stairs[0]) >= 1.5


def test_every_portal_has_explicit_level_in_v2_schema():
    plan = make_elevator_floor_plan(4)
    for group_name in ("doors", "entrance", "opens", "interiors", "windows"):
        assert all("level" in portal for portal in plan[group_name].values())


def test_shared_predefined_cutter_is_unrolled_once_with_both_rooms():
    cutter = object()

    entries = list(
        BlueprintSolidifier.unroll(
            {
                "elevator-room_0/0": [cutter],
                "elevator-lobby_0/0": [cutter],
            }
        )
    )

    assert entries == [(("elevator-room_0/0", "elevator-lobby_0/0"), cutter)]
