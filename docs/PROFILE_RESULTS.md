# Profile Results

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

The CSV is proposal-attempt level. If a step has multiple retries, step-level fields such as `total_step_duration` and `garbage_collect_duration` repeat across rows for that iteration; group by `iteration` and take one value when doing step-level aggregates.

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
