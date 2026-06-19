# Worklog

## 2026-06-19 - GarbageCollect target timing

### Round Goal

Keep generation behavior unchanged while adding optional target-level timing
inside `infinigen.core.util.blender.GarbageCollect` / `garbage_collect` and
using a bounded sample to identify whether the GC cost is enter snapshot,
exit cleanup scanning, removal, or a specific `bpy.data` target.

### Changes

Added optional GC timing:

- `infinigen/core/util/blender.py`

Enable with either:

```bash
INFINIGEN_PROFILE_GC=1
```

or the existing:

```bash
INFINIGEN_PROFILE_TIMING=1
```

The timing CSV is `infinigen_gc_timing.csv`. It is written to the current
solver output folder when available, otherwise to:

```text
/tmp/infinigen_gc_timing.csv
```

Recorded rows include context-level timing for `GarbageCollect` enter/exit and
target-level timing for `enter_snapshot` and `exit_cleanup`. Target rows record
the `bpy.data` target name, target lengths, scanned count, skipped count,
removed count, remove duration, and total target duration.

The default non-timing `garbage_collect` / `GarbageCollect` behavior remains
unchanged. The timing path preserves target traversal order, `keep_in_use`,
`keep_names`, and `verbose` semantics, preserves remove conditions, and
re-raises original exceptions.

Added GC timing analysis:

- `scripts/analyze_gc_timing.py`

The script summarizes context count, enter versus exit totals, target duration
totals, scan/remove counts, slowest target rows, zero-remove high-duration
rows, and prints guidance for the next behavior-preserving experiment.

### Validation Notes

Ran a bounded 600s GC timing sample using:

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

The sample produced 4821 GC timing rows at:

```text
outputs/profile_gc_current/coarse/infinigen_gc_timing.csv
```

Analyzer result:

- context rows: 501
- target rows: 4320
- target `enter_snapshot` duration: 0.422s
- target `exit_cleanup` duration: 183.972s
- `remove_duration`: 183.378s
- estimated exit scan time excluding remove: 0.594s
- exit cleanup scanned count: 1,528,801
- exit cleanup removed count: 7,843

Target duration totals:

- `node_groups`: 181.131s, with 7,582 removals
- `meshes`: 2.433s, with 261 removals
- `materials`: 0.829s, with 0 removals
- `textures`: 0.000s, with 0 removals

The current dominant GC cost is `exit_cleanup` removal from
`bpy.data.node_groups`. `enter_snapshot` is not dominant, broad scan cost is not
dominant, and zero-remove rows are low-duration in this sample.

### Behavior Guardrails

This round is timing only. It does not optimize the solver, does not reduce
solve steps, does not disable objects, does not change gin configuration, does
not change `GarbageCollect` behavior, and does not change generated content.

The current first measured cause is `AssetFactory.spawn_asset` spending most of
its measured internal time inside `GarbageCollect` context work. In the fresh GC
sample, `garbage_collect_context_duration` was 177.848s of 278.502s
`spawn_asset` time, or 63.859%. `create_asset_duration` was secondary at
99.383s, or 35.685%; `delete_placeholder_duration` was only 0.228s, or 0.082%.

The earlier bbox timing still stands: `union_all_bbox` was only 0.075s out of
334.068s, or 0.023%, so default C++ bbox integration is not the priority.
`GarbageCollect` touches Blender `bpy.data` lifecycle and is not a C++ rewrite
target.

Any future GC scope adjustment, deferred cleanup, less frequent cleanup, batch
cleanup, or target-specific cleanup must start opt-in and pass same
seed/gin/task A/B validation with `scripts/compare_indoor_outputs.py`.

## 2026-06-19 - Asset factory spawn timing

### Round Goal

Keep generation behavior unchanged while adding optional fine-grained timing
inside `AssetFactory.spawn_asset` and using a bounded sample to identify the
next real bottleneck inside factory spawning.

### Changes

Added optional `spawn_asset` timing:

- `infinigen/core/placement/factory.py`

Enable with either:

```bash
INFINIGEN_PROFILE_ASSET_FACTORY=1
```

or the existing:

```bash
INFINIGEN_PROFILE_TIMING=1
```

The timing CSV is `infinigen_asset_factory_timing.csv`. It is written to the
current solver output folder when available, otherwise to:

```text
/tmp/infinigen_asset_factory_timing.csv
```

Recorded fields include generator class, factory seed, instance seed,
user-provided placeholder flag, distance, visibility distance, spawn
placeholder duration, placeholder finalization duration, asset-parameter
duration, `create_asset` duration, parent/transform duration, placeholder
delete duration, `GarbageCollect` context duration, total duration, success, and
error type.

The default non-timing `spawn_asset` path remains unchanged. The timing path
does not change random number usage, does not reorder placeholder or asset
creation, does not reorder object parent/transform/delete operations, and
re-raises original exceptions.

Added asset factory timing analysis:

- `scripts/analyze_asset_factory_timing.py`

The script summarizes generator totals, `create_asset`, placeholder delete,
placeholder finalization, slowest calls, duration totals, and prints guidance on
the dominant stage.

### Validation Notes

Ran a bounded 600s asset factory timing sample using:

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

The sample produced 499 `AssetFactory.spawn_asset` timing rows at:

```text
outputs/profile_asset_factory_current/coarse/infinigen_asset_factory_timing.csv
```

Analyzer result:

- total `spawn_asset` time: 276.641s
- total `garbage_collect_context_duration`: 176.647s, 63.854%
- total `create_asset_duration`: 98.738s, 35.692%
- total `delete_placeholder_duration`: 0.225s, 0.082%
- total `finalize_placeholders_duration`: 0.000s, 0.000%

`garbage_collect_context_duration` is the dominant measured stage inside
`spawn_asset`; `create_asset` is secondary. Placeholder delete and placeholder
finalization are not primary in this sample.

### Behavior Guardrails

This round still does not optimize the solver, does not connect C++ to the
solver path, and does not fix the suspected `union_all_bbox` issue. Bbox timing
showed `union_all_bbox` at only 0.075s of 334.068s, or 0.023%, so default C++
bbox integration is not the priority.

The next optimization candidate should be behavior-preserving work around
`AssetFactory.spawn_asset`, `GarbageCollect`, and factory lifecycle. Any delete
batching, deferred cleanup, or factory bbox/cache experiment must start as an
opt-in path and pass same seed/gin/task A/B output comparison before being
accepted.

## 2026-06-19 - Optional geometry build flag and bbox timing

### Round Goal

Keep the solver behavior unchanged while making the standalone geometry C++
extension optional, adding fine-grained `bbox_mesh_from_hipoly` timing, and
surveying real C++ call sites before any solver integration.

### Changes

Made the standalone geometry extension opt-out at build time:

- `setup.py`

Set:

```bash
INFINIGEN_DISABLE_GEOMETRY_CPP=True python -m pip install -e .
```

to skip `infinigen.core.constraints.cpp.geometry_kernels_cpp` while keeping the
NumPy fallback importable and usable. The default build still attempts to build
the extension. Terrain, bnurbs, and customgt build flags remain separate.

Added optional bbox timing:

- `infinigen/assets/utils/bbox_from_mesh.py`
- `infinigen/core/constraints/example_solver/timing.py`

Enable with either:

```bash
INFINIGEN_PROFILE_BBOX=1
```

or the existing:

```bash
INFINIGEN_PROFILE_TIMING=1
```

The timing CSV is `infinigen_bbox_timing.csv`. It is written to the current
solver output folder when that is available, otherwise to:

```text
/tmp/infinigen_bbox_timing.csv
```

Recorded fields include generator class, factory seed, instance seed,
`use_pholder`, spawn placeholder duration, spawn asset duration,
`union_all_bbox` duration, bbox mesh creation duration, cleanup collection
duration, delete duration, total duration, success, and error type. The timing
path does not replace any bbox logic, does not call C++ kernels, does not change
random number usage, and re-raises original exceptions.

Added bbox timing analysis:

- `scripts/analyze_bbox_timing.py`

The script summarizes generator totals, slowest calls, duration totals, and
prints guidance on whether `union_all_bbox` is large enough to justify an
opt-in C++ bbox experiment.

Added C++ call-site survey:

- `docs/CPP_CALLSITE_SURVEY.md`

The survey records candidate file paths, functions, current logic, estimated
array scale, `bpy` and random-number contact, pure-array suitability, behavior
risk, C++ suitability, and priority.

### Behavior Guardrails

This round still does not optimize the solver and does not connect C++ kernels
to the indoor solver, evaluator, `Addition.apply`, or `union_all_bbox` by
default.

`infinigen/assets/utils/bbox_from_mesh.py::union_all_bbox` still has the
suspected max update issue and remains unfixed:

```python
maxs = pmaxs if maxs is None else np.maximum(pmins, mins)
```

The next decision should be data-driven: use bbox timing to determine whether
time is in `spawn_asset`, `delete`, or `union_all_bbox` before considering an
opt-in C++ bbox integration. If C++ is integrated later, require same
seed/gin/task A/B equivalence validation.

### Validation Notes

Ran a bounded 600s bbox timing sample using:

```bash
INFINIGEN_PROFILE_TIMING=1 INFINIGEN_PROFILE_BBOX=1 timeout 600s python -m infinigen_examples.generate_indoors \
  --seed 0 \
  --task coarse \
  --output_folder outputs/profile_bbox_current/coarse \
  -g fast_solve.gin \
  -p compose_indoors.terrain_enabled=False \
     home_room_constraints.has_fewer_rooms=False \
     restrict_solving.solve_max_rooms=10
```

The sample produced 507 `bbox_mesh_from_hipoly` timing rows at:

```text
outputs/profile_bbox_current/coarse/infinigen_bbox_timing.csv
```

Analyzer result:

- total `bbox_mesh_from_hipoly` time: 334.068s
- total `spawn_asset_duration`: 266.233s, 79.7%
- total `delete_duration`: 57.480s, 17.2%
- total `union_all_bbox_duration`: 0.075s, 0.023%

This sample does not justify prioritizing default C++ integration for
`union_all_bbox` / `bbox_min_max`. The better next target remains
Blender-heavy asset spawning, deletion, and factory lifecycle work.

## 2026-06-19 - Standalone C++ geometry kernel prototypes

### Round Goal

Add the first standalone Cython/C++ numeric kernel prototypes, Python fallback,
unit tests, and microbenchmark without changing indoor solver behavior.

### Changes

Added a pure numeric kernel package:

- `infinigen/core/constraints/cpp/__init__.py`
- `infinigen/core/constraints/cpp/geometry_kernels.py`
- `infinigen/core/constraints/cpp/geometry_kernels.pyx`

Added tests and benchmarking:

- `tests/test_geometry_kernels.py`
- `scripts/bench_geometry_kernels.py`

Updated the existing Cython build list in `setup.py` with:

- `infinigen.core.constraints.cpp.geometry_kernels_cpp`

The new kernels cover:

1. `bbox_min_max(points)`
2. `bbox_union(mins, maxs)`
3. `aabb_overlap_matrix(mins_a, maxs_a, mins_b, maxs_b)`
4. `aabb_contains(outer_min, outer_max, inner_min, inner_max)`

### Behavior Guardrails

This round does not import or call the new kernels from:

- `union_all_bbox`
- `validity.py`
- evaluator modules
- annealing
- `Addition.apply`

The new package does not import `bpy`, does not import `gin`, does not call
random number generators, and does not touch `spawn_asset` or
`spawn_placeholder`.

Boundary contact is treated as inclusive overlap/containment in the standalone
AABB helpers. This is conservative for a future broad-phase because touching
pairs must still reach the existing exact collision/contact code.

`infinigen/assets/utils/bbox_from_mesh.py::union_all_bbox` still has suspicious
logic and remains unchanged:

```python
maxs = pmaxs if maxs is None else np.maximum(pmins, mins)
```

Any fix to that behavior remains separate work requiring a focused sanity test
and same seed/gin/task A/B equivalence validation.

## 2026-06-19 - Equivalence testing and C++ rewrite planning

### Round Goal

Add an A/B equivalence validation harness and document the C++ rewrite plan
without optimizing solver behavior, changing gin configuration, reducing solve
steps, disabling objects, changing random number order, or writing C++ code.

### Changes

Added A/B comparison tooling:

- `scripts/compare_indoor_outputs.py`

Added documentation:

- `docs/EQUIVALENCE_TESTING.md`
- `docs/CPP_REWRITE_CANDIDATES.md`

Updated handoff docs to make the next phase explicit:

- The next stage is behavior-preserving optimization.
- Every optimization must pass A/B equivalence validation first.
- C++ is only for pure computation kernels.
- Reduced content or lower generation quality is not the main acceleration path.
- The best current investigation target remains failed or unaccepted
  `Addition.apply` work from heavy factories.
- Cheap preflight rejection is risky unless it preserves random number order,
  proposal order, accept/reject decisions, and final outputs.

### A/B Comparator

Run:

```bash
python scripts/compare_indoor_outputs.py outputs/a/coarse outputs/b/coarse
```

The script recursively pairs `.json` files by relative path, canonicalizes
obvious run-specific fields and absolute output/temp paths, sorts known
unordered tag lists such as `tags`, `child_tags`, and `parent_tags`, compares
numeric values with `--rtol` and `--atol`, prints first differences, reports
numeric `max_abs_diff`, and ends with `PASS` or `FAIL`.

If no paired comparable JSON exists, it prints:

```text
NO_COMPARABLE_JSON_FOUND
```

That result is a failure, not a pass.

### Smoke A/B

Ran a small single-room coarse smoke A/B inside the existing `infinigen`
container using the same seed, gin, task, and parameter overrides:

```text
outputs/ab_smoke_a/coarse
outputs/ab_smoke_b/coarse
```

Compared on the host with:

```bash
python scripts/compare_indoor_outputs.py \
  outputs/ab_smoke_a/coarse \
  outputs/ab_smoke_b/coarse
```

Result:

```text
matched_json_file_count: 2
SAME MaskTag.json numeric_max_abs_diff=0
SAME solve_state.json numeric_max_abs_diff=0
FINAL: PASS
```

This smoke only validates the comparison workflow. It is not evidence that
reducing room count is an acceptable speed optimization.

### C++ Rewrite Planning

The top P0 candidates are extracted pure numeric kernels, not the current
Blender wrappers:

1. Batch bbox min/max reduction.
2. Batch bbox union.
3. AABB pair overlap matrix.
4. Axis-aligned bounds and containment checks.
5. Batch plane distance and support margin checks.

Do not rewrite `Addition.apply`, `sample_rand_placeholder`, factory
`spawn_asset` / `spawn_placeholder`, material/node generation, solver control
flow, random sampling, proposal order, or accept/reject logic in C++.

### Risk Notes

`infinigen/assets/utils/bbox_from_mesh.py::union_all_bbox` still has suspicious
logic:

```python
maxs = pmaxs if maxs is None else np.maximum(pmins, mins)
```

This round intentionally does not fix it. A fix may change generated geometry
and needs a separate sanity test plus A/B equivalence validation.

## 2026-06-19 13:25 CST - Indoor solver timing CSV analysis

### Round Goal

Confirm the timing instrumentation push, run an indoor coarse timing profile without changing generation behavior, add a CSV analysis helper, and identify behavior-preserving optimization targets.

### Git / Push

Confirmed local branch:

```text
perf/indoor-isaac-speedup
```

Confirmed and pushed:

```text
f1825d95 Add indoor solver timing instrumentation
```

The commit was pushed to:

```text
myroom/perf/indoor-isaac-speedup
```

### Profile Run

Command run inside the container:

```bash
cd /opt/infinigen
source /root/miniconda3/etc/profile.d/conda.sh
conda activate infinigen
INFINIGEN_PROFILE_TIMING=1 timeout 1800s bash scripts/profile_indoor_solver.sh
```

This was a 1800s timeout sample, not a complete profile. It timed out during:

```text
on_floor_freestanding_8 / kitchen_0/0
KitchenIslandFactory
```

Generated timing CSV:

```text
/opt/infinigen/outputs/profile_indoor_baseline/coarse/indoor_solver_timing.csv
outputs/profile_indoor_baseline/coarse/indoor_solver_timing.csv
```

CSV rows: 3061 proposal-attempt rows, plus header.

The cProfile output path was intended to be:

```text
/tmp/indoors_coarse.prof
```

This timeout run did not produce `/tmp/indoors_coarse.prof` in the container. The timing CSV is the source of truth for this round.

### Changes

Added a timing CSV summary helper:

- `scripts/analyze_indoor_timing.py`

Run it with:

```bash
python scripts/analyze_indoor_timing.py
```

or:

```bash
python scripts/analyze_indoor_timing.py path/to/indoor_solver_timing.csv
```

### Key Results

Top `generator_class` by `apply_duration` total:

| Rank | generator_class | count | apply total (s) | mean (s) | max (s) | failed | accepted |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | KitchenIslandFactory | 20 | 294.443 | 14.722 | 22.297 | 16 | 0 |
| 2 | LargeShelfFactory | 153 | 232.303 | 1.518 | 4.444 | 131 | 6 |
| 3 | TableDiningFactory | 63 | 84.746 | 1.345 | 1.469 | 54 | 1 |
| 4 | BeverageFridgeFactory | 44 | 84.472 | 1.920 | 2.097 | 43 | 1 |
| 5 | LargePlantContainerFactory | 585 | 64.825 | 0.111 | 0.301 | 537 | 8 |
| 6 | SimpleBookcaseFactory | 90 | 51.549 | 0.573 | 0.936 | 61 | 7 |
| 7 | (unknown) | 844 | 47.895 | 0.057 | 2.207 | 497 | 186 |
| 8 | SimpleDeskFactory | 112 | 45.202 | 0.404 | 0.721 | 89 | 3 |
| 9 | BathtubFactory | 126 | 43.983 | 0.349 | 0.845 | 125 | 1 |
| 10 | OvenFactory | 56 | 38.936 | 0.695 | 0.773 | 55 | 1 |

Slowest proposal attempts were all `KitchenIslandFactory` additions. Top 10 by `attempt_duration`:

| Rank | iteration | attempt | attempts | attempt (s) | apply (s) | revert (s) | total step (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 4 | 4 | 5 | 22.500 | 22.297 | 0.187 | 72.358 |
| 2 | 5 | 0 | 4 | 22.402 | 22.210 | 0.176 | 63.787 |
| 3 | 3 | 4 | 5 | 21.782 | 21.592 | 0.174 | 88.518 |
| 4 | 3 | 3 | 5 | 20.573 | 20.384 | 0.172 | 88.518 |
| 5 | 7 | 0 | 4 | 18.840 | 18.646 | 0.179 | 55.705 |
| 6 | 3 | 1 | 5 | 18.283 | 18.098 | 0.170 | 88.518 |
| 7 | 3 | 2 | 5 | 18.126 | 17.941 | 0.169 | 88.518 |
| 8 | 5 | 1 | 4 | 16.497 | 16.304 | 0.176 | 63.787 |
| 9 | 4 | 1 | 5 | 16.362 | 16.173 | 0.174 | 72.358 |
| 10 | 7 | 2 | 4 | 16.325 | 16.129 | 0.180 | 55.705 |

Failed proposal clusters by failed attempt count:

| Rank | generator_class | attempts | failed | failure rate | wasted apply (s) |
| --- | --- | ---: | ---: | ---: | ---: |
| 1 | LargePlantContainerFactory | 585 | 537 | 0.918 | 61.787 |
| 2 | (unknown) | 844 | 497 | 0.589 | 39.918 |
| 3 | KitchenCabinetFactory | 205 | 196 | 0.956 | 15.978 |
| 4 | CellShelfFactory | 152 | 134 | 0.882 | 12.558 |
| 5 | LargeShelfFactory | 153 | 131 | 0.856 | 209.884 |
| 6 | BathtubFactory | 126 | 125 | 0.992 | 43.868 |
| 7 | BedFactory | 95 | 92 | 0.968 | 10.582 |
| 8 | SingleCabinetFactory | 121 | 92 | 0.760 | 8.668 |
| 9 | SimpleDeskFactory | 112 | 89 | 0.795 | 33.350 |
| 10 | SimpleBookcaseFactory | 90 | 61 | 0.678 | 36.822 |

Largest wasted apply time clusters:

1. `KitchenIslandFactory` - 257.877s wasted apply
2. `LargeShelfFactory` - 209.884s wasted apply
3. `BeverageFridgeFactory` - 82.742s wasted apply
4. `TableDiningFactory` - 72.458s wasted apply
5. `LargePlantContainerFactory` - 61.787s wasted apply

Move type totals:

| move_type | count | apply (s) | evaluate (s) | revert (s) | accept (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Addition | 2217 | 1112.264 | 109.877 | 178.612 | 0.000 |
| Resample | 114 | 27.863 | 2.396 | 8.204 | 0.662 |
| RelationPlaneChange | 217 | 14.650 | 10.944 | 0.074 | 0.000 |
| ReinitPoseMove | 111 | 3.942 | 14.598 | 0.042 | 0.000 |
| TranslateMove | 261 | 1.363 | 27.042 | 0.069 | 0.000 |

Overall row-level totals:

- `apply_duration`: 1160.159s
- `evaluate_duration`: 172.236s
- `revert_duration`: 187.095s
- `garbage_collect_duration`: 287.308s row-level sum, with repeated step-level rows; max observed 22.470s

### Conclusion

The main bottleneck in this timing sample is `Addition.apply`, especially failed or unaccepted heavy additions. `KitchenIslandFactory` dominates individual slow attempts and wasted apply time. `LargeShelfFactory` is the second largest wasted-apply cluster. Kitchen appliances and dining table proposals also contribute substantial repeated apply cost.

`evaluate_duration`, `revert_duration`, and `garbage_collect_duration` are measurable and can spike, but they are not the primary driver in this CSV. Even the row-level, over-count-prone `garbage_collect_duration` total is below `apply_duration`, and the largest slow attempts are dominated by apply work.

### Next Optimization Direction

Prioritize behavior-preserving optimization before any C++ rewrite:

1. Add cheap preflight rejection for expensive additions before full asset spawn/finalization, starting with `KitchenIslandFactory`, `LargeShelfFactory`, `BeverageFridgeFactory`, `DishwasherFactory`, `OvenFactory`, and `TableDiningFactory`.
2. Cache deterministic placeholder, bbox, and high-poly mesh bound computations per factory/scale/seed where the generated geometry is equivalent.
3. Defer expensive material/node/final object creation until after cheap geometric and relation checks when the exact same accepted asset can still be produced.
4. Reduce repeated failed retry work inside a stage by memoizing local negative placement/relation candidates without changing object availability or solve-step counts.
5. Investigate GC spikes as a secondary issue, but do not optimize it ahead of heavy addition apply cost.

Potential C++ rewrite candidates, after Python-level behavior-preserving work:

1. Numeric bbox min/max reductions and high-poly mesh bounds extraction.
2. AABB overlap and broad-phase collision checks.
3. Room/floor/wall bounds and containment checks over numeric arrays.
4. Batch candidate collision matrix construction for many boxes.
5. Constraint loss aggregation once inputs are already numeric arrays.

Do not start by rewriting `bpy` object creation/deletion, `spawn_asset`, material/node generation, or the simulated annealing solver control flow in C++.

## 2026-06-19 - Indoor solver timing instrumentation

### Round Goal

Add fine-grained, opt-in timing instrumentation for the indoor coarse solver without changing solver behavior, gin configuration, solve steps, object availability, or caching behavior.

### Changes

Added solver timing helpers:

- `infinigen/core/constraints/example_solver/timing.py`

Instrumented solver proposal steps:

- `SimulatedAnnealingSolver.retry_attempt_proposals`
- `SimulatedAnnealingSolver.step`
- `Addition.apply`
- `sample_rand_placeholder`

Timing is disabled by default. Enable it by setting:

```bash
INFINIGEN_PROFILE_TIMING=1
```

When enabled, the solver writes:

```text
<output_folder>/indoor_solver_timing.csv
```

The CSV records proposal-attempt rows with move generator name, move type, generator class when present, retry index, apply/evaluate/revert/accept/garbage-collect durations, total step duration, proposal success, and proposal acceptance.

### Notes

This round intentionally did not optimize or change generation logic.

`infinigen/assets/utils/bbox_from_mesh.py` has a suspected bug in `union_all_bbox`:

```python
maxs = pmaxs if maxs is None else np.maximum(pmins, mins)
```

This looks like it may use `pmins, mins` where `pmaxs, maxs` was intended. Do not fix as part of the timing round; add a focused sanity test in the next round before changing it.

## 2026-06-19 12:22 CST - Indoor coarse profiling baseline

### Round Goal

Establish an indoor coarse profiling baseline without optimizing source code.

### Changes

Added profiling helpers:

- `scripts/profile_indoor_solver.sh`
- `scripts/print_indoor_profile.py`

Added local handoff context:

- `AGENTS.md`
- `docs/WORKLOG.md`
- `docs/COMMANDS.md`
- `docs/PROFILE_RESULTS.md`
- `docs/NEXT_STEPS.md`

Updated ignore rules so generated profile and archive files are not committed.

### Commands

Run inside the container:

```bash
cd /opt/infinigen
source /root/miniconda3/etc/profile.d/conda.sh
conda activate infinigen
bash scripts/profile_indoor_solver.sh
python scripts/print_indoor_profile.py
```

### Result

This was a 30 minute bounded cProfile sampling run. It timed out during the `KitchenIslandFactory` stage, so it is not a complete profile.

Profile output path:

```text
/tmp/indoors_coarse.prof
```

Application-layer cumulative top 5:

1. `generate_indoors.py:206(solve_large)` - 1778.308s
2. `solve.py:144(solve_objects)` - 1778.287s
3. `annealing.py:252(step)` - 1776.001s
4. `annealing.py:187(retry_attempt_proposals)` - 1632.759s
5. `addition.py:88(apply)` - 1144.959s

Other notable hotspots:

- `sample_rand_placeholder` - 1007.360s
- `bbox_mesh_from_hipoly` - 962.604s
- `blender.py:236(garbage_collect)` - 684.869s
- `blender.py:290(delete)` - 449.876s
- `kitchen_space.py:236(create_asset)` - 322.605s

### Conclusion

The current indoor coarse baseline points to `solve_large`, `Solver.solve_objects`, simulated annealing `step`, proposal retry/apply/revert work, Blender object lifecycle costs, and `KitchenIslandFactory` as the main bottleneck area.

The bottleneck appears to be CPU / Python / Blender `bpy` / constraint-solving dominated rather than GPU/CUDA dominated.

`KitchenIslandFactory` single proposals taking roughly 55-88s are the clearest current hotspot. Kitchen appliances, `LargeShelf`, `Sofa`, and `TVStand` are also high-cost proposal areas. Constraint evaluation is not free, but appears secondary to Blender object lifecycle and asset factory creation costs in this bounded run.

### Next Step

Save this context, push the profiling baseline helpers to GitHub, then either run a complete profile or begin configuration-level speed experiments.
