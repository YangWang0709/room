# Copyright (C) 2026, Princeton University.
# This source code is licensed under the BSD 3-Clause license found in the
# LICENSE file in the root directory of this source tree.

"""Configurable elevator asset package.

The controller/model exports below are pure Python.  Blender symbols are loaded
only when requested, keeping state-machine consumers independent of ``bpy``.
"""

from .model import (
    ElevatorAnimationPlan,
    ElevatorBuildMode,
    ElevatorConfigurationError,
    ElevatorController,
    ElevatorInterlockError,
    ElevatorPhase,
    ElevatorSnapshot,
    ElevatorSpec,
    ElevatorTiming,
    ElevatorVisualVariant,
    LevelId,
    build_animation_plan,
    sample_visual_variant,
)

_BLENDER_EXPORTS = {
    "BlenderElevatorAsset",
    "ElevatorFactory",
    "animate_elevator_asset",
    "apply_elevator_snapshot",
    "build_elevator_asset",
    "build_elevator_smoke",
}


def __getattr__(name):
    if name not in _BLENDER_EXPORTS:
        raise AttributeError(name)
    from . import blender

    return getattr(blender, name)


def __dir__():
    return sorted(set(globals()).union(_BLENDER_EXPORTS))


__all__ = [
    "BlenderElevatorAsset",
    "ElevatorAnimationPlan",
    "ElevatorBuildMode",
    "ElevatorConfigurationError",
    "ElevatorController",
    "ElevatorFactory",
    "ElevatorInterlockError",
    "ElevatorPhase",
    "ElevatorSnapshot",
    "ElevatorSpec",
    "ElevatorTiming",
    "ElevatorVisualVariant",
    "LevelId",
    "animate_elevator_asset",
    "apply_elevator_snapshot",
    "build_animation_plan",
    "build_elevator_asset",
    "build_elevator_smoke",
    "sample_visual_variant",
]
