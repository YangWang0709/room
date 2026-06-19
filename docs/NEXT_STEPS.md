# Next Steps

## Suggested Next Round

1. Keep the standalone geometry kernels out of the default indoor solver
   path until an opt-in integration is implemented and validated.
2. Use `INFINIGEN_PROFILE_BBOX=1` or `INFINIGEN_PROFILE_TIMING=1` to collect
   `infinigen_bbox_timing.csv`, then run `scripts/analyze_bbox_timing.py`.
3. Decide whether `union_all_bbox` is worth a C++ experiment only from the
   measured `union_all_bbox_duration / total_duration` share. If it is low,
   prioritize `spawn_asset`, object deletion, and factory lifecycle work
   instead.
   The 2026-06-19 600s sample measured `union_all_bbox` at 0.075s out of
   334.068s of `bbox_mesh_from_hipoly` time, or 0.023%, so do not prioritize
   default C++ bbox integration from current evidence.
4. Run `python -m pytest tests/test_geometry_kernels.py -q` and
   `python scripts/bench_geometry_kernels.py` after every kernel change.
5. When build environments cannot compile the geometry extension, use
   `INFINIGEN_DISABLE_GEOMETRY_CPP=True python -m pip install -e .` and verify
   the NumPy fallback remains importable.
6. Consider an opt-in experiment in
   `infinigen/assets/utils/bbox_from_mesh.py`, limited first to replacing the
   numeric `points.min(axis=0)` / `points.max(axis=0)` portion with
   `bbox_min_max`, only if bbox timing justifies it.
7. If adding that opt-in path, gate it behind a flag or experimental config so
   the baseline generation behavior remains the default.
8. Before any solver-facing use, run same seed/gin/task A/B with
   `scripts/compare_indoor_outputs.py` and require matching coarse JSON.
9. Do not fix the suspected `union_all_bbox` max update while doing this
   opt-in kernel integration. Treat that as a separate behavior change.

## Existing Optimization Guidance

1. Start the behavior-preserving optimization phase by running an A/B baseline
   and candidate comparison with `scripts/compare_indoor_outputs.py`.
2. Keep the same seed, gin files, gin parameter overrides, task, output target,
   solve steps, room count, and object availability for each A/B.
3. Start with behavior-preserving Python/Blender optimizations, not a C++
   rewrite.
4. Target the largest wasted `Addition.apply` clusters first:
   - `KitchenIslandFactory` - 257.877s wasted apply in the 1800s timing sample.
   - `LargeShelfFactory` - 209.884s wasted apply.
   - `BeverageFridgeFactory` - 82.742s wasted apply.
   - `TableDiningFactory` - 72.458s wasted apply.
   - `LargePlantContainerFactory` - 61.787s wasted apply.
5. Investigate cheap preflight rejection only as a risky candidate. It cannot
   enter the main path unless it preserves random number consumption, proposal
   order, accept/reject decisions, and final output.
6. Cache deterministic placeholder, bbox, and high-poly mesh bound computations
   only where the generated result is equivalent for the same factory
   parameters.
7. Investigate whether accepted assets can be finalized later while failed
   proposals use equivalent lightweight bounds/proxies for early checks.
   Validate visually, with timing, and with A/B output comparison before relying
   on this.
8. Memoize local negative placement/relation candidates inside a stage only if
   it does not change random-path behavior, retry order, or final output.
9. Keep `garbage_collect_duration` visible, but do not make it the first target.
   In the timing CSV, apply dominates: 1160.159s apply versus 172.236s
   evaluate, 187.095s revert, and a row-level 287.308s garbage-collect sum with
   repeated step-level rows.

Do not use reduced content, fewer rooms, fewer solve steps, disabled object
classes, or lower quality as the main acceleration strategy.

## C++ Rewrite Candidates

Only consider these after the Python/Blender behavior-preserving pass, and only
for pure computation kernels that do not touch `bpy`, random numbers, solver
control flow, proposal order, or accept/reject logic:

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
- random number sampling
- proposal / accept / reject logic

See `docs/CPP_REWRITE_CANDIDATES.md` before writing any C++.

## A/B Equivalence Commands

Compare two coarse outputs:

```bash
python scripts/compare_indoor_outputs.py outputs/a/coarse outputs/b/coarse
```

With explicit tolerances:

```bash
python scripts/compare_indoor_outputs.py \
  --rtol 1e-6 \
  --atol 1e-6 \
  --max-diffs 20 \
  outputs/a/coarse \
  outputs/b/coarse
```

If the script prints `NO_COMPARABLE_JSON_FOUND`, the validation failed because
there was no comparable JSON evidence.

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
- Every optimization must pass A/B equivalence validation before being treated
  as mainline.
- Prefer opt-in `fast` / `isaac` config paths for speed experiments.
- Keep changes small enough to profile and roll back.
- Use C++ only for pure computation kernels.
- Do not trade away generated content or quality for speed.
- Do not commit generated `outputs`, `.blend`, `.usd`, `.usdc`, `.prof`, or `.zip` files.
