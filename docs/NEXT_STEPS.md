# Next Steps

## Suggested Next Round

1. Start with behavior-preserving Python/Blender optimizations, not a C++ rewrite.
2. Target the largest wasted Addition apply clusters first:
   - `KitchenIslandFactory` - 257.877s wasted apply in the 1800s timing sample.
   - `LargeShelfFactory` - 209.884s wasted apply.
   - `BeverageFridgeFactory` - 82.742s wasted apply.
   - `TableDiningFactory` - 72.458s wasted apply.
   - `LargePlantContainerFactory` - 61.787s wasted apply.
3. Add cheap preflight rejection for expensive additions before full asset spawn/finalization. Keep object availability, proposal probabilities, room count, and solve-step counts unchanged.
4. Cache deterministic placeholder, bbox, and high-poly mesh bound computations where the generated result is equivalent for the same factory parameters.
5. Investigate whether accepted assets can be finalized later while failed proposals use equivalent lightweight bounds/proxies for early checks. Validate visually and with timing before relying on this.
6. Memoize local negative placement/relation candidates inside a stage to avoid repeating the same expensive failed proposal path. Treat this carefully because it can affect random-path behavior if implemented too broadly.
7. Keep `garbage_collect_duration` visible, but do not make it the first target. In the timing CSV, apply dominates: 1160.159s apply versus 172.236s evaluate, 187.095s revert, and a row-level 287.308s garbage-collect sum with repeated step-level rows.

## C++ Rewrite Candidates

Only consider these after the Python/Blender behavior-preserving pass:

1. Numeric bbox min/max reductions and high-poly mesh bounds extraction.
2. AABB overlap and broad-phase collision checks.
3. Room/floor/wall bounds and containment checks over numeric arrays.
4. Batch collision matrix construction for many boxes or sampled candidates.
5. Constraint loss aggregation once inputs are already numeric arrays.

Avoid C++ rewrites for:

- `bpy` object creation/deletion
- `spawn_asset` or factory orchestration
- material/node generation
- the simulated annealing solver control flow

## Timing Commands

Run the timing profile:

```bash
INFINIGEN_PROFILE_TIMING=1 bash scripts/profile_indoor_solver.sh
```

If a full run is too slow, use a bounded sample:

```bash
INFINIGEN_PROFILE_TIMING=1 timeout 1800s bash scripts/profile_indoor_solver.sh
```

Analyze the CSV:

```bash
python scripts/analyze_indoor_timing.py
```

The default CSV path is:

```text
outputs/profile_indoor_baseline/coarse/indoor_solver_timing.csv
```

## Deferred Sanity Check

Add a focused sanity test for `infinigen/assets/utils/bbox_from_mesh.py::union_all_bbox` before changing it. The current `maxs` update logic looks suspicious and should be verified independently from timing work.

## Current Guardrails

- Keep original generation behavior available.
- Prefer opt-in `fast` / `isaac` config paths for speed experiments.
- Keep changes small enough to profile and roll back.
- Do not commit generated `outputs`, `.blend`, `.usd`, `.usdc`, `.prof`, or `.zip` files.
