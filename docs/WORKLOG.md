# Worklog

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
