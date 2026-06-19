# Commands

## Enter Container

```bash
docker exec -it infinigen bash
```

## Activate Conda

```bash
source /root/miniconda3/etc/profile.d/conda.sh
conda activate infinigen
cd /opt/infinigen
```

## Run Indoor Coarse Profile

```bash
bash scripts/profile_indoor_solver.sh
```

## Run Indoor Coarse Profile With Solver Timing

```bash
INFINIGEN_PROFILE_TIMING=1 bash scripts/profile_indoor_solver.sh
```

Timing CSV output:

```text
outputs/profile_indoor_baseline/coarse/indoor_solver_timing.csv
```

## Run Bounded Timing Sample

Use this when a full indoor coarse run is too slow:

```bash
INFINIGEN_PROFILE_TIMING=1 timeout 1800s bash scripts/profile_indoor_solver.sh
```

This preserves the normal room count, solve steps, object availability, and gin settings used by `scripts/profile_indoor_solver.sh`. A timeout sample is not a complete profile. Depending on how `timeout` terminates Python, `/tmp/indoors_coarse.prof` may not be written; use `indoor_solver_timing.csv` as the timing source for this workflow.

## Analyze Solver Timing CSV

Default path:

```bash
python scripts/analyze_indoor_timing.py
```

Explicit path:

```bash
python scripts/analyze_indoor_timing.py outputs/profile_indoor_baseline/coarse/indoor_solver_timing.csv
```

The script prints:

- `apply_duration` by `generator_class`
- Addition breakdowns by `generator_class`
- duration totals by `move_type`
- slowest proposal attempts
- failed proposal clusters
- C++ rewrite candidate guidance

## Compare Indoor Coarse Outputs

Use this for baseline versus candidate A/B validation:

```bash
python scripts/compare_indoor_outputs.py outputs/a/coarse outputs/b/coarse
```

With explicit tolerances and a larger diff budget:

```bash
python scripts/compare_indoor_outputs.py \
  --rtol 1e-6 \
  --atol 1e-6 \
  --max-diffs 50 \
  outputs/a/coarse \
  outputs/b/coarse
```

The script recursively pairs `.json` files by relative path, canonicalizes
obvious run-specific fields and output/temp paths, sorts known unordered tag
lists such as `tags`, `child_tags`, and `parent_tags`, reports missing/extra
files, prints per-file `SAME` or `DIFFERENT`, reports numeric `max_abs_diff`,
and ends with `PASS` or `FAIL`.

`NO_COMPARABLE_JSON_FOUND` is a failed validation, not a pass.

## View Profile Top 80

```bash
python scripts/print_indoor_profile.py -n 80
```

The default profile path is:

```text
/tmp/indoors_coarse.prof
```

## Build Standalone Geometry Kernels

The standalone Cython/C++ geometry kernels are optional. If the extension is
not compiled, `infinigen.core.constraints.cpp.geometry_kernels` falls back to
NumPy implementations.

```bash
python -m pip install -e .
```

Disable only the standalone geometry extension build:

```bash
INFINIGEN_DISABLE_GEOMETRY_CPP=True python -m pip install -e .
```

This leaves the NumPy fallback importable:

```bash
python - <<'PY'
from infinigen.core.constraints.cpp import geometry_kernels as g
print("C_EXTENSION_AVAILABLE=", g.C_EXTENSION_AVAILABLE)
PY
```

Run fast unit tests:

```bash
python -m pytest tests/test_geometry_kernels.py -q
```

Run the microbenchmark:

```bash
python scripts/bench_geometry_kernels.py
```

These commands do not run indoor generation and do not connect the kernels to
the solver. Before any future solver-facing opt-in integration, run a same
seed/gin/task A/B comparison with `scripts/compare_indoor_outputs.py`.

## Run BBox Mesh Timing

Enable fine-grained `bbox_mesh_from_hipoly` timing:

```bash
INFINIGEN_PROFILE_BBOX=1 bash scripts/profile_indoor_solver.sh
```

The existing solver timing flag also enables bbox timing:

```bash
INFINIGEN_PROFILE_TIMING=1 INFINIGEN_PROFILE_BBOX=1 bash scripts/profile_indoor_solver.sh
```

When the solver output folder is available, bbox timing is written to:

```text
<output_folder>/infinigen_bbox_timing.csv
```

Outside the solver path, the fallback path is:

```text
/tmp/infinigen_bbox_timing.csv
```

Analyze bbox timing:

```bash
python scripts/analyze_bbox_timing.py /tmp/infinigen_bbox_timing.csv
```

or point it at the run output:

```bash
python scripts/analyze_bbox_timing.py outputs/profile_indoor_baseline/coarse/infinigen_bbox_timing.csv
```

Use the `union_all_bbox_duration / total_duration` share from this script before
considering any opt-in C++ bbox integration.

## Run Asset Factory Spawn Timing

Enable fine-grained `AssetFactory.spawn_asset` timing:

```bash
INFINIGEN_PROFILE_ASSET_FACTORY=1 bash scripts/profile_indoor_solver.sh
```

The existing solver timing flag also enables asset factory timing:

```bash
INFINIGEN_PROFILE_TIMING=1 INFINIGEN_PROFILE_ASSET_FACTORY=1 bash scripts/profile_indoor_solver.sh
```

When the solver output folder is available, asset factory timing is written to:

```text
<output_folder>/infinigen_asset_factory_timing.csv
```

Outside the solver path, the fallback path is:

```text
/tmp/infinigen_asset_factory_timing.csv
```

Analyze asset factory timing:

```bash
python scripts/analyze_asset_factory_timing.py /tmp/infinigen_asset_factory_timing.csv
```

or point it at the run output:

```bash
python scripts/analyze_asset_factory_timing.py outputs/profile_indoor_baseline/coarse/infinigen_asset_factory_timing.csv
```

Fresh-folder bounded sample used for the 2026-06-19 asset factory timing run:

```bash
INFINIGEN_PROFILE_TIMING=1 INFINIGEN_PROFILE_BBOX=1 INFINIGEN_PROFILE_ASSET_FACTORY=1 timeout 600s python -m infinigen_examples.generate_indoors \
  --seed 0 \
  --task coarse \
  --output_folder outputs/profile_asset_factory_current/coarse \
  -g fast_solve.gin \
  -p compose_indoors.terrain_enabled=False \
     home_room_constraints.has_fewer_rooms=False \
     restrict_solving.solve_max_rooms=10
```

Use this timing to decide whether the next behavior-preserving experiment
should inspect `create_asset`, placeholder deletion, placeholder finalization,
or `GarbageCollect` context behavior.

## Run GarbageCollect Target Timing

Enable target-level `garbage_collect` / `GarbageCollect` timing:

```bash
INFINIGEN_PROFILE_GC=1 bash scripts/profile_indoor_solver.sh
```

The existing solver timing flag also enables GC timing:

```bash
INFINIGEN_PROFILE_TIMING=1 INFINIGEN_PROFILE_GC=1 bash scripts/profile_indoor_solver.sh
```

When the solver output folder is available, GC timing is written to:

```text
<output_folder>/infinigen_gc_timing.csv
```

Outside the solver path, the fallback path is:

```text
/tmp/infinigen_gc_timing.csv
```

Analyze GC timing:

```bash
python scripts/analyze_gc_timing.py /tmp/infinigen_gc_timing.csv
```

or point it at the run output:

```bash
python scripts/analyze_gc_timing.py outputs/profile_gc_current/coarse/infinigen_gc_timing.csv
```

Fresh-folder bounded sample used for the 2026-06-19 GC target timing run:

```bash
INFINIGEN_PROFILE_TIMING=1 INFINIGEN_PROFILE_BBOX=1 INFINIGEN_PROFILE_ASSET_FACTORY=1 INFINIGEN_PROFILE_GC=1 timeout 600s python -m infinigen_examples.generate_indoors \
  --seed 0 \
  --task coarse \
  --output_folder outputs/profile_gc_current/coarse \
  -g fast_solve.gin \
  -p compose_indoors.terrain_enabled=False \
     home_room_constraints.has_fewer_rooms=False \
     restrict_solving.solve_max_rooms=10
```

Use this timing to decide whether GC cost is in enter snapshot, exit scan,
remove calls, or a specific `bpy.data` target. Current evidence points to
`bpy.data.node_groups` removal, not `create_asset`, placeholder delete,
`union_all_bbox`, or a C++ kernel candidate.

## Run Node Group GC Throttling A/B Experiment

The node group cleanup throttle is an opt-in experiment. Default behavior is
unchanged when `INFINIGEN_GC_NODE_GROUP_INTERVAL` is unset or set to `1`.

Run the scripted baseline and candidate comparison:

```bash
EXPERIMENT_TIMEOUT_SECONDS=1200 bash scripts/run_gc_node_group_experiment.sh
```

On the host, if the active `python` does not have `bpy`, point the script at
the Infinigen conda interpreter:

```bash
PYTHON_BIN=/home/ubuntu22/miniconda3/envs/infinigen/bin/python \
EXPERIMENT_TIMEOUT_SECONDS=1200 \
bash scripts/run_gc_node_group_experiment.sh
```

The script runs:

- baseline with `INFINIGEN_GC_NODE_GROUP_INTERVAL=1`:
  `outputs/gc_node_group_ab/baseline/coarse`
- candidate with `INFINIGEN_GC_NODE_GROUP_INTERVAL=20`:
  `outputs/gc_node_group_ab/candidate_interval20/coarse`

Both use seed `0`, task `coarse`, `fast_solve.gin`, and these overrides:

```text
compose_indoors.terrain_enabled=False
home_room_constraints.has_fewer_rooms=False
restrict_solving.solve_max_rooms=10
```

Both enable:

```text
INFINIGEN_PROFILE_TIMING=1
INFINIGEN_PROFILE_GC=1
INFINIGEN_PROFILE_ASSET_FACTORY=1
```

After generation, the script runs:

```bash
python scripts/compare_indoor_outputs.py \
  outputs/gc_node_group_ab/baseline/coarse \
  outputs/gc_node_group_ab/candidate_interval20/coarse
```

If either side times out, the output is only a smoke/profile sample, not a
complete A/B equivalence result.

Analyze the GC timing files:

```bash
python scripts/analyze_gc_timing.py \
  outputs/gc_node_group_ab/baseline/coarse/infinigen_gc_timing.csv

python scripts/analyze_gc_timing.py \
  outputs/gc_node_group_ab/candidate_interval20/coarse/infinigen_gc_timing.csv
```

The analyzer reports interval values, skipped and executed node group cleanup
counts, node group duration and remove duration totals, an estimated saved-time
signal, and the maximum observed `node_groups` datablock count.

## Single-Room Coarse Generation

Single-room generation is useful only as a smoke test for scripts and workflow.
It is not evidence that reducing room count is a valid speed optimization.

```bash
python -m infinigen_examples.generate_indoors \
  --seed 0 \
  --task coarse \
  --output_folder outputs/single_room/coarse \
  -g fast_solve.gin \
  -p compose_indoors.terrain_enabled=False \
     home_room_constraints.has_fewer_rooms=True \
     restrict_single_supported_roomtype=True \
     restrict_solving.solve_max_rooms=1
```

## Smoke A/B Comparator Check

Use the same seed, same gin files, same task, and same parameter overrides for
both folders:

```bash
python -m infinigen_examples.generate_indoors \
  --seed 0 \
  --task coarse \
  --output_folder outputs/ab_smoke_a/coarse \
  -g fast_solve.gin \
  -p compose_indoors.terrain_enabled=False \
     home_room_constraints.has_fewer_rooms=True \
     restrict_single_supported_roomtype=True \
     restrict_solving.solve_max_rooms=1

python -m infinigen_examples.generate_indoors \
  --seed 0 \
  --task coarse \
  --output_folder outputs/ab_smoke_b/coarse \
  -g fast_solve.gin \
  -p compose_indoors.terrain_enabled=False \
     home_room_constraints.has_fewer_rooms=True \
     restrict_single_supported_roomtype=True \
     restrict_solving.solve_max_rooms=1

python scripts/compare_indoor_outputs.py \
  outputs/ab_smoke_a/coarse \
  outputs/ab_smoke_b/coarse
```

Do not use this reduced single-room smoke command as the main performance
target. Full indoor coarse A/B must keep the normal room count and solve steps.

## Single-Room USDC Export

Generate or reuse a coarse output folder, then export:

```bash
python -m infinigen.tools.export \
  --input_folder outputs/single_room/coarse \
  --output_folder outputs/single_room/usdc \
  --format usdc \
  --omniverse
```

## Find USD/USDC/USDA Files

```bash
find outputs -type f \( -name '*.usd' -o -name '*.usdc' -o -name '*.usda' \)
```

## Isaac Sim Import Notes

Use the host path when importing into Isaac Sim. Do not copy only a single `.usdc` file if the export produced related assets, textures, or sidecar files; keep the exported folder structure together.
