# Copyright (C) 2024, Princeton University.
# This source code is licensed under the BSD 3-Clause license found in the LICENSE file in the root directory
# of this source tree.

# Authors:
# - Lingjie Mei: primary author
# - Karhan Kayan: fix constants

from collections import defaultdict

import matplotlib.pyplot as plt
import numpy as np
import shapely
import shapely.plotting
from numpy.random import uniform
from shapely import LineString, union
from shapely.ops import split as split_geometry

from infinigen.assets.utils.shapes import (
    cut_polygon_by_line,
    is_valid_polygon,
    segment_filter,
)
from infinigen.core.constraints import constraint_language as cl
from infinigen.core.constraints.constraint_language.constants import RoomConstants
from infinigen.core.constraints.example_solver.state_def import (
    ObjectState,
    RelationState,
    State,
)
from infinigen.core.tags import Semantics
from infinigen.core.util.math import FixedSeed

from .base import RoomGraph, room_name, room_type
from .utils import shared
from .vertical_core import (
    VerticalCoreRegistry,
    core_candidate_segments,
    lobby_candidate_segments,
)


class SegmentMaker:
    def __init__(
        self,
        factory_seed,
        constants: RoomConstants,
        consgraph,
        contour,
        graph: RoomGraph,
        level,
    ):
        with FixedSeed(factory_seed):
            self.factory_seed = factory_seed
            self.constants = constants
            self.level = level
            self.contour = contour
            self.consgraph = consgraph
            self.graph = graph
            self.n_boxes = int(len(graph) * uniform(1.8, 2.0))

            self.box_ratio = 0.15
            self.divide_box_fn = lambda x: x.area**0.5
            self.n_box_trials = 100

    def build_segments(
        self,
        placeholder=None,
        vertical_cores: VerticalCoreRegistry | None = None,
    ):
        """Build one floor's room segments.

        ``placeholder`` is the legacy single-staircase interface and remains
        untouched for default generation.  New multi-core configurations pass
        ``vertical_cores`` instead; each required room key then receives only
        the candidate segments for its own core instance.
        """

        if placeholder is not None and vertical_cores is not None:
            raise ValueError("Pass either placeholder or vertical_cores, not both")
        seed = np.random.randint(10e7)
        filter_attempts = 0
        while True:
            try:
                with FixedSeed(seed):
                    segments, shared_edges = self.filter_segments(vertical_cores)
                break
            except Exception:
                filter_attempts += 1
                # The legacy path historically retries until a random split is
                # valid.  Elevator-enabled layouts have an outer bounded retry
                # loop, so return control instead of spinning forever on an
                # impossible core/room assignment.
                if vertical_cores is not None and filter_attempts >= 12:
                    return None
            seed += 1
        neighbours_all = {
            k: set(self.constants.filter(se)) for k, se in shared_edges.items()
        }
        exterior_edges = {}
        exterior_neighbours = []
        for k, s in segments.items():
            l = s.boundary
            for ls in shared_edges[k].values():
                l = l.difference(ls)
            if l.length > 0:
                exterior_edges[k] = (
                    shapely.MultiLineString([l]) if isinstance(l, LineString) else l
                )
            else:
                exterior_edges[k] = shapely.MultiLineString([])
            if segment_filter(l, self.constants.segment_margin):
                exterior_neighbours.append(k)
        staircase_candidates = []
        if placeholder is not None:
            for k, s in segments.items():
                if (
                    s.intersection(placeholder).area / placeholder.area
                    > self.constants.staircase_thresh
                ):
                    staircase_candidates.append(k)
            if len(staircase_candidates) == 0:
                return None
        core_candidates = {}
        if vertical_cores is not None:
            for placement in vertical_cores.for_level(self.level):
                key = placement.spec.room_key(self.level)
                candidates = core_candidate_segments(segments, placement)
                if not candidates:
                    return None
                core_candidates[key] = candidates
                lobby_key = placement.spec.lobby_key(self.level)
                if lobby_key is not None:
                    candidates = lobby_candidate_segments(segments, placement)
                    if not candidates:
                        return None
                    core_candidates[lobby_key] = candidates
        exterior_rooms = self.graph.ns[
            self.graph.names.index(room_name(Semantics.Exterior, self.level))
        ]
        unassigned = set(neighbours_all.keys())
        assignment = [0] * len(self.graph)
        valid_ns = self.graph.valid_ns

        def assign(i):
            if i == len(self.graph):
                return assignment
            elif self.graph.names[i] in core_candidates:
                candidates = unassigned.intersection(
                    core_candidates[self.graph.names[i]]
                )
            elif i in self.graph[Semantics.StaircaseRoom]:
                candidates = unassigned.intersection(staircase_candidates)
            elif i in exterior_rooms:
                candidates = unassigned.intersection(exterior_neighbours)
            else:
                candidates = unassigned.copy()
            n_unassigned = len(list(j for j in valid_ns[i] if j > i))
            assigned_neighbours = set(assignment[j] for j in valid_ns[i] if j < i)
            for n in candidates:
                if assigned_neighbours.issubset(neighbours_all[n]):
                    if len(neighbours_all[n].intersection(unassigned)) >= n_unassigned:
                        assignment[i] = n
                        unassigned.remove(n)
                        r = assign(i + 1)
                        if r is not None:
                            return r
                        unassigned.add(n)

        assignment = assign(0)
        if assignment is None:
            return None
        names = {j: self.graph.names[assignment.index(j)] for j in shared_edges}
        st = State()
        for i, r in enumerate(self.graph.names):
            if i in self.graph.invalid_indices:
                continue
            st.objs[r] = ObjectState(
                polygon=self.constants.canonicalize(segments[assignment[i]]),
                relations=[
                    RelationState(cl.SharedEdge(), names[j], value=se)
                    for j, se in shared_edges[assignment[i]].items()
                ],
                tags={room_type(r), Semantics.RoomContour},
            )
        exterior = room_name(Semantics.Exterior, self.level)
        relations = [
            RelationState(cl.SharedEdge(), names[j], value=se)
            for j, se in exterior_edges.items()
        ]
        st.objs[exterior] = ObjectState(
            polygon=self.contour,
            relations=relations,
            tags={Semantics.Exterior, Semantics.RoomContour},
        )
        if placeholder is not None:
            pholder = room_name(Semantics.Staircase, self.level)
            st.objs[pholder] = ObjectState(
                polygon=placeholder, tags={Semantics.Staircase}
            )
        if vertical_cores is not None:
            for placement in vertical_cores.for_level(self.level):
                spec = placement.spec
                st.objs[spec.placeholder_key(self.level)] = ObjectState(
                    polygon=placement.polygon,
                    tags={spec.placeholder_tag},
                )
        return st

    def _seed_vertical_core_segments(self, vertical_cores):
        """Partition exact core/lobby footprints before random room splitting.

        Elevator shafts must remain vertically aligned, and the native stair
        asset placer also needs a consistently shaped room on every level.
        Reserving both cores here prevents annealing from leaving only small,
        L-shaped pairwise intersections that no staircase factory can occupy.
        """

        reservations = []
        for placement in vertical_cores.for_level(self.level):
            reservations.append(placement.polygon)
            if placement.spec.lobby_key(self.level) is not None:
                reservations.append(placement.lobby_polygon)
        if not reservations:
            return {0: self.contour}, set()

        for reservation in reservations:
            bounds_box = shapely.box(*reservation.bounds)
            if reservation.symmetric_difference(bounds_box).area > 1e-7:
                raise ValueError("Vertical-core seeding currently requires rectangles")

        pieces = [self.contour]
        minx, miny, maxx, maxy = self.contour.bounds
        margin = max(maxx - minx, maxy - miny, 1.0) + 1.0
        x_cuts = sorted(
            {
                coordinate
                for reservation in reservations
                for coordinate in (reservation.bounds[0], reservation.bounds[2])
                if minx + 1e-8 < coordinate < maxx - 1e-8
            }
        )
        y_cuts = sorted(
            {
                coordinate
                for reservation in reservations
                for coordinate in (reservation.bounds[1], reservation.bounds[3])
                if miny + 1e-8 < coordinate < maxy - 1e-8
            }
        )
        lines = [
            LineString([(x, miny - margin), (x, maxy + margin)]) for x in x_cuts
        ] + [LineString([(minx - margin, y), (maxx + margin, y)]) for y in y_cuts]
        for line in lines:
            split_pieces = []
            for piece in pieces:
                result = split_geometry(piece, line)
                split_pieces.extend(
                    geometry
                    for geometry in result.geoms
                    if geometry.geom_type == "Polygon" and geometry.area > 1e-8
                )
            pieces = split_pieces

        claimed = set()
        ordered = []
        for reservation in reservations:
            indices = [
                index
                for index, piece in enumerate(pieces)
                if index not in claimed
                and reservation.buffer(1e-8).covers(piece.representative_point())
                and piece.difference(reservation.buffer(1e-8)).area < 1e-7
            ]
            if not indices:
                raise ValueError("Core partition did not produce its reserved segment")
            merged = shapely.union_all([pieces[index] for index in indices])
            if merged.symmetric_difference(reservation).area > 1e-6:
                raise ValueError("Core partition does not reproduce reserved geometry")
            ordered.append(self.constants.canonicalize(merged))
            claimed.update(indices)

        ordered.extend(
            self.constants.canonicalize(piece)
            for index, piece in enumerate(pieces)
            if index not in claimed
        )
        segments = {index: polygon for index, polygon in enumerate(ordered)}
        return segments, set(range(len(reservations)))

    def divide_segments(self, vertical_cores=None):
        if vertical_cores is None:
            segments = {0: self.contour}
            protected = set()
        else:
            segments, protected = self._seed_vertical_core_segments(vertical_cores)
        self._protected_segment_ids = protected
        for _ in range(self.n_boxes):
            available = [
                (key, value) for key, value in segments.items() if key not in protected
            ]
            if not available:
                break
            keys, values = zip(*available)
            prob = np.array([self.divide_box_fn(v) for v in values])
            for _ in range(self.n_box_trials):
                k = np.random.choice(list(keys), p=prob / prob.sum())
                x, y, xx, yy = segments[k].bounds
                w, h = xx - x, yy - y
                r = uniform(0.25, 0.75)
                line = None
                if w >= h:
                    w_ = self.constants.unit_cast(r * w)
                    bound = max(self.box_ratio * h, self.constants.segment_margin)
                    if w_ >= bound and w - w_ >= bound:
                        line = LineString([(x + w_, -100), (x + w_, 100)])
                else:
                    h_ = self.constants.unit_cast(r * h)
                    bound = max(self.box_ratio * w, self.constants.segment_margin)
                    if h_ >= bound and h - h_ >= bound:
                        line = LineString([(-100, y + h_), (100, y + h_)])
                if line is not None:
                    i = max(segments.keys())
                    s, t = cut_polygon_by_line(segments[k], line)
                    s_ = self.constants.canonicalize(s)
                    t_ = self.constants.canonicalize(t)
                    if (
                        np.abs(s.area - s_.area) < 1e-3
                        and np.abs(t.area - t_.area) < 1e-3
                    ):
                        segments[k], segments[i + 1] = s_, t_
                        break
        return {k: v for k, v in segments.items()}

    def merge_segment(self, segments, shared_edges, attached, i, j):
        assert i != j
        s = self.constants.canonicalize(union(segments[i], segments[j]))
        if not is_valid_polygon(s):
            return
        segments[j] = s
        segments.pop(i)
        shared_edges.pop(i)
        attached.pop(i)
        for k, ses in shared_edges.items():
            if i in ses:
                ses.pop(i)
        for k, ats in attached.items():
            if i in ats:
                ats.remove(i)
        for k, s in segments.items():
            for l, t in segments.items():
                if k != l and (k == j or l == j):
                    se = shared(s, t)
                    shared_edges[k][l] = se
                    if se.length >= self.constants.segment_margin:
                        attached[k].add(l)
                        attached[l].add(k)
        return shared_edges

    def filter_segments(self, vertical_cores=None):
        segments = self.divide_segments(vertical_cores)
        protected = getattr(self, "_protected_segment_ids", set())
        shared_edges = defaultdict(dict)
        attached = defaultdict(set)
        for k, s in segments.items():
            for l, t in segments.items():
                if k < l:
                    se = shared(s, t)
                    shared_edges[k][l] = shared_edges[l][k] = se
                    if se.length >= self.constants.segment_margin:
                        attached[k].add(l)
                        attached[l].add(k)

        while len(segments) > len(self.graph):
            mergeable = [
                key
                for key in shared_edges
                if key not in protected
                and any(
                    candidate not in protected
                    for candidate in self.constants.filter(shared_edges[key], 1e-6)
                )
            ]
            if not mergeable:
                raise ValueError("No non-core segments remain available for merging")
            prob = np.array([1 / (len(attached[c]) + 1) for c in mergeable])
            k = np.random.choice(mergeable, p=prob / prob.sum())
            candidates = [
                candidate
                for candidate in self.constants.filter(shared_edges[k], 1e-6)
                if candidate not in protected
            ]
            prob = np.array(
                [
                    len(attached[c].difference(attached[k])) ** 2 + 0.5
                    for c in candidates
                ]
            )
            n = np.random.choice(candidates, p=prob / prob.sum())
            self.merge_segment(segments, shared_edges, attached, k, n)
        return segments, shared_edges

    def plot(self, segments):
        plt.clf()
        for k, s in segments.items():
            shapely.plotting.plot_polygon(s, color=uniform(0, 1, 3))
        plt.tight_layout()
        plt.show()
