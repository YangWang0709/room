# Profile Results

## BBox Mesh Timing CSV - 2026-06-19 14:57 CST

Profile type: 600s timeout sample with solver timing and bbox timing enabled.
This is not a complete profile.

Command:

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

The wrapper script `scripts/profile_indoor_solver.sh` could not be reused for
this sample because its existing output folder contained root-owned files from a
previous container run. The direct command above used the same seed, task, gin
file, and gin overrides with a fresh output folder.

Timing CSV path:

```text
outputs/profile_bbox_current/coarse/infinigen_bbox_timing.csv
```

Rows:

```text
507 bbox_mesh_from_hipoly rows
```

Analyzer command:

```bash
python scripts/analyze_bbox_timing.py outputs/profile_bbox_current/coarse/infinigen_bbox_timing.csv
```

### BBox Duration Totals

| duration_column | total (s) | pct_total |
| --- | ---: | ---: |
| spawn_placeholder_duration | 9.076 | 0.027 |
| spawn_asset_duration | 266.233 | 0.797 |
| union_all_bbox_duration | 0.075 | 0.000 |
| box_from_corners_duration | 1.175 | 0.004 |
| cleanup_collect_duration | 0.013 | 0.000 |
| delete_duration | 57.480 | 0.172 |
| total_duration | 334.068 | 1.000 |

### BBox Generator Totals Top 8

| generator_class | count | total (s) | mean (s) | max (s) |
| --- | ---: | ---: | ---: | ---: |
| LargeShelfFactory | 153 | 203.963 | 1.333 | 4.333 |
| SimpleBookcaseFactory | 94 | 42.881 | 0.456 | 0.747 |
| BathtubFactory | 127 | 32.831 | 0.259 | 0.692 |
| SimpleDeskFactory | 86 | 20.411 | 0.237 | 0.339 |
| BeverageFridgeFactory | 8 | 12.745 | 1.593 | 1.667 |
| OvenFactory | 21 | 10.850 | 0.517 | 0.542 |
| DishwasherFactory | 5 | 7.251 | 1.450 | 1.529 |
| FloorLampFactory | 13 | 3.135 | 0.241 | 0.363 |

### BBox C++ Judgment

`union_all_bbox` took 0.075s out of 334.068s of
`bbox_mesh_from_hipoly` time, or 0.023%. Do not prioritize default C++
integration for `bbox_min_max` / `union_all_bbox` from this sample. The useful
target remains Blender-heavy `spawn_asset` and deletion/factory lifecycle work,
especially `LargeShelfFactory` and related heavy addition attempts.

## Indoor Solver Timing CSV - 2026-06-19 13:25 CST

Profile type: 1800s timeout sample with solver timing enabled. This is not a complete profile.

Command:

```bash
INFINIGEN_PROFILE_TIMING=1 timeout 1800s bash scripts/profile_indoor_solver.sh
```

Timing CSV path:

```text
outputs/profile_indoor_baseline/coarse/indoor_solver_timing.csv
```

Container CSV path:

```text
/opt/infinigen/outputs/profile_indoor_baseline/coarse/indoor_solver_timing.csv
```

Rows:

```text
3061 proposal-attempt rows
```

Current use of these results:

- The next phase should be behavior-preserving optimization, guarded by A/B
  output comparison.
- Each optimization must pass `scripts/compare_indoor_outputs.py` against a
  baseline generated with the same seed, gin configuration, task, and output
  target.
- C++ should only be considered for pure computation kernels that do not touch
  `bpy`, random number generation, solver control flow, proposal order, or
  accept/reject logic.
- Reduced content, fewer rooms, fewer solve steps, disabled object classes, or
  lower quality should not be used as the main acceleration strategy.

The run timed out during `on_floor_freestanding_8 / kitchen_0/0` while attempting `KitchenIslandFactory`. The cProfile file `/tmp/indoors_coarse.prof` was not produced by this timeout run in the container, so this section is based on the timing CSV.

### generator_class apply_duration Top 10

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

### Slowest Proposal Attempts Top 10

All top 10 proposal attempts were `Addition(KitchenIslandFactory)`.

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

### Failed Proposal Clusters Top 10

Sorted by failed attempt count.

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

Sorted by wasted apply time, the main clusters are:

1. `KitchenIslandFactory` - 257.877s
2. `LargeShelfFactory` - 209.884s
3. `BeverageFridgeFactory` - 82.742s
4. `TableDiningFactory` - 72.458s
5. `LargePlantContainerFactory` - 61.787s

### Move Type Totals

| move_type | count | apply (s) | evaluate (s) | revert (s) | accept (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Addition | 2217 | 1112.264 | 109.877 | 178.612 | 0.000 |
| Resample | 114 | 27.863 | 2.396 | 8.204 | 0.662 |
| RelationPlaneChange | 217 | 14.650 | 10.944 | 0.074 | 0.000 |
| ReinitPoseMove | 111 | 3.942 | 14.598 | 0.042 | 0.000 |
| TranslateMove | 261 | 1.363 | 27.042 | 0.069 | 0.000 |
| RotateMove | 16 | 0.074 | 6.181 | 0.025 | 0.000 |
| Deletion | 22 | 0.003 | 1.198 | 0.069 | 0.530 |

### Bottleneck Judgment

`Addition.apply` dominates this timing sample. `evaluate_duration`, `revert_duration`, and `garbage_collect_duration` are not the primary bottleneck:

- total `apply_duration`: 1160.159s
- total `evaluate_duration`: 172.236s
- total `revert_duration`: 187.095s
- row-level `garbage_collect_duration`: 287.308s, with step-level duplication caveat
- max observed `garbage_collect_duration`: 22.470s

Garbage collection can spike and should stay visible in future profiling, but heavy failed addition apply work is the first target.

The most valuable next investigation is failed or unaccepted `Addition.apply`
work in heavy factories. The current top apply clusters are
`KitchenIslandFactory`, `LargeShelfFactory`, `TableDiningFactory`,
`BeverageFridgeFactory`, `LargePlantContainerFactory`,
`SimpleBookcaseFactory`, `SimpleDeskFactory`, `BathtubFactory`, and
`OvenFactory`.

Cheap preflight rejection is a promising but risky idea. It should not enter the
main path unless A/B evidence shows it preserves random number consumption,
proposal order, accept/reject decisions, and final outputs.

### Addition Breakdown

For the largest classes, `addition_sample_placeholder_duration` and `addition_spawn_placeholder_duration` carry nearly all Addition time:

- `KitchenIslandFactory`: sample 293.582s, spawn 293.508s, constraint 0.793s
- `LargeShelfFactory`: sample 220.599s, spawn 220.194s, constraint 11.255s
- `TableDiningFactory`: sample 82.026s, spawn 79.796s, constraint 2.522s
- `BeverageFridgeFactory`: sample 80.563s, spawn 78.851s, constraint 3.770s

This points to object/placeholder/factory generation work rather than constraint aggregation as the immediate bottleneck.

## Indoor Coarse Baseline - 2026-06-19

Profile type: 30 minute timeout sampling with cProfile. This is not a complete profile.

Profile file path:

```text
/tmp/indoors_coarse.prof
```

The `.prof` file itself is intentionally not committed.

## Top 5 Cumulative Functions

1. `generate_indoors.py:206(solve_large)` - 1778.308s
2. `solve.py:144(solve_objects)` - 1778.287s
3. `annealing.py:252(step)` - 1776.001s
4. `annealing.py:187(retry_attempt_proposals)` - 1632.759s
5. `addition.py:88(apply)` - 1144.959s

## Other Hotspots

- `sample_rand_placeholder` - 1007.360s
- `bbox_mesh_from_hipoly` - 962.604s
- `blender.py:236(garbage_collect)` - 684.869s
- `blender.py:290(delete)` - 449.876s
- `kitchen_space.py:236(create_asset)` - 322.605s

## Initial Bottleneck Judgment

Indoor coarse currently appears dominated by simulated annealing proposal / apply / revert work rather than GPU execution.

The expensive path includes repeated Blender `bpy` object creation and deletion, garbage collection, asset factory creation, node/material generation, placeholder sampling, high-poly mesh bound extraction, and follow-up constraint or validity evaluation.

The `KitchenIslandFactory` path is the clearest hotspot in this run, with individual steps observed around 55-88s before the timeout interrupted the profile. Kitchen appliances, `LargeShelf`, `Sofa`, and `TVStand` are also high-cost proposal sources.

Constraint evaluation has measurable cost, but in this bounded sample it appears secondary to Blender object lifecycle and factory asset creation.

## Next Profiling Need

Run a full indoor coarse profile if practical. If a full run is too slow, keep this timeout profile as the initial baseline and use the opt-in solver timing CSV to break down the proposal stack.

## Solver Timing CSV - 2026-06-19

Opt-in timing instrumentation now writes:

```text
<output_folder>/indoor_solver_timing.csv
```

Enable it before starting Python:

```bash
INFINIGEN_PROFILE_TIMING=1 bash scripts/profile_indoor_solver.sh
```

The CSV is proposal-attempt level. If a step has multiple retries, step-level fields such as `total_step_duration` and `garbage_collect_duration` repeat across retry-attempt rows. Do not sum those fields naively; stage-level context is needed for exact step-level aggregation because `iteration` resets across solver stages.

Important columns:

- `move_gen_func`, `move_type`, `generator_class`
- `retry`, `attempt_index`, `attempt_count`
- `proposal_succeeded`, `proposal_accepted`
- `apply_duration`, `evaluate_duration`, `revert_duration`, `accept_duration`
- `garbage_collect_duration`, `total_step_duration`
- `addition_sample_placeholder_duration`
- `addition_generator_init_duration`
- `addition_spawn_placeholder_duration`
- `addition_placeholder_finalize_duration`
- `addition_parse_scene_duration`
- `addition_state_update_duration`
- `addition_constraint_duration`

## Deferred Sanity Check

`infinigen/assets/utils/bbox_from_mesh.py::union_all_bbox` has suspicious `maxs` update logic:

```python
maxs = pmaxs if maxs is None else np.maximum(pmins, mins)
```

This should be verified with a focused multi-child bounding-box sanity test in the next round before any fix is made.

Fixing this may change generated geometry and must be treated as a separate
behavior change with its own sanity test and A/B equivalence validation.
