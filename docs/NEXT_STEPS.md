# Next Steps

## Suggested Next Round

1. Keep the current optimization scope to a single indoor coarse scene. Do not
   run concurrent benchmarks, do not tune `manage_jobs.num_concurrent`, and do
   not investigate 32-thread or multi-process throughput until single-scene
   behavior-preserving optimization is stable and A/B validated.
2. Treat `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1` as the current opt-in
   cleanup candidate. The 2026-06-19 smoke lowered timeout-sample
   `node_groups` remove duration from 366.131s in the baseline to 46.350s in
   the candidate, while the candidate advanced farther and removed more node
   groups. This is a strong timing signal, not a validated optimization.
3. Run `scripts/run_gc_batch_remove_equivalence.sh` for the normal 10-room
   same seed/gin/task A/B before considering any mainline use. The run must
   complete on both sides and `scripts/compare_indoor_outputs.py` must print
   `FINAL: PASS`.
4. Run `scripts/run_gc_batch_remove_walltime.sh` after equivalence passes to
   measure wall-clock speed without heavy timing instrumentation. A profiling
   CSV speedup is not enough; the no-instrumentation wall-clock run must also
   improve.
5. Use `EXPERIMENT_SMOKE_SINGLE_ROOM=1` only as a harness smoke. Passing
   single-room A/B validates the script and catches obvious differences, but it
   does not prove the 10-room mainline target is behavior-preserving or faster.
   The 2026-06-19 single-room smoke did pass compare on both new scripts, but
   wall-clock was effectively flat at `0.999x`, so it is not speed evidence for
   the full target.
6. If the normal 10-room A/B still cannot finish, keep the candidate opt-in and
   record the timeout as not complete. Require comparable coarse JSON before
   accepting behavior preservation.
7. Keep `LargeShelfFactory` and repeated node group prefixes as the root-cause
   attribution target. The attribution sample measured `LargeShelfFactory` at
   139.219s and 5,661 removed node groups; repeated prefixes included
   `nodegroup_tagged_cube`, `nodegroup_division_board`,
   `nodegroup_screw_head`, and `nodegroup_side_board`.
8. Do not continue expanding `INFINIGEN_GC_NODE_GROUP_INTERVAL` experiments.
   The interval=20 smoke was not a valid speedup: both baseline and candidate
   timed out, no comparable JSON was produced, and raw `node_groups_remove`
   increased from 369.071s to 443.414s. Naive deferred node group cleanup
   creates large burst removes and is not the main path.
9. If batch remove passes A/B, run a longer profile and explicit output
   equivalence validation before promoting the opt-in path. If it fails A/B or
   still lacks comparable JSON, shift back to precise reuse, caching, or reduced
   duplicate node group creation in the dominant factories instead of broad
   delayed cleanup.
10. Inspect the factory paths and node tree generation for the factories that
   dominate node group churn, starting with `LargeShelfFactory`, then
   `SimpleBookcaseFactory`, `SimpleDeskFactory`, `KitchenIslandFactory`, and
   the kitchen appliance factories observed in the batch smoke.
11. If repeated node group prefixes are semantically equivalent for the same
   factory parameters, consider an opt-in reuse/cache/reduce-duplicate-creation
   experiment. Preserve node group identity and Blender-visible lifecycle
   behavior unless same seed/gin/task A/B proves equivalence.
12. If inspection shows the node group names are highly parameterized or not
   safely reusable, continue with a finer cleanup strategy instead of broad
   delayed cleanup. Any cleanup strategy must remain opt-in until it passes
   A/B comparison.
13. Keep the standalone geometry kernels out of the default indoor solver
   path. The 2026-06-19 bbox sample measured `union_all_bbox` at 0.075s out of
   334.068s of `bbox_mesh_from_hipoly` time, or 0.023%, so do not prioritize
   default C++ bbox integration from current evidence.
14. Treat `AssetFactory.spawn_asset` / factory lifecycle as the current first
   investigation target. The latest GC sample measured
   `garbage_collect_context_duration` at 177.848s out of 278.502s of
   `spawn_asset` time, or 63.859%; `create_asset_duration` was secondary at
   99.383s, or 35.685%, and `delete_placeholder_duration` was only 0.228s, or
   0.082%.
15. Treat `bpy.data.node_groups` removal as the current first behavior-preserving
   experiment target. The GC target sample measured 183.972s in target
   `exit_cleanup`, 183.378s in `remove_duration`, and 181.131s in
   `node_groups` alone. `enter_snapshot` was only 0.422s, and broad scan time
   excluding remove was about 0.594s.
16. Use the opt-in `INFINIGEN_GC_NODE_GROUP_INTERVAL` experiment only behind the
   environment variable. Unset or `1` keeps default behavior; values greater
   than `1` throttle only `bpy.data.node_groups` cleanup. This may change
   Blender data-block name allocation or leave residual node groups, so it must
   pass same seed/gin/task A/B before being treated as usable.
17. Do not treat the interval=20 smoke as a validated speedup. Both runs timed
   out, `compare_indoor_outputs.py` found no comparable JSON, and raw
   `node_groups_remove` increased from 369.071s to 443.414s in the partial
   sample despite 558 skipped cleanup opportunities. Prefer targeted node group
   attribution, reuse, or cache investigation instead of changing the interval.
18. If trying GC scope adjustment, node-group-specific cleanup, less frequent
   cleanup, deferred cleanup, batch cleanup, or factory bbox/cache reuse,
   preserve random number consumption, proposal order, accept/reject decisions,
   object parent/transform/delete semantics, and final output. Validate with
   `scripts/compare_indoor_outputs.py`.
19. Use `INFINIGEN_PROFILE_GC=1` or `INFINIGEN_PROFILE_TIMING=1` to collect
   `infinigen_gc_timing.csv`, then run `scripts/analyze_gc_timing.py`.
20. Use `INFINIGEN_PROFILE_ASSET_FACTORY=1` or `INFINIGEN_PROFILE_TIMING=1` to
   collect `infinigen_asset_factory_timing.csv`, then run
   `scripts/analyze_asset_factory_timing.py`.
21. Use `INFINIGEN_PROFILE_BBOX=1` or `INFINIGEN_PROFILE_TIMING=1` to collect
   `infinigen_bbox_timing.csv`, then run `scripts/analyze_bbox_timing.py` only
   if bbox behavior changes are under consideration.
22. Run `python -m pytest tests/test_geometry_kernels.py -q` and
   `python scripts/bench_geometry_kernels.py` after every kernel change.
23. When build environments cannot compile the geometry extension, use
   `INFINIGEN_DISABLE_GEOMETRY_CPP=True python -m pip install -e .` and verify
   the NumPy fallback remains importable.
24. Consider an opt-in bbox C++ experiment only if a later timing sample
   contradicts the current 0.023% `union_all_bbox` share.
25. Before any solver-facing use, run same seed/gin/task A/B with
   `scripts/compare_indoor_outputs.py` and require matching coarse JSON.
26. Do not fix the suspected `union_all_bbox` max update while doing this
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
- `GarbageCollect` / `bpy.data` cleanup
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
