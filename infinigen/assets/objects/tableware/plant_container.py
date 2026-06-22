# Copyright (C) 2024, Princeton University.
# This source code is licensed under the BSD 3-Clause license found in the LICENSE file in the root directory of this source tree.

# Authors: Lingjie Mei
import logging
import time
from pathlib import Path

import bpy
import numpy as np
from numpy.random import uniform

from infinigen.assets.composition import material_assignments
from infinigen.assets.objects.cactus import CactusFactory
from infinigen.assets.objects.monocot import MonocotFactory
from infinigen.assets.objects.mushroom import MushroomFactory
from infinigen.assets.objects.small_plants import (
    FernFactory,
    SnakePlantFactory,
    SpiderPlantFactory,
    SucculentFactory,
)
from infinigen.assets.objects.tableware.pot import PotFactory
from infinigen.assets.utils.decorate import (
    read_edge_center,
    read_edge_direction,
    remove_vertices,
    select_edges,
    subsurf,
)
from infinigen.assets.utils.object import join_objects, new_bbox, origin2lowest
from infinigen.core.placement.factory import AssetFactory
from infinigen.core.util import blender as butil
from infinigen.core.util.math import FixedSeed
from infinigen.core.util import profile_utils
from infinigen.core.util.random import log_uniform, weighted_sample

logger = logging.getLogger(__name__)

PLANT_ASSETS_TIMING_ENV_VAR = "INFINIGEN_PROFILE_PLANT_ASSETS"
PLANT_ASSETS_TIMING_CSV_ENV_VAR = "INFINIGEN_PLANT_ASSETS_TIMING_CSV"
PLANT_ASSETS_TIMING_CSV_NAME = "infinigen_plant_assets_timing.csv"
DEFAULT_PLANT_ASSETS_TIMING_CSV = Path("/tmp") / PLANT_ASSETS_TIMING_CSV_NAME

PLANT_ASSETS_TIMING_FIELDNAMES = [
    "factory_class",
    "factory_seed",
    "inst_seed",
    "placeholder_name",
    "plant_factory_class",
    "pot_factory_class",
    "create_asset_total_duration",
    "geometry_duration",
    "material_duration",
    "pot_create_duration",
    "pot_finalize_duration",
    "dirt_geometry_duration",
    "dirt_material_duration",
    "plant_spawn_duration",
    "plant_finalize_duration",
    "plant_place_duration",
    "join_duration",
    "mesh_count_before",
    "mesh_count_after",
    "material_count_before",
    "material_count_after",
    "texture_count_before",
    "texture_count_after",
    "node_group_count_before",
    "node_group_count_after",
    "object_count_before",
    "object_count_after",
    "image_count_before",
    "image_count_after",
    "created_mesh_count",
    "created_material_count",
    "created_texture_count",
    "created_node_group_count",
    "created_object_count",
    "created_image_count",
    "success",
    "error_type",
]

_PLANT_ASSETS_TIMING_WRITE_FAILED = False


def _profile_plant_assets_enabled() -> bool:
    return profile_utils.env_truthy(PLANT_ASSETS_TIMING_ENV_VAR)


def _plant_assets_timing_csv_path() -> Path:
    return profile_utils.solver_output_csv_path(
        PLANT_ASSETS_TIMING_CSV_NAME,
        DEFAULT_PLANT_ASSETS_TIMING_CSV,
        explicit_env_var=PLANT_ASSETS_TIMING_CSV_ENV_VAR,
    )


def _write_plant_assets_timing_row(row: dict):
    global _PLANT_ASSETS_TIMING_WRITE_FAILED

    if _PLANT_ASSETS_TIMING_WRITE_FAILED:
        return

    path = _plant_assets_timing_csv_path()
    try:
        profile_utils.write_csv_row(path, PLANT_ASSETS_TIMING_FIELDNAMES, row)
    except OSError:
        _PLANT_ASSETS_TIMING_WRITE_FAILED = True
        logger.exception("Failed to write plant asset timing CSV at %s", path)


def _record_plant_duration(row: dict, field: str, start_time: float):
    row[field] = row.get(field, 0.0) + time.perf_counter() - start_time


def _empty_plant_assets_timing_row(factory, i, params, before_sets):
    row = {
        "factory_class": factory.__class__.__name__,
        "factory_seed": getattr(factory, "factory_seed", ""),
        "inst_seed": i,
        "placeholder_name": getattr(params.get("placeholder"), "name", ""),
        "plant_factory_class": factory.plant_factory.__class__.__name__,
        "pot_factory_class": factory.base_factory.__class__.__name__,
        "create_asset_total_duration": 0.0,
        "geometry_duration": 0.0,
        "material_duration": 0.0,
        "pot_create_duration": 0.0,
        "pot_finalize_duration": 0.0,
        "dirt_geometry_duration": 0.0,
        "dirt_material_duration": 0.0,
        "plant_spawn_duration": 0.0,
        "plant_finalize_duration": 0.0,
        "plant_place_duration": 0.0,
        "join_duration": 0.0,
        "success": False,
        "error_type": "",
    }
    profile_utils.add_datablock_before_counts(row, before_sets)
    return row


def _finish_plant_assets_timing_row(row: dict, before_sets):
    profile_utils.add_datablock_after_counts(row, before_sets)
    _write_plant_assets_timing_row(row)


class PlantPotFactory(PotFactory):
    def __init__(self, factory_seed, coarse=False):
        super(PlantPotFactory, self).__init__(factory_seed, coarse)
        with FixedSeed(self.factory_seed):
            self.has_handle = self.has_bar = self.has_guard = False
            self.depth = log_uniform(0.5, 1.0)
            self.r_expand = uniform(1.1, 1.3)
            alpha = uniform(0.5, 0.8)
            self.r_mid = (self.r_expand - 1) * alpha + 1

        self.surface = weighted_sample(material_assignments.decorative_hard)()()


class PlantContainerFactory(AssetFactory):
    plant_factories = [
        CactusFactory,
        MushroomFactory,
        FernFactory,
        SucculentFactory,
        SpiderPlantFactory,
        SnakePlantFactory,
    ]

    def __init__(self, factory_seed, coarse=False):
        super(PlantContainerFactory, self).__init__(factory_seed, coarse)
        with FixedSeed(self.factory_seed):
            self.base_factory = PlantPotFactory(self.factory_seed, coarse)

            fn = np.random.choice(self.plant_factories)

            self.dirt_ratio = uniform(0.7, 0.8)
            self.plant_factory = fn(self.factory_seed)
            self.side_size = self.base_factory.scale * self.base_factory.r_expand
            self.top_size = uniform(0.4, 0.6)

            self.dirt_surface = weighted_sample(material_assignments.potting_soil)()

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        return new_bbox(
            -self.side_size,
            self.side_size,
            -self.side_size,
            self.side_size,
            -0.02,
            self.base_factory.depth * self.base_factory.scale + self.top_size,
        )

    def create_asset(self, i, **params) -> bpy.types.Object:
        if _profile_plant_assets_enabled():
            return self._create_asset_timed(i, **params)

        obj = self.base_factory.create_asset(i=i, **params)
        horizontal = np.abs(read_edge_direction(obj)[:, -1]) < 0.1

        edge_center = read_edge_center(obj)
        z = edge_center[:, -1]
        dirt_z = self.dirt_ratio * self.base_factory.depth * self.base_factory.scale
        idx = np.argmin(np.abs(z - dirt_z) - horizontal * 10)
        radius = np.sqrt((edge_center[idx] ** 2)[:2].sum())

        selection = np.zeros_like(z).astype(bool)
        selection[idx] = True
        with butil.ViewportMode(obj, "EDIT"):
            bpy.ops.mesh.select_mode(type="EDGE")
            select_edges(obj, selection)
            bpy.ops.mesh.loop_multi_select(ring=False)
            bpy.ops.mesh.duplicate_move()
            bpy.ops.mesh.separate(type="SELECTED")

        dirt_ = bpy.context.selected_objects[-1]
        butil.select_none()
        self.base_factory.finalize_assets(obj)
        with butil.ViewportMode(dirt_, "EDIT"):
            bpy.ops.mesh.select_all(action="SELECT")
            bpy.ops.mesh.fill_grid()
        subsurf(dirt_, 3)
        self.dirt_surface.apply(dirt_)
        butil.apply_modifiers(dirt_)

        remove_vertices(dirt_, lambda x, y, z: np.sqrt(x**2 + y**2) > radius * 0.92)
        dirt_.location[-1] -= 0.02

        plant = self.plant_factory.spawn_asset(i=i, loc=(0, 0, 0), rot=(0, 0, 0))
        origin2lowest(plant, approximate=True)
        self.plant_factory.finalize_assets(plant)

        scale = np.min(
            np.array([self.side_size, self.side_size, self.top_size])
            / np.max(np.abs(np.array(plant.bound_box)), 0)
        )
        plant.scale = [scale] * 3
        plant.location[-1] = dirt_z

        obj = join_objects([obj, plant, dirt_])
        return obj

    def _create_asset_timed(self, i, **params) -> bpy.types.Object:
        before_sets = profile_utils.bpy_datablock_name_sets()
        row = _empty_plant_assets_timing_row(self, i, params, before_sets)
        total_start_time = time.perf_counter()

        try:
            step_start_time = time.perf_counter()
            try:
                obj = self.base_factory.create_asset(i=i, **params)
            finally:
                _record_plant_duration(row, "pot_create_duration", step_start_time)

            step_start_time = time.perf_counter()
            try:
                horizontal = np.abs(read_edge_direction(obj)[:, -1]) < 0.1

                edge_center = read_edge_center(obj)
                z = edge_center[:, -1]
                dirt_z = (
                    self.dirt_ratio * self.base_factory.depth * self.base_factory.scale
                )
                idx = np.argmin(np.abs(z - dirt_z) - horizontal * 10)
                radius = np.sqrt((edge_center[idx] ** 2)[:2].sum())

                selection = np.zeros_like(z).astype(bool)
                selection[idx] = True
                with butil.ViewportMode(obj, "EDIT"):
                    bpy.ops.mesh.select_mode(type="EDGE")
                    select_edges(obj, selection)
                    bpy.ops.mesh.loop_multi_select(ring=False)
                    bpy.ops.mesh.duplicate_move()
                    bpy.ops.mesh.separate(type="SELECTED")

                dirt_ = bpy.context.selected_objects[-1]
                butil.select_none()
            finally:
                _record_plant_duration(row, "dirt_geometry_duration", step_start_time)

            step_start_time = time.perf_counter()
            try:
                self.base_factory.finalize_assets(obj)
            finally:
                _record_plant_duration(row, "pot_finalize_duration", step_start_time)

            step_start_time = time.perf_counter()
            try:
                with butil.ViewportMode(dirt_, "EDIT"):
                    bpy.ops.mesh.select_all(action="SELECT")
                    bpy.ops.mesh.fill_grid()
                subsurf(dirt_, 3)
            finally:
                _record_plant_duration(row, "dirt_geometry_duration", step_start_time)

            step_start_time = time.perf_counter()
            try:
                self.dirt_surface.apply(dirt_)
                butil.apply_modifiers(dirt_)
            finally:
                _record_plant_duration(row, "dirt_material_duration", step_start_time)

            step_start_time = time.perf_counter()
            try:
                remove_vertices(
                    dirt_, lambda x, y, z: np.sqrt(x**2 + y**2) > radius * 0.92
                )
                dirt_.location[-1] -= 0.02
            finally:
                _record_plant_duration(row, "dirt_geometry_duration", step_start_time)

            step_start_time = time.perf_counter()
            try:
                plant = self.plant_factory.spawn_asset(
                    i=i, loc=(0, 0, 0), rot=(0, 0, 0)
                )
                origin2lowest(plant, approximate=True)
            finally:
                _record_plant_duration(row, "plant_spawn_duration", step_start_time)

            step_start_time = time.perf_counter()
            try:
                self.plant_factory.finalize_assets(plant)
            finally:
                _record_plant_duration(row, "plant_finalize_duration", step_start_time)

            step_start_time = time.perf_counter()
            try:
                scale = np.min(
                    np.array([self.side_size, self.side_size, self.top_size])
                    / np.max(np.abs(np.array(plant.bound_box)), 0)
                )
                plant.scale = [scale] * 3
                plant.location[-1] = dirt_z
            finally:
                _record_plant_duration(row, "plant_place_duration", step_start_time)

            step_start_time = time.perf_counter()
            try:
                obj = join_objects([obj, plant, dirt_])
            finally:
                _record_plant_duration(row, "join_duration", step_start_time)

            row["geometry_duration"] = (
                row["pot_create_duration"]
                + row["dirt_geometry_duration"]
                + row["plant_spawn_duration"]
                + row["plant_place_duration"]
                + row["join_duration"]
            )
            row["material_duration"] = (
                row["pot_finalize_duration"]
                + row["dirt_material_duration"]
                + row["plant_finalize_duration"]
            )
            row["success"] = True
            return obj
        except BaseException as exc:
            row["error_type"] = exc.__class__.__name__
            raise
        finally:
            row["create_asset_total_duration"] = time.perf_counter() - total_start_time
            _finish_plant_assets_timing_row(row, before_sets)


class LargePlantContainerFactory(PlantContainerFactory):
    plant_factories = [MonocotFactory]

    def __init__(self, factory_seed, coarse=False):
        super(LargePlantContainerFactory, self).__init__(factory_seed, coarse)
        with FixedSeed(self.factory_seed):
            self.base_factory.depth = log_uniform(1.0, 1.5)
            self.base_factory.scale = log_uniform(0.15, 0.25)
            self.side_size = (
                self.base_factory.scale * uniform(1.5, 2.0) * self.base_factory.r_expand
            )
            self.top_size = uniform(1, 1.5)
            # if WALL_HEIGHT - 2*WALL_THICKNESS < 3:
            #     self.top_size = uniform(1.5, WALL_HEIGHT - 2*WALL_THICKNESS)
            # else:
            #     self.top_size = uniform(1.5, 3)
            # print(f"{self.side_size=} {self.top_size=} {WALL_THICKNESS=} {WALL_HEIGHT=}")
