#!/usr/bin/env python3
"""Targeted NatureShelfTrinketsFactory create_asset benchmark."""

from __future__ import annotations

import argparse
import contextlib
import os
import signal
import sys
import time
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

CSV_NAME = "infinigen_nature_shelf_trinkets_timing.csv"
PROFILE_ENV_VAR = "INFINIGEN_PROFILE_NATURE_SHELF_TRINKETS"
CSV_ENV_VAR = "INFINIGEN_NATURE_SHELF_TRINKETS_TIMING_CSV"
GC_TARGET_NAMES = ["objects", "meshes", "textures", "node_groups", "materials"]


def raise_timeout(_signum, _frame):
    raise TimeoutError("sample timed out")


@contextlib.contextmanager
def sample_timeout(seconds: float):
    if seconds <= 0:
        yield
        return

    old_handler = signal.signal(signal.SIGALRM, raise_timeout)
    old_timer = signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)
        if old_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, old_timer[0], old_timer[1])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate isolated NatureShelfTrinketsFactory samples and collect "
            "per-create_asset timing rows."
        )
    )
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--output_folder",
        type=Path,
        default=Path("outputs/bench_nature_shelf_trinkets"),
    )
    parser.add_argument(
        "--sample_timeout_seconds",
        type=float,
        default=300.0,
        help=(
            "Per-sample wall-clock timeout. Use 0 to disable. Timeouts are "
            "recorded as failed timing rows and the benchmark continues."
        ),
    )
    return parser.parse_args()


def live_object(obj, bpy_module) -> bool:
    return obj is not None and getattr(obj, "name", "") in bpy_module.data.objects


def delete_object_tree(root, bpy_module, butil_module) -> None:
    if not live_object(root, bpy_module):
        return
    objects = list(butil_module.iter_object_tree(root))
    for obj in reversed(objects):
        if live_object(obj, bpy_module):
            butil_module.delete(obj)


def benchmark(args: argparse.Namespace) -> int:
    # Import bpy-dependent modules only after argparse so py_compile remains simple
    # and the script can show argument help without Blender side effects.
    import bpy

    from infinigen.assets.objects.elements.nature_shelf_trinkets.generate import (
        NatureShelfTrinketsFactory,
    )
    from infinigen.core.util import blender as butil
    from infinigen.core.util.math import FixedSeed, int_hash

    if args.samples <= 0:
        raise ValueError("--samples must be positive")

    output_folder = args.output_folder
    output_folder.mkdir(parents=True, exist_ok=True)
    csv_path = output_folder / CSV_NAME
    if csv_path.exists():
        csv_path.unlink()

    os.environ[PROFILE_ENV_VAR] = "1"
    os.environ[CSV_ENV_VAR] = str(csv_path)

    butil.clear_scene()

    rng = np.random.default_rng(args.seed)
    gc_targets = [getattr(bpy.data, name) for name in GC_TARGET_NAMES]
    failures = 0
    total_start = time.perf_counter()

    print("NatureShelfTrinketsFactory targeted benchmark")
    print(f"samples: {args.samples}")
    print(f"seed: {args.seed}")
    print(f"output_folder: {output_folder}")
    print(f"timing_csv: {csv_path}")
    print(f"sample_timeout_seconds: {args.sample_timeout_seconds}")

    for sample_index in range(args.samples):
        factory_seed = int(rng.integers(0, 1_000_000_000))
        inst_seed = int(rng.integers(0, 10_000_000))
        factory = NatureShelfTrinketsFactory(factory_seed)
        placeholder = None
        asset = None
        sample_start = time.perf_counter()

        try:
            with butil.GarbageCollect(
                gc_targets,
                caller="bench_nature_shelf_trinkets_factory",
                generator_class="NatureShelfTrinketsFactory",
                factory_seed=factory_seed,
                inst_seed=inst_seed,
            ):
                print(
                    f"sample {sample_index + 1:03d}/{args.samples:03d} "
                    f"factory_seed={factory_seed} inst_seed={inst_seed} "
                    f"base_factory={factory.base_factory.__class__.__name__} "
                    "starting",
                    flush=True,
                )
                placeholder = factory.spawn_placeholder(
                    inst_seed, loc=(0, 0, 0), rot=(0, 0, 0)
                )
                with (
                    sample_timeout(args.sample_timeout_seconds),
                    FixedSeed(int_hash((factory.factory_seed, inst_seed))),
                ):
                    asset = factory.create_asset(inst_seed, placeholder=placeholder)
                delete_object_tree(asset, bpy, butil)
                delete_object_tree(placeholder, bpy, butil)
        except Exception as exc:
            failures += 1
            delete_object_tree(asset, bpy, butil)
            delete_object_tree(placeholder, bpy, butil)
            print(
                f"sample {sample_index + 1:03d}/{args.samples:03d} "
                f"factory_seed={factory_seed} inst_seed={inst_seed} "
                f"failed={exc.__class__.__name__}: {exc}"
            )
        else:
            print(
                f"sample {sample_index + 1:03d}/{args.samples:03d} "
                f"factory_seed={factory_seed} inst_seed={inst_seed} "
                f"base_factory={factory.base_factory.__class__.__name__} "
                f"duration={time.perf_counter() - sample_start:.3f}s"
            )

    butil.garbage_collect(gc_targets, keep_in_use=True)
    print(f"total_duration: {time.perf_counter() - total_start:.3f}s")
    print(f"failures: {failures}")
    print(f"timing_csv: {csv_path}")
    return 0


def main() -> None:
    raise SystemExit(benchmark(parse_args()))


if __name__ == "__main__":
    main()
