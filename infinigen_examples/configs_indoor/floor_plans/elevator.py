# Copyright (C) 2026, Princeton University.
# This source code is licensed under the BSD 3-Clause license found in the
# LICENSE file in the root directory of this source tree.

"""Deterministic multi-floor elevator blueprints used by integration tests.

The ordinary rooms intentionally remain real Infinigen room shells.  Only the
macro topology is fixed, allowing the native furniture/material stages to run
unchanged while shaft geometry and motion are debugged independently from the
random floor-plan solver.
"""

from __future__ import annotations

import shapely


def make_elevator_floor_plan(n_stories: int, n_elevators: int = 1):
    if n_stories < 2:
        raise ValueError("The elevator smoke blueprint requires at least two floors")
    if n_elevators != 1:
        raise NotImplementedError(
            "The fixed smoke blueprint has one shaft; the random core planner "
            "supports multiple elevator specs"
        )

    rooms = {}
    doors = {}
    entrances = {}
    for level in range(n_stories):
        # These six polygons tile a 20 m x 16 m contour without overlap.  The
        # 8 m square staircase room is deliberate: native stair factories vary
        # substantially in footprint and the deterministic smoke layout must
        # not lower their geometry quality merely to make the building compact.
        rooms[f"elevator-room_{level}/0"] = {"shape": shapely.box(0.0, 0.0, 2.5, 2.5)}
        rooms[f"elevator-lobby_{level}/0"] = {
            "shape": shapely.union(
                shapely.box(2.5, 0.0, 8.0, 2.5),
                shapely.box(0.0, 2.5, 8.0, 4.0),
            )
        }
        rooms[f"staircase-room_{level}/0"] = {"shape": shapely.box(0.0, 4.0, 8.0, 12.0)}
        rooms[f"living-room_{level}/0"] = {"shape": shapely.box(8.0, 0.0, 20.0, 12.0)}
        rooms[f"hallway_{level}/0"] = {"shape": shapely.box(0.0, 12.0, 10.0, 16.0)}
        rooms[f"bedroom_{level}/0"] = {"shape": shapely.box(10.0, 12.0, 20.0, 16.0)}

        doors[f"elevator-landing-door_{level}/0"] = {
            "shape": shapely.LineString([(2.5, 0.75), (2.5, 2.25)]),
            "level": level,
            "semantic": "elevator_landing",
            "elevator_id": "elevator_0",
        }
        doors[f"lobby-door_{level}/0"] = {
            "shape": shapely.LineString([(8.0, 0.75), (8.0, 2.25)]),
            "level": level,
        }
        doors[f"stair-door_{level}/0"] = {
            "shape": shapely.LineString([(8.0, 6.0), (8.0, 7.5)]),
            "level": level,
        }
        doors[f"hall-living-door_{level}/0"] = {
            "shape": shapely.LineString([(8.5, 12.0), (10.0, 12.0)]),
            "level": level,
        }
        doors[f"bedroom-door_{level}/0"] = {
            "shape": shapely.LineString([(12.0, 12.0), (13.5, 12.0)]),
            "level": level,
        }

        if level == 0:
            entrances["entrance_0/0"] = {
                "shape": shapely.LineString([(13.0, 0.0), (14.5, 0.0)]),
                "level": 0,
            }

    return {
        "schema_version": 2,
        "rooms": rooms,
        "doors": doors,
        "entrance": entrances,
        "opens": {},
        "interiors": {},
        "windows": {},
    }


def fixed_four_story_elevator(factory_seed):
    del factory_seed
    return make_elevator_floor_plan(4)


def fixed_eight_story_elevator(factory_seed):
    del factory_seed
    return make_elevator_floor_plan(8)
