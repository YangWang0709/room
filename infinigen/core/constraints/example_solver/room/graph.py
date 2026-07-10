# Copyright (C) 2024, Princeton University.
# This source code is licensed under the BSD 3-Clause license found in the LICENSE file in the root directory of this source tree.

# Authors: Lingjie Mei
import operator
from copy import deepcopy

import gin
import numpy as np
import scipy.special
import shapely
from numpy.random import uniform
from tqdm import tqdm

from infinigen.core.constraints import constraint_language as cl
from infinigen.core.constraints.constraint_language import Problem
from infinigen.core.constraints.evaluator.evaluate import (
    evaluate_problem,
)
from infinigen.core.constraints.example_solver.room.base import (
    RoomGraph,
    room_name,
    room_type,
)
from infinigen.core.constraints.example_solver.room.utils import update_exterior
from infinigen.core.constraints.example_solver.state_def import (
    ObjectState,
    RelationState,
    State,
)
from infinigen.core.tags import Semantics
from infinigen.core.util.math import FixedSeed
from infinigen.core.util.random import log_uniform


@gin.configurable
class GraphMaker:
    def __init__(self, factory_seed, consgraph, level):
        self.factory_seed = factory_seed
        with FixedSeed(factory_seed):
            self.level = level
            self.constants = consgraph.constants
            self.typical_areas = self.get_typical_areas(consgraph)
            consgraph = consgraph.filter("node")
            self.consgraph = Problem(
                {"node": consgraph.constraints["node"]},
                {"node_gen": self.inject(consgraph.constraints["node_gen"])},
                consgraph.constants,
            )
            self.max_samples = 1000
            self.slackness = log_uniform(1.1, 1.3)

    @property
    def semantics_floor(self):
        """Primary floor tag, preserving legacy tags for the first floors."""

        return self.constants.floor_tag(self.level)

    @property
    def floor_tags(self):
        """Dynamic floor index plus any compatible legacy floor semantic."""

        return self.constants.floor_tags(self.level)

    def inject(self, node, on=False):
        match node:
            case cl.in_range(count, low, high, mean) if mean > 0:
                size = high - low
                if size > 0:
                    p = (mean - low) / size
                    return cl.rand(
                        self.inject(count, True),
                        "cat",
                        [0] * low
                        + [
                            p**i * (1 - p) ** (size - i) * scipy.special.comb(size, i)
                            for i in range(size + 1)
                        ],
                    )
                else:
                    assert low == int(low)
                    return cl.rand(
                        self.inject(count, True), "cat", [0] * int(low) + [1]
                    )
            case cl.scene():
                return cl.scene() if on else cl.scene()[-Semantics.New]
            case cl.ForAll(objs, var, pred):
                return cl.SumOver(self.inject(objs), var, self.inject(pred, on))
            case cl.SumOver(objs, var, pred) | cl.MeanOver(objs, var, pred):
                return node.__class__(self.inject(objs), var, self.inject(pred, on))
            case cl.BoolOperatorExpression(operator.and_, operands):
                return cl.ScalarOperatorExpression(operator.add, self.inject(operands))
            case cl.Node():
                first = next(iter(node.__dict__))
                return node.__class__(
                    **{
                        k: self.inject(v, on and k == first)
                        for k, v in node.__dict__.items()
                    }
                )
            case _ if isinstance(node, list):
                return list(self.inject(n, on) for n in node)
            case _ if isinstance(node, dict):
                return {k: self.inject(n, on) for k, n in node.items()}
            case _:
                return node

    def make_graph(self, i):
        with FixedSeed(i):
            while True:
                name = room_name(Semantics.Root, self.level)
                state = State(
                    {
                        name: ObjectState(
                            tags={Semantics.Root, Semantics.RoomContour}.union(
                                self.floor_tags
                            )
                        )
                    }
                )
                for _ in tqdm(range(40), desc=f"Generating graphs for {self.level}: "):
                    unvisited = list(
                        sorted(
                            k
                            for k, obj_st in state.objs.items()
                            if Semantics.Visited not in obj_st.tags
                        )
                    )
                    if len(unvisited) == 0:
                        break
                    n = unvisited[np.random.randint(len(unvisited))]
                    score, _ = evaluate_problem(
                        self.consgraph, state, {}, enable_violated=False
                    )
                    scores = [score]
                    states = [state]
                    for t in list(sorted(self.constants.room_types)) + [
                        Semantics.Entrance,
                        Semantics.Exterior,
                    ]:
                        count = len(list(k for k in state.objs if room_type(k) == t))
                        for i in range(1, 3):
                            st = deepcopy(state)
                            for j in range(i):
                                name = room_name(t, self.level, count + j)
                                st[name] = ObjectState(
                                    tags={
                                        t,
                                        Semantics.RoomContour,
                                        Semantics.New,
                                    }.union(self.floor_tags),
                                    relations=[RelationState(cl.Traverse(), n)],
                                )
                                st[n].relations.append(
                                    RelationState(cl.Traverse(), name)
                                )
                            score, _ = evaluate_problem(
                                self.consgraph, st, {}, enable_violated=False
                            )
                            states.append(st)
                            scores.append(score)
                        scores_ = np.array(scores) - np.min(scores)
                        if np.all(scores_ < 0.01):
                            i = 0
                        else:
                            i = np.random.choice(
                                np.arange(len(scores)),
                                p=np.exp(-scores_) / np.exp(-scores_).sum(),
                            )
                        state = states[i]
                        scores = [scores[i]]
                        states = [state]
                    for k, obj_st in state.objs.items():
                        if Semantics.New in obj_st.tags:
                            obj_st.tags.remove(Semantics.New)
                    if room_type(n) == Semantics.Root:
                        state.objs.pop(n)
                        first = next(iter(state.objs))
                        for k, obj_st in state.objs.items():
                            if k == first:
                                obj_st.relations = [
                                    RelationState(cl.Traverse(), l)
                                    for l in state.objs
                                    if l != first
                                ]
                            else:
                                obj_st.relations = [RelationState(cl.Traverse(), first)]
                    else:
                        state[n].tags.add(Semantics.Visited)
                _, viol = evaluate_problem(self.consgraph, state)
                if viol == 0:
                    return self.add_vertical_core_nodes(self.state2graph(state))

    def add_vertical_core_nodes(self, graph):
        """Inject mandatory shaft/lobby topology after the legacy graph solve.

        Keeping this deterministic post-step outside the stochastic grammar is
        important: disabled generation consumes exactly the original random
        stream, while an enabled elevator is guaranteed rather than merely
        encouraged by room-count scores.
        """

        if not getattr(self.constants, "elevator_enabled", False):
            return graph
        if self.constants.n_stories <= 1:
            return graph

        served = self.constants.elevator_served_levels
        is_served = served is None or self.level in served
        names = list(graph.names)
        children = [list(neighbours) for neighbours in graph.ns]

        public_indices = (
            graph[Semantics.Hallway]
            or graph[Semantics.LivingRoom]
            or graph[Semantics.DiningRoom]
        )
        if not public_indices:
            public_indices = [
                index
                for index, name in enumerate(names)
                if room_type(name) not in {Semantics.Exterior, Semantics.StaircaseRoom}
            ]
        if is_served and not public_indices:
            raise ValueError(
                f"Level {self.level} has no public room for an elevator lobby"
            )

        for elevator_index in range(self.constants.n_elevators):
            shaft_name = room_name(Semantics.ElevatorRoom, self.level, elevator_index)
            if shaft_name in names:
                raise ValueError(f"Duplicate elevator room node {shaft_name!r}")

            if is_served:
                lobby_name = room_name(
                    Semantics.ElevatorLobby, self.level, elevator_index
                )
                public_index = public_indices[elevator_index % len(public_indices)]
                lobby_index = len(names)
                shaft_index = lobby_index + 1
                names.extend((lobby_name, shaft_name))
                children.append([public_index, shaft_index])
                children.append([lobby_index])
                children[public_index].append(lobby_index)
            else:
                names.append(shaft_name)
                children.append([])

        # ``RoomGraph.__len__`` and ``SegmentMaker`` intentionally preserve the
        # legacy invariant that the sole Exterior node is the final entry.  The
        # post-solve core injection above appends valid rooms, so rebuild the
        # index space with Exterior last before handing the graph back to the
        # unchanged segment assignment recursion.
        exterior_indices = [
            index
            for index, name in enumerate(names)
            if room_type(name) == Semantics.Exterior
        ]
        if len(exterior_indices) != 1:
            raise ValueError(
                "A room graph must contain exactly one Exterior node before "
                f"vertical-core injection, got {exterior_indices}"
            )
        exterior_index = exterior_indices[0]
        order = [index for index in range(len(names)) if index != exterior_index]
        order.append(exterior_index)
        old_to_new = {old: new for new, old in enumerate(order)}
        remapped_names = [names[old] for old in order]
        remapped_children = [
            [old_to_new[neighbour] for neighbour in children[old]] for old in order
        ]
        remapped_entrance = (
            None if graph._entrance is None else old_to_new[graph._entrance]
        )
        return RoomGraph(remapped_children, remapped_names, remapped_entrance)

    def state2graph(self, state):
        state = self.merge_exterior(state)
        state, entrance = self.merge_entrance(state)
        names = [k for k in state.objs.keys() if room_type(k) != Semantics.Exterior] + [
            room_name(Semantics.Exterior, self.level)
        ]
        return RoomGraph(
            [[names.index(r.target_name) for r in state[n].relations] for n in names],
            names,
            None if entrance is None else names.index(entrance),
        )

    def merge_exterior(self, state):
        exterior_connected = set()
        for k, obj_st in state.objs.items():
            if room_type(k) == Semantics.Exterior:
                for r in obj_st.relations:
                    exterior_connected.add(r.target_name)
        exterior_name = room_name(Semantics.Exterior, self.level)
        state = State(
            {
                k: obj_st
                for k, obj_st in state.objs.items()
                if room_type(k) != Semantics.Exterior
            }
        )
        for k in exterior_connected:
            state[k].relations = [
                r
                for r in state[k].relations
                if room_type(r.target_name) != Semantics.Exterior
            ]
            state[k].relations.append(RelationState(cl.Traverse(), exterior_name))
        state[exterior_name] = ObjectState(
            tags={Semantics.Exterior, Semantics.RoomContour}.union(self.floor_tags),
            relations=[RelationState(cl.Traverse(), k) for k in exterior_connected],
        )
        return state

    def merge_entrance(self, state):
        entrance_connected = set()
        for k, obj_st in state.objs.items():
            if room_type(k) == Semantics.Entrance:
                for r in obj_st.relations:
                    entrance_connected.add(r.target_name)
        state = State(
            {
                k: obj_st
                for k, obj_st in state.objs.items()
                if room_type(k) != Semantics.Entrance
            }
        )
        for k in entrance_connected:
            state[k].relations = [
                r
                for r in state[k].relations
                if room_type(r.target_name) != Semantics.Entrance
            ]
        if len(entrance_connected) == 0:
            entrance = None
        else:
            entrance = np.random.choice(list(entrance_connected))
            exterior_name = room_name(Semantics.Exterior, self.level)
            state[entrance].relations.append(
                RelationState(cl.Traverse(), exterior_name)
            )
            if exterior_name not in state.objs:
                state[exterior_name] = ObjectState(
                    tags={Semantics.Exterior, Semantics.RoomContour}.union(
                        self.floor_tags
                    )
                )
            state[exterior_name].relations.append(
                RelationState(cl.Traverse(), entrance)
            )
        return state, entrance

    __call__ = make_graph

    def suggest_dimensions(self, graph, width=None, height=None):
        area = (
            sum(
                [
                    self._typical_area(room_type(r))
                    for r in graph.names
                    if room_type(r) != Semantics.Exterior
                ]
            )
            * self.slackness
        )
        if width is None and height is None:
            aspect_ratio = uniform(*self.constants.aspect_ratio_range)
        else:
            aspect_ratio = width / height
        width = self.constants.unit_cast(np.sqrt(area * aspect_ratio).item())
        height = self.constants.unit_cast(np.sqrt(area / aspect_ratio).item())
        return width, height

    def _typical_area(self, semantic):
        if semantic == Semantics.ElevatorRoom:
            return (
                self.constants.elevator_shaft_width
                * self.constants.elevator_shaft_depth
            )
        if semantic == Semantics.ElevatorLobby:
            return (
                self.constants.elevator_shaft_width
                * self.constants.elevator_lobby_depth
            )
        return self.typical_areas[semantic]

    def draw(self, state):
        graph = self.state2graph(state)
        graph.draw()

    def get_typical_areas(self, consgraph):
        consgraph = consgraph.filter("room")
        typical_areas = {}
        undecided = set()
        for t in tqdm(self.constants.room_types, "Computing typical areas: "):
            name = room_name(t, self.level)
            holder = room_name(Semantics.Staircase, self.level)
            exterior = room_name(Semantics.Exterior, self.level)
            state = State(
                {
                    name: ObjectState(
                        tags={Semantics.RoomContour, t}.union(self.floor_tags)
                    ),
                    holder: ObjectState(
                        tags={Semantics.RoomContour, Semantics.Staircase}.union(
                            self.floor_tags
                        )
                    ),
                    exterior: ObjectState(
                        tags={
                            Semantics.RoomContour,
                            Semantics.Exterior,
                            Semantics.Garage,
                        }.union(self.floor_tags),
                        relations=[RelationState(cl.SharedEdge(), name)],
                    ),
                },
                graphs=[RoomGraph([[]], [name], 0)] * (self.level + 1),
            )
            scores = []
            lengths = np.exp(np.linspace(np.log(1.5), np.log(25), 20))
            for l in lengths:
                state.objs[name].polygon = shapely.box(0, 0, l, l)
                state.objs[holder].polygon = shapely.box(-l, -l, 0, 0)
                state.objs[exterior].polygon = shapely.box(-l, -l, 0, 0)
                update_exterior(state, name)
                score, _ = evaluate_problem(consgraph, state)
                scores.append(score)
            scores = np.array(scores)
            selection = (scores - np.min(scores)) < 1
            if np.sum(selection) > len(selection) / 2:
                undecided.add(t)
            else:
                typical_areas[t] = np.exp(np.log(lengths[selection]).mean()) ** 2
        if len(typical_areas) > 0:
            m = np.mean([v for t, v in typical_areas.items()])
        else:
            m = 10
        for t in undecided:
            typical_areas[t] = m
        return typical_areas
