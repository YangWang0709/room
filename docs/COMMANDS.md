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

## Run GarbageCollect Attribution Timing

Use this when the question is which factory or node group name family causes
`bpy.data.node_groups` remove cost:

```bash
INFINIGEN_PROFILE_TIMING=1 INFINIGEN_PROFILE_GC=1 INFINIGEN_PROFILE_ASSET_FACTORY=1 timeout 600s python -m infinigen_examples.generate_indoors \
  --seed 0 \
  --task coarse \
  --output_folder outputs/profile_gc_attribution/coarse \
  -g fast_solve.gin \
  -p compose_indoors.terrain_enabled=False \
     home_room_constraints.has_fewer_rooms=False \
     restrict_solving.solve_max_rooms=10
```

Analyze the resulting CSV:

```bash
python scripts/analyze_gc_timing.py \
  outputs/profile_gc_attribution/coarse/infinigen_gc_timing.csv
```

The analyzer reports:

- `node_groups` remove duration by `generator_class`
- `node_groups` removed count by `generator_class`
- removed node group name prefix totals
- slowest `node_groups` remove rows with `context_id`, `generator_class`,
  remove counts, target sizes, top prefixes, and name samples

Current sample output:

```text
outputs/profile_gc_attribution/coarse/infinigen_gc_timing.csv
```

The 2026-06-19 attribution sample produced 4,741 CSV lines including the
header. `node_groups` remove duration was 185.030s. The top factory was
`LargeShelfFactory` with 139.219s and 5,661 removed node groups. Top repeated
prefixes were `nodegroup_tagged_cube`, `nodegroup_division_board`, and
`nodegroup_screw_head`.

Use this attribution before designing an optimization. If a few factories or
prefixes dominate, inspect those factories' `create_asset` and node tree
generation first. Prefer precise reuse, caching, or reducing repeated node
group creation over broad deferred cleanup. Any optimization must remain
opt-in until same seed/gin/task A/B passes.

## Run LargeShelf Node Group Timing

Enable `LargeShelfFactory` shelf node group creation timing:

```bash
INFINIGEN_PROFILE_SHELF_NODEGROUPS=1 python -m infinigen_examples.generate_indoors \
  --seed 0 \
  --task coarse \
  --output_folder outputs/profile_shelf_nodegroups_seed0/coarse \
  -g fast_solve.gin \
  -p compose_indoors.terrain_enabled=False \
     home_room_constraints.has_fewer_rooms=False \
     restrict_solving.solve_max_rooms=10 \
     populate_doors.door_chance=0
```

The timing CSV is written under the solver output folder when available:

```text
<output_folder>/infinigen_shelf_nodegroup_timing.csv
```

Analyze it with:

```bash
python scripts/analyze_shelf_nodegroups.py \
  outputs/profile_shelf_nodegroups_seed0/coarse/infinigen_shelf_nodegroup_timing.csv
```

The analyzer reports prefix call counts, total and mean duration, per-spawn
node group counts, repeated-template signals, and, when present, reuse cache
hits and misses.

## Run LargeShelf Child Reuse Short A/B

The first `LargeShelfFactory` child node group reuse experiment is opt-in.
Default behavior is unchanged unless this variable is set:

```bash
INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1
```

The first reuse set is limited to:

```text
nodegroup_screw_head
nodegroup_side_board
nodegroup_bottom_board
nodegroup_back_board
```

Do not use this switch to imply that top-level `geometry_nodes`,
`nodegroup_division_board`, or `nodegroup_tagged_cube` are reused. Those stay
uncached because of per-object material/array defaults and tag attribute risk.

Baseline short timing sample:

```bash
INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1 \
INFINIGEN_PROFILE_SHELF_NODEGROUPS=1 \
timeout 900s python -m infinigen_examples.generate_indoors \
  --seed 0 \
  --task coarse \
  --output_folder outputs/profile_shelf_reuse_ab/baseline/coarse \
  -g fast_solve.gin \
  -p compose_indoors.terrain_enabled=False \
     home_room_constraints.has_fewer_rooms=False \
     restrict_solving.solve_max_rooms=10 \
     populate_doors.door_chance=0
```

Candidate short timing sample:

```bash
INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1 \
INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1 \
INFINIGEN_PROFILE_SHELF_NODEGROUPS=1 \
timeout 900s python -m infinigen_examples.generate_indoors \
  --seed 0 \
  --task coarse \
  --output_folder outputs/profile_shelf_reuse_ab/candidate/coarse \
  -g fast_solve.gin \
  -p compose_indoors.terrain_enabled=False \
     home_room_constraints.has_fewer_rooms=False \
     restrict_solving.solve_max_rooms=10 \
     populate_doors.door_chance=0
```

Analyze both CSVs:

```bash
python scripts/analyze_shelf_nodegroups.py \
  outputs/profile_shelf_reuse_ab/baseline/coarse/infinigen_shelf_nodegroup_timing.csv

python scripts/analyze_shelf_nodegroups.py \
  outputs/profile_shelf_reuse_ab/candidate/coarse/infinigen_shelf_nodegroup_timing.csv
```

The 2026-06-21 short A/B timed out on both sides at 900s, as intended for a
bounded sample. Both CSVs had 5,918 data rows and 163 `LargeShelfFactory`
spawns. Candidate cache hit rate was 96.744%, actual node groups created
dropped from 5,918 to 3,363, and target-prefix duration dropped from 21.417s
to 0.538s. Treat this as timing evidence only, not as a quality gate.

Next quality validation should keep:

```text
INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1
INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1
restrict_solving.solve_max_rooms=10
populate_doors.door_chance=0
```

Do not run concurrent generation for this validation. Do not commit generated
outputs, CSVs, `.blend`, `.usd`, `.usdc`, `.zip`, or `.prof` files.

## Run Node Group Batch Remove Equivalence A/B

The node group batch remove path is an opt-in single-scene experiment. Default
behavior is unchanged unless this variable is explicitly set for the candidate:

```text
INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1
```

Run the full same seed/gin/task 10-room A/B without heavy timing
instrumentation:

```bash
EXPERIMENT_TIMEOUT_SECONDS=14400 \
bash scripts/run_gc_batch_remove_equivalence.sh
```

On the host, if the active `python` does not have `bpy`, point the script at
the Infinigen conda interpreter:

```bash
PYTHON_BIN=/home/ubuntu22/miniconda3/envs/infinigen/bin/python \
EXPERIMENT_TIMEOUT_SECONDS=14400 \
bash scripts/run_gc_batch_remove_equivalence.sh
```

The script runs:

- baseline without `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS`:
  `outputs/gc_batch_remove_equiv/baseline/coarse`
- candidate with `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1`:
  `outputs/gc_batch_remove_equiv/candidate_batch/coarse`

Both use seed `0`, task `coarse`, `fast_solve.gin`, and these overrides:

```text
compose_indoors.terrain_enabled=False
home_room_constraints.has_fewer_rooms=False
restrict_solving.solve_max_rooms=10
```

The script explicitly unsets:

```text
INFINIGEN_PROFILE_TIMING
INFINIGEN_PROFILE_GC
INFINIGEN_PROFILE_ASSET_FACTORY
INFINIGEN_PROFILE_BBOX
```

After generation, it runs:

```bash
python scripts/compare_indoor_outputs.py \
  outputs/gc_batch_remove_equiv/baseline/coarse \
  outputs/gc_batch_remove_equiv/candidate_batch/coarse
```

`EXPERIMENT_TIMEOUT_SECONDS` defaults to `14400`. Set it to `0` or an empty
string to disable `timeout`. If either side times out or the compare prints
`NO_COMPARABLE_JSON_FOUND`, the script reports that this is not a complete A/B
and cannot be used as mainline evidence.

Smoke mode:

```bash
EXPERIMENT_SMOKE_SINGLE_ROOM=1 \
EXPERIMENT_TIMEOUT_SECONDS=3600 \
bash scripts/run_gc_batch_remove_equivalence.sh
```

Smoke mode adds `singleroom.gin`, sets
`home_room_constraints.has_fewer_rooms=True`, and sets
`restrict_solving.solve_max_rooms=1`. A single-room PASS validates only the
script and obvious equivalence. It does not prove the 10-room mainline target.

2026-06-19 single-room smoke result: both new scripts completed and
`compare_indoor_outputs.py` printed `FINAL: PASS` with two comparable JSON
files. The wall-clock smoke was effectively flat, baseline `163.339s` versus
candidate `163.462s` (`0.999x`), with no traceback, OOM, kill, or segmentation
fault observed. Treat this as harness validation only.

## Run Node Group Batch Remove Wall-Clock A/B

Run the same baseline and candidate without heavy timing, recording wall time
and max RSS:

```bash
EXPERIMENT_TIMEOUT_SECONDS=14400 \
bash scripts/run_gc_batch_remove_walltime.sh
```

Host conda example:

```bash
PYTHON_BIN=/home/ubuntu22/miniconda3/envs/infinigen/bin/python \
EXPERIMENT_TIMEOUT_SECONDS=14400 \
bash scripts/run_gc_batch_remove_walltime.sh
```

The script writes:

```text
outputs/gc_batch_remove_walltime/summary.txt
outputs/gc_batch_remove_walltime/baseline.time.txt
outputs/gc_batch_remove_walltime/candidate_batch.time.txt
outputs/gc_batch_remove_walltime/compare.log
```

It records:

- baseline and candidate exit code
- shell-measured wall time
- `/usr/bin/time -v` max RSS when available
- `compare_indoor_outputs.py` result
- explicit timeout or `NO_COMPARABLE_JSON_FOUND` warnings

Smoke mode is available with:

```bash
EXPERIMENT_SMOKE_SINGLE_ROOM=1 \
EXPERIMENT_TIMEOUT_SECONDS=3600 \
bash scripts/run_gc_batch_remove_walltime.sh
```

Treat wall-clock speedup as accepted evidence only when both 10-room runs
complete and `compare_indoor_outputs.py` prints `FINAL: PASS`.

## Run Node Group Batch Remove Profiling Experiment

This older script is for GC/profile timing attribution, not no-instrumentation
wall-clock validation. It enables heavy timing and writes GC CSVs.

Run the sequential baseline and candidate profiling smoke:

```bash
EXPERIMENT_TIMEOUT_SECONDS=1200 bash scripts/run_gc_batch_remove_experiment.sh
```

On the host, if the active `python` does not have `bpy`, point the script at
the Infinigen conda interpreter:

```bash
PYTHON_BIN=/home/ubuntu22/miniconda3/envs/infinigen/bin/python \
EXPERIMENT_TIMEOUT_SECONDS=1200 \
bash scripts/run_gc_batch_remove_experiment.sh
```

The script runs:

- baseline without `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS`:
  `outputs/gc_batch_remove_ab/baseline/coarse`
- candidate with `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1`:
  `outputs/gc_batch_remove_ab/candidate_batch/coarse`

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
  outputs/gc_batch_remove_ab/baseline/coarse \
  outputs/gc_batch_remove_ab/candidate_batch/coarse
```

If either side times out, the output is only a smoke/profile sample, not a
complete A/B equivalence result. If the compare prints
`NO_COMPARABLE_JSON_FOUND`, the candidate must not be mainlined.

Analyze the GC timing files:

```bash
python scripts/analyze_gc_timing.py \
  outputs/gc_batch_remove_ab/baseline/coarse/infinigen_gc_timing.csv

python scripts/analyze_gc_timing.py \
  outputs/gc_batch_remove_ab/candidate_batch/coarse/infinigen_gc_timing.csv
```

The 2026-06-19 smoke timed out on both sides and produced no comparable JSON.
It still showed a strong timing signal: baseline partial `node_groups`
remove_duration was 366.131s, while the candidate partial was 46.350s with
15,758 node groups removed via `batch_remove`. Treat that as profiling evidence
only until a complete same seed/gin/task A/B passes.

Do not use this script for concurrent generation or throughput benchmarking.
Do not change `manage_jobs.num_concurrent` for this experiment.

## Run Node Group GC Throttling A/B Experiment

The node group cleanup throttle is an opt-in experiment. Default behavior is
unchanged when `INFINIGEN_GC_NODE_GROUP_INTERVAL` is unset or set to `1`.

The interval=20 smoke on 2026-06-19 is not a valid speedup. Both runs timed
out, no comparable JSON was produced, and raw `node_groups_remove` increased
from 369.071s to 443.414s because deferred cleanup produced large burst
removes. Do not continue by simply increasing this interval.

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
