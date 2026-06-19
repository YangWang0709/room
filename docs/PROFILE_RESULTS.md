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

Run a full indoor coarse profile if practical. If a full run is too slow, keep this timeout profile as the initial baseline and add stage-level timing instrumentation around the solver/proposal stack.
