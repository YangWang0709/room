# Worklog

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
