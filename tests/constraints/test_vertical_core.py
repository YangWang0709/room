import shapely

from infinigen.core.constraints.example_solver.room.vertical_core import (
    VerticalCorePlacement,
    VerticalCoreRegistry,
    VerticalCoreSpec,
    core_candidate_segments,
    place_vertical_cores,
)
from infinigen.core.constraints.constraint_language.constants import RoomConstants
from infinigen.core.constraints.example_solver.room.base import RoomGraph, room_name
from infinigen.core.constraints.example_solver.room.graph import GraphMaker
from infinigen.core.constraints.example_solver.room.segment import SegmentMaker
from infinigen.core.constraints.example_solver.room.solver import FloorPlanMoves
from infinigen.core.tags import Semantics


def _spec(core_id, instance, levels, served=None, **kwargs):
    return VerticalCoreSpec(
        core_id=core_id,
        room_type=Semantics.StaircaseRoom,
        placeholder_tag=Semantics.Staircase,
        instance_index=instance,
        width=kwargs.pop("width", 2.0),
        depth=kwargs.pop("depth", 2.0),
        span_levels=tuple(levels),
        served_levels=tuple(levels if served is None else served),
        overlap_threshold=kwargs.pop("overlap_threshold", 0.9),
        clearance=kwargs.pop("clearance", 0.5),
        lobby_depth=kwargs.pop("lobby_depth", 1.5),
        door_width=kwargs.pop("door_width", 1.0),
        **kwargs,
    )


def test_arbitrary_floor_count_and_express_service():
    contours = [shapely.box(0, 0, 20, 16) for _ in range(16)]
    registry = place_vertical_cores(
        contours,
        [_spec("elevator_0", 0, range(16), served=(0, 4, 8, 12, 15))],
        seed=302,
    )

    placement = registry["elevator_0"]
    assert placement.spec.span_levels == tuple(range(16))
    assert placement.spec.served_levels == (0, 4, 8, 12, 15)
    assert all(registry.for_level(i) == (placement,) for i in range(16))
    registry.validate(contours)


def test_multiple_cores_are_deterministic_and_clear():
    contours = [shapely.box(0, 0, 24, 18) for _ in range(8)]
    specs = [
        _spec("stairs_0", 0, range(8), width=3.0, depth=4.0),
        _spec("elevator_0", 1, range(8), width=2.4, depth=2.2),
    ]

    first = place_vertical_cores(contours, specs, seed=17)
    second = place_vertical_cores(contours, specs, seed=17)

    assert [p.polygon.wkt for p in first] == [p.polygon.wkt for p in second]
    assert [p.door_side for p in first] == [p.door_side for p in second]
    assert (
        not first["stairs_0"]
        .polygon.buffer(0.5)
        .intersects(first["elevator_0"].polygon)
    )


def test_core_must_fit_every_spanned_floor():
    contours = [
        shapely.box(0, 0, 20, 20),
        shapely.box(3, 2, 18, 18),
        shapely.box(6, 4, 16, 16),
        shapely.box(7, 5, 15, 15),
    ]
    registry = place_vertical_cores(
        contours,
        [_spec("elevator_0", 0, range(4))],
        seed=9,
    )
    placement = registry["elevator_0"]
    assert all(contour.covers(placement.required_polygon) for contour in contours)


def test_candidate_sets_follow_each_placeholder_only():
    contours = [shapely.box(0, 0, 20, 12) for _ in range(4)]
    registry = place_vertical_cores(
        contours,
        [
            _spec("stairs_0", 0, range(4)),
            _spec("elevator_0", 1, range(4)),
        ],
        seed=55,
    )
    stair = registry["stairs_0"]
    elevator = registry["elevator_0"]
    segments = {
        0: stair.polygon.buffer(0.2, join_style="mitre"),
        1: elevator.polygon.buffer(0.2, join_style="mitre"),
        2: shapely.box(0, 0, 1, 1),
    }

    assert core_candidate_segments(segments, stair) == {0}
    assert core_candidate_segments(segments, elevator) == {1}


def test_manifest_conversion_contains_no_shapely_objects():
    contours = [shapely.box(0, 0, 20, 16) for _ in range(4)]
    registry = place_vertical_cores(
        contours,
        [_spec("elevator_0", 0, range(4))],
        seed=302,
    )

    manifest = registry.to_manifest_dict()
    assert manifest[0]["span_levels"] == [0, 1, 2, 3]
    assert isinstance(manifest[0]["footprint_xy"], list)
    assert all(isinstance(point, list) for point in manifest[0]["footprint_xy"])


def _basic_room_graph(level):
    return RoomGraph(
        [[1], [0]],
        [
            room_name(Semantics.LivingRoom, level),
            room_name(Semantics.Exterior, level),
        ],
        entrance=0,
    )


def test_graph_injects_one_shaft_and_lobby_per_enabled_elevator():
    constants = RoomConstants(
        n_stories=8,
        elevator_enabled=True,
        n_elevators=2,
        fixed_contour=False,
    )
    maker = GraphMaker.__new__(GraphMaker)
    maker.constants = constants
    maker.level = 6

    graph = maker.add_vertical_core_nodes(_basic_room_graph(6))

    assert len(graph[Semantics.ElevatorRoom]) == 2
    assert len(graph[Semantics.ElevatorLobby]) == 2
    assert graph.names[-1] == room_name(Semantics.Exterior, 6)
    assert set(graph.valid_ns) == set(range(len(graph)))
    for index in range(2):
        shaft = graph.names.index(room_name(Semantics.ElevatorRoom, 6, index))
        lobby = graph.names.index(room_name(Semantics.ElevatorLobby, 6, index))
        living = graph.names.index(room_name(Semantics.LivingRoom, 6))
        assert lobby in graph.ns[shaft]
        assert shaft in graph.ns[lobby]
        assert living in graph.ns[lobby]


def test_express_pass_through_floor_has_no_landing_lobby():
    constants = RoomConstants(
        n_stories=8,
        elevator_enabled=True,
        elevator_served_levels=(0, 3, 7),
        fixed_contour=False,
    )
    maker = GraphMaker.__new__(GraphMaker)
    maker.constants = constants
    maker.level = 4

    graph = maker.add_vertical_core_nodes(_basic_room_graph(4))

    assert len(graph[Semantics.ElevatorRoom]) == 1
    assert len(graph[Semantics.ElevatorLobby]) == 0


def test_disabled_graph_is_the_same_object_and_consumes_no_structure():
    constants = RoomConstants(
        n_stories=4,
        elevator_enabled=False,
        fixed_contour=False,
    )
    maker = GraphMaker.__new__(GraphMaker)
    maker.constants = constants
    maker.level = 3
    original = _basic_room_graph(3)

    assert maker.add_vertical_core_nodes(original) is original


def test_injected_graph_remains_compatible_with_segment_assignment():
    constants = RoomConstants(
        n_stories=2,
        elevator_enabled=True,
        fixed_contour=False,
    )
    constants.unit = 1.0
    constants.segment_margin = 0.1
    graph_maker = GraphMaker.__new__(GraphMaker)
    graph_maker.constants = constants
    graph_maker.level = 0
    graph = graph_maker.add_vertical_core_nodes(_basic_room_graph(0))

    spec = VerticalCoreSpec(
        core_id="elevator_0",
        room_type=Semantics.ElevatorRoom,
        placeholder_tag=Semantics.ElevatorShaft,
        instance_index=0,
        width=1.0,
        depth=1.0,
        span_levels=(0,),
        served_levels=(0,),
        lobby_room_type=Semantics.ElevatorLobby,
        overlap_threshold=0.98,
        lobby_overlap_threshold=0.98,
        clearance=0.0,
        lobby_depth=1.0,
        door_width=0.8,
    )
    placement = VerticalCorePlacement(spec, shapely.box(2, 0, 3, 1), "-x")
    registry = VerticalCoreRegistry((placement,))

    segments = {
        0: shapely.box(0, 0, 1, 1),
        1: shapely.box(1, 0, 2, 1),
        2: shapely.box(2, 0, 3, 1),
    }
    shared_edges = {
        0: {1: shapely.LineString([(1, 0), (1, 1)])},
        1: {
            0: shapely.LineString([(1, 0), (1, 1)]),
            2: shapely.LineString([(2, 0), (2, 1)]),
        },
        2: {1: shapely.LineString([(2, 0), (2, 1)])},
    }
    maker = SegmentMaker.__new__(SegmentMaker)
    maker.constants = constants
    maker.level = 0
    maker.contour = shapely.box(0, 0, 3, 1)
    maker.graph = graph
    maker.filter_segments = lambda vertical_cores=None: (segments, shared_edges)

    state = maker.build_segments(vertical_cores=registry)

    assert state is not None
    assert state.objs[room_name(Semantics.ElevatorRoom, 0)].polygon.equals(segments[2])
    assert state.objs[room_name(Semantics.ElevatorLobby, 0)].polygon.equals(segments[1])


def test_segment_seeding_reserves_stairs_shaft_and_lobby_exactly():
    constants = RoomConstants(
        n_stories=2,
        elevator_enabled=True,
        fixed_contour=False,
    )
    constants.unit = 0.5
    constants.segment_margin = 0.1
    stair_spec = _spec(
        "stairs_0",
        0,
        range(2),
        width=3.0,
        depth=4.0,
        lobby_depth=0.0,
    )
    elevator_spec = VerticalCoreSpec(
        core_id="elevator_0",
        room_type=Semantics.ElevatorRoom,
        placeholder_tag=Semantics.ElevatorShaft,
        instance_index=0,
        width=2.5,
        depth=2.5,
        span_levels=(0, 1),
        served_levels=(0, 1),
        lobby_room_type=Semantics.ElevatorLobby,
        lobby_depth=2.0,
        door_width=1.1,
    )
    stair = VerticalCorePlacement(stair_spec, shapely.box(1, 1, 4, 5), "-y")
    elevator = VerticalCorePlacement(elevator_spec, shapely.box(7, 1, 9.5, 3.5), "+y")
    registry = VerticalCoreRegistry((stair, elevator))

    maker = SegmentMaker.__new__(SegmentMaker)
    maker.constants = constants
    maker.level = 0
    maker.contour = shapely.box(0, 0, 12, 10)
    segments, protected = maker._seed_vertical_core_segments(registry)

    assert protected == {0, 1, 2}
    assert segments[0].equals(stair.polygon)
    assert segments[1].equals(elevator.polygon)
    assert segments[2].equals(elevator.lobby_polygon)
    assert (
        abs(shapely.union_all(list(segments.values())).area - maker.contour.area) < 1e-8
    )


def test_all_vertical_core_rooms_and_placeholders_are_rigid():
    contours = [shapely.box(0, 0, 12, 10) for _ in range(2)]
    stair_spec = _spec("stairs_0", 0, range(2), lobby_depth=0.0)
    elevator_spec = VerticalCoreSpec(
        core_id="elevator_0",
        room_type=Semantics.ElevatorRoom,
        placeholder_tag=Semantics.ElevatorShaft,
        instance_index=0,
        width=2.5,
        depth=2.5,
        span_levels=(0, 1),
        served_levels=(0, 1),
        lobby_room_type=Semantics.ElevatorLobby,
        lobby_depth=2.0,
        door_width=1.1,
    )
    registry = place_vertical_cores(
        contours,
        [stair_spec, elevator_spec],
        seed=91,
    )
    constants = RoomConstants(
        n_stories=2,
        elevator_enabled=True,
        fixed_contour=False,
    )

    moves = FloorPlanMoves(constants, registry)

    assert room_name(Semantics.ElevatorRoom, 0) in moves.protected_room_keys
    assert room_name(Semantics.ElevatorLobby, 0) in moves.protected_room_keys
    assert room_name(Semantics.StaircaseRoom, 0) in moves.protected_room_keys
    assert room_name(Semantics.Staircase, 0) in moves.protected_placeholder_keys
