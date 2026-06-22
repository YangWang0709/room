# Next Steps

## Latest Populate Clutter Focus

The current Isaac-inspected speed configuration is:

```text
INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1
INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1
restrict_solving.solve_max_rooms=10
populate_doors.door_chance=0
```

After the solver / GC and `LargeShelfFactory` child node-group work, the next
bottleneck focus is final `populate_assets` clutter. A complete 10-room proxy
log showed `populate_assets` at about `3296.8s` / `54.9m` for `222` items.
The highest-priority populate factory is now `NatureShelfTrinketsFactory`,
with `BookStackFactory` and `LargePlantContainerFactory` as the next targets.

Use the new NatureShelfTrinkets instrumentation only when collecting evidence:

```bash
INFINIGEN_PROFILE_NATURE_SHELF_TRINKETS=1 python -m infinigen_examples.generate_indoors ...
python scripts/analyze_nature_shelf_trinkets.py \
  outputs/<run>/coarse/infinigen_nature_shelf_trinkets_timing.csv
```

For isolated internal cost attribution, use the targeted benchmark instead of
rerunning a full 10-room scene:

```bash
INFINIGEN_PROFILE_NATURE_SHELF_TRINKETS=1 \
python scripts/bench_nature_shelf_trinkets_factory.py \
  --samples 100 \
  --seed 0 \
  --output_folder outputs/bench_nature_shelf_trinkets_100
python scripts/analyze_nature_shelf_trinkets.py \
  outputs/bench_nature_shelf_trinkets_100/infinigen_nature_shelf_trinkets_timing.csv
```

The latest 100-sample targeted run completed with `100` successful samples and
`0` failures. It is only a microbenchmark for
`NatureShelfTrinketsFactory.create_asset()` internals, not a complete-scene
walltime result. In that sample, `stable_pose_duration` accounted for
`95.971s` / `54.1%` of measured `create_asset` time, and
`obj2trimesh_duration` accounted for `26.151s` / `14.7%`. Together the
stable-pose pipeline accounted for `122.121s` / `68.9%`, while
`base_factory_spawn_duration` accounted for `46.610s` / `26.3%`.

Top duration factories were `ClamFactory` (`49.970s`), `MusselFactory`
(`27.341s`), and `CoralFactory` (`25.904s`). `ClamFactory` and
`MusselFactory` were dominated by `compute_stable_poses()` on about `528k`
faces per sample. `CoralFactory` used much larger meshes, about `3.45m`
average faces, and was often dominated by `obj2trimesh` conversion rather than
`compute_stable_poses()` itself.

The diagnostic `stable_pose_cache_candidate_key` had `75` keys, `75` unique
keys, and `0` repeats. Exact stable-pose cache likely has limited benefit for
this sample. Material / texture / node-group creation is not the first
duration target in this benchmark, even though creature factories still create
most materials and node groups.

Recommended next order:

1. Do not rerun a full 10-room scene just to collect NatureShelfTrinkets
   internals. The bounded 1800s sample timed out inside `[solve_large]`, did
   not reach final `populate_assets`, and wrote no Nature timing CSV.
2. Use the targeted benchmark for more samples or specific seeds when the goal
   is internal cost attribution. Keep interpreting it as a microbenchmark, not
   complete-scene walltime.
3. First inspect stable-pose-heavy paths, starting with `ClamFactory`, then
   `MusselFactory`. Look at the geometry fed into
   `trimesh.poses.compute_stable_poses()` and whether a separate opt-in
   simplification path can preserve visual quality.
4. Inspect `CoralFactory` separately for `obj2trimesh` conversion cost on very
   large meshes before changing stable-pose logic.
5. Do not start with exact stable-pose cache unless a later full-scene or
   larger targeted sample shows repeated exact candidate keys. Any cache must
   be opt-in.
6. If a later larger sample shows `base_factory.spawn_asset` dominating,
   inspect the concrete wrapped base factory before broad wrapper changes.
7. If a later CSV shows repeated material, texture, or node-group names with high
   creation counts, design a separate opt-in reuse experiment for the narrowest
   repeated template only.
8. Keep `BookStackFactory` and `LargePlantContainerFactory` as second-priority
   populate targets after the NatureShelfTrinkets evidence is clearer.
9. Do not run concurrent benchmarks in this phase.
10. Do not reduce clutter count or scene complexity unless a later quality gate
   explicitly allows it.
11. Do not change solver behavior, proposal order, accept/reject behavior, or
   random number flow.

## Latest LargeShelf Child Reuse Short Sample

A first-round opt-in `LargeShelfFactory` child node group reuse experiment was
implemented behind:

```bash
INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1
```

Default behavior is unchanged when the variable is unset. The first reuse set
is limited to `nodegroup_screw_head`, `nodegroup_side_board`,
`nodegroup_bottom_board`, and `nodegroup_back_board`.

Do not reuse these in the next step:

| prefix | reason |
| --- | --- |
| top-level `geometry_nodes` | per-shelf arrays, scalar defaults, and material objects |
| `nodegroup_division_board` | tag-support path and inclusive nested timing |
| `nodegroup_tagged_cube` | `MaskTag` / `TAG_support_surface` attribute risk |

The bounded 900s short A/B used seed `0`, `fast_solve.gin`,
`restrict_solving.solve_max_rooms=10`,
`populate_doors.door_chance=0`,
`INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1`, and
`INFINIGEN_PROFILE_SHELF_NODEGROUPS=1`. Both sides timed out as intended at
900s, so this is not a complete coarse profile and not a quality gate.

Results from the matched 163-spawn sample:

| metric | baseline | candidate |
| --- | ---: | ---: |
| CSV data rows | 5,918 | 5,918 |
| `LargeShelfFactory` spawns | 163 | 163 |
| actual node groups created | 5,918 | 3,363 |
| mean actual node groups per spawn | 36.307 | 20.632 |
| `spawn_summary` total duration | 60.096s | 36.718s |
| cache hit rate | 0.000% | 96.744% |

Target prefix duration dropped from `21.417s` to `0.538s`. No traceback, OOM,
or segfault was observed.

Recommended next order:

1. Run a full 10-room Isaac static quality validation with both opt-in speed
   switches enabled:
   `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1` and
   `INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1`.
2. Keep the static Isaac quality configuration at
   `restrict_solving.solve_max_rooms=10` and
   `populate_doors.door_chance=0` so door panels are not generated while door
   openings remain.
3. Treat the 900s result as timing evidence only; do not accept the reuse path
   until the full quality validation has no obvious scene bug and Isaac Sim can
   use the exported static environment.
4. Do not expand reuse to `nodegroup_division_board`, `nodegroup_tagged_cube`,
   or top-level `geometry_nodes` before the child-only path passes.
5. Keep `batch_remove` as the main deletion-cost switch. The reuse experiment
   addresses repeated creation cost that `batch_remove` does not solve.
6. Do not continue bbox C++ work or concurrent optimization from the current
   evidence.

## Latest LargeShelf Node Group Timing Sample

A bounded `LargeShelfFactory` shelf node group timing sample was collected on
2026-06-21 with `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1`,
`INFINIGEN_PROFILE_SHELF_NODEGROUPS=1`, seed `0`, `fast_solve.gin`,
`restrict_solving.solve_max_rooms=10`, and
`populate_doors.door_chance=0`.

The valid run timed out at `3600s`, so it is not a complete coarse profile.
It still wrote:

```text
outputs/profile_shelf_nodegroups_seed0/coarse/infinigen_shelf_nodegroup_timing.csv
```

The CSV has `24,524` data rows, including `23,083` child
`nodegroup_create` rows and `1,441` `spawn_summary` rows. Mean created node
groups per `LargeShelfFactory` spawn was `17.019`, including one top-level
`geometry_nodes` tree per shelf.

Prefix duration totals:

| prefix | calls | total duration |
| --- | ---: | ---: |
| `nodegroup_division_board` | 5,629 | 278.151s |
| `nodegroup_screw_head` | 5,629 | 125.246s |
| `nodegroup_side_board` | 3,170 | 43.601s |
| `nodegroup_tagged_cube` | 5,629 | 37.736s |
| `nodegroup_bottom_board` | 1,585 | 25.735s |
| `nodegroup_back_board` | 1,441 | 23.490s |

The first-round reuse candidates
(`nodegroup_screw_head`, `nodegroup_side_board`,
`nodegroup_bottom_board`, and `nodegroup_back_board`) accounted for
`218.072s`, about `6.1%` of the `3600s` timeout window. This is enough to
justify a small opt-in reuse experiment. The inclusive prefix total
(`533.958s`) double-counts nested work because `nodegroup_division_board`
includes nested `nodegroup_tagged_cube` and `nodegroup_screw_head` creation.

`LargeShelfFactory` remains the next single-scene speed investigation target,
but only for opt-in shelf child node group reuse. The repeated high-frequency
shelf node group prefixes are created in
`infinigen/assets/objects/shelves/large_shelf.py` and
`infinigen/assets/objects/shelves/utils.py`.

The active path is:

```text
LargeShelfBaseFactory.create_asset()
  surface.add_geomod(obj, geometry_nodes, apply=True, input_kwargs=obj_params)
    geometry_nodes(...)
      nodegroup_side_board()
      nodegroup_back_board()
      nodegroup_bottom_board()
      nodegroup_division_board(..., tag_support=True)
        nodegroup_tagged_cube()
        nodegroup_screw_head()
```

All of these child groups currently use `singleton=False`, so each call creates
a fresh Blender node group datablock. `batch_remove` remains useful as an
opt-in deletion-cost switch, but it does not reduce repeated creation cost.

Use the new instrumentation only when needed:

```bash
INFINIGEN_PROFILE_SHELF_NODEGROUPS=1 python -m infinigen_examples.generate_indoors ...
python scripts/analyze_shelf_nodegroups.py \
  outputs/<run>/coarse/infinigen_shelf_nodegroup_timing.csv
```

Recommended next order:

1. Keep `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1` as a separate opt-in
   deletion-cost switch; do not change its behavior.
2. Add a separate opt-in reuse experiment for pure shelf child groups,
   starting with `nodegroup_screw_head`,
   `nodegroup_side_board`, `nodegroup_bottom_board`, and
   `nodegroup_back_board`.
3. Treat `nodegroup_tagged_cube` and `nodegroup_division_board` as more
   sensitive second-phase candidates because they participate in tag-support
   behavior.
4. Do not reuse the top-level `geometry_nodes` tree in the first experiment;
   it embeds per-shelf sampled arrays and material objects.
5. Do not continue bbox C++ optimization from current evidence:
   `union_all_bbox` was only about `0.023%` of the measured bbox path.
6. Do not run concurrent benchmarks or tune multi-process throughput in this
   phase.
7. Do not change door logic. Default Isaac validation should keep
   `populate_doors.door_chance=0` so door panels are not generated and door
   openings remain.

## Latest Full Baseline Determinism Check

A full 10-room baseline repeat was completed to test whether the existing full
baseline is deterministic under the current strict JSON gate.

Compared folders:

```text
outputs/gc_batch_remove_equiv/baseline/coarse
outputs/determinism_full_baseline_b/coarse
```

The new baseline B run used the original baseline behavior: seed `0`, task
`coarse`, `fast_solve.gin`, `compose_indoors.terrain_enabled=False`,
`home_room_constraints.has_fewer_rooms=False`, and
`restrict_solving.solve_max_rooms=10`. `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS`
was unset, and heavy profiling timing env vars were not enabled.

Baseline B completed with `MAIN TOTAL` `4:25:03.044391`. No timeout,
traceback, OOM, killed, or segfault marker was found.

`scripts/compare_indoor_outputs.py` result:

```text
matched_json_file_count: 2
DIFFERENT MaskTag.json numeric_max_abs_diff=1
  $.back.bottom: left 22, right 21
  $.front.top: left 21, right 22
SAME solve_state.json numeric_max_abs_diff=0
numeric_max_abs_diff: 1
FINAL: FAIL
```

The full baseline A/A repeats the same `MaskTag.json` label-ID swap seen in
the full baseline-vs-batch A/B. This means the `MaskTag.json` swap is not
currently attributable to `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1`.

Static blend comparison was run only as diagnostic evidence:

```text
STATIC_SCENE_FAIL
USD_RELEVANT_DIFF: yes
UNUSED_DATABLOCK_DIFF: no
UNUSED_DATABLOCK_DIFF_ONLY: no
static_scene_diff_count: 60
unused_datablock_diff_count: 0
```

Because both single-room and full baseline-vs-baseline comparisons can fail the
saved-blend static scene diagnostic, saved `.blend` static-scene differences
alone are not a valid batch-remove rejection reason.

Updated next diagnostic order:

1. Keep `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1` opt-in; do not mainline it.
2. Do not run walltime for acceptance while the strict/relevant gate is
   undefined or failing under baseline A/A.
3. Treat `solve_state.json SAME` as the strongest current evidence that the
   solver state is stable for the full baseline repeat.
4. Root-cause or explicitly scope the baseline nondeterminism in
   `MaskTag.json` label-ID assignment and saved-blend linked scene summaries.
5. Do not relax `scripts/compare_indoor_outputs.py` in the same round as an
   optimization. Any gate split must be a separate compare-policy proposal.
6. If a future gate distinguishes strict JSON, Isaac static scene, and
   GT/segmentation equivalence, calibrate that gate against baseline A/A first.
7. Only after the relevant baseline-calibrated gate is defined should
   baseline-vs-batch be used to decide whether batch remove changes the scene.

## Latest Determinism Ablation

Before judging `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1`, confirm baseline
self-determinism. The new tools are:

```bash
python scripts/compare_blend_static_scene.py outputs/a/coarse outputs/b/coarse
EXPERIMENT_SMOKE_SINGLE_ROOM=1 EXPERIMENT_TIMEOUT_SECONDS=3600 bash scripts/run_determinism_ablation.sh
```

The 2026-06-20 smoke A/A completed without timeout or error markers. Both
baseline A/A and candidate A/A passed `scripts/compare_indoor_outputs.py`:
`MaskTag.json` and `solve_state.json` were `SAME`, and
`numeric_max_abs_diff` was `0`.

Both smoke A/A pairs failed `scripts/compare_blend_static_scene.py` with
`STATIC_SCENE_FAIL` and `USD_RELEVANT_DIFF: yes`. The differences were linked
scene differences, not unused-datablock-only differences. They included
wall/floor/ceiling material slot changes and some wall mesh vertex/edge/polygon
count changes, while object counts and object type counts matched.

This means the saved `.blend` differences in the previous full
baseline-vs-batch A/B cannot yet be attributed to batch remove. At least in
smoke mode, baseline same-seed A/A is JSON-deterministic but not static-blend
deterministic under the new comparator.

Next diagnostic order:

1. Keep batch remove opt-in and do not mainline it.
2. Do not run walltime for acceptance while the relevant equivalence gate is
   failing or undefined.
3. Use the completed full 10-room baseline A/A recorded above as the current
   baseline-calibration evidence.
4. Because full baseline-vs-baseline shows the same MaskTag label-ID swap and
   linked static-scene diagnostic differences, redefine the strict/static gates
   before blaming batch remove.
5. If a later baseline-calibrated gate passes for baseline-vs-baseline but
   fails for baseline-vs-batch, treat batch remove as a likely source of scene
   change and continue root-cause analysis.
6. Keep unused Blender datablock differences separate from USD-relevant linked
   scene differences. Unused node group differences alone should not be treated
   the same as object, mesh, material-slot, transform, or linked node-tree
   differences.
7. If `MaskTag.json` proves to affect only GT annotation and not the linked
   static scene, consider a separately reviewed Isaac-static-scene-specific
   equivalence gate. Do not relax `compare_indoor_outputs.py` in the same
   round as an optimization.

## Latest MaskTag Investigation

The full 10-room `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1` A/B completed and
has a clear runtime signal: baseline `MAIN TOTAL` was `4:11:49.774668`, while
candidate_batch was `3:07:38.553985`. The signal is not accepted as a validated
speedup because strict equivalence still failed.

The only comparable JSON failure was `MaskTag.json`: `front.top` and
`back.bottom` swapped tag IDs `21` and `22`. `solve_state.json` was equal after
the compare script's canonicalization, so this does not by itself show a solver
layout change. `MaskTag.json` is a tag-to-integer-label mapping used for
semantic tag lookup and GT/tag-segmentation interpretation; the inspected USD
export and Isaac Sim static import paths do not read it.

Do not conclude that the current candidate is Isaac-static-equivalent. A
read-only Blender summary of the saved baseline-vs-batch blends found matching
object names and counts but different mesh totals, several
mesh/material/transform differences, and extra candidate node groups. However,
the later full baseline A/A also failed the static blend diagnostic with linked
scene differences, so saved `.blend` static differences are not currently a
batch-remove-specific rejection signal. Before any walltime run or promotion
of batch remove, define a baseline-calibrated relevant gate or root-cause the
baseline nondeterminism.

If a future run has only a pure `MaskTag.json` ID-order difference and no
USD-relevant scene differences, it may be worth proposing separate validation
gates for strict equivalence, Isaac static scene equivalence, and GT annotation
equivalence. That should be a separate compare-policy proposal, not an
immediate relaxation.

## Suggested Next Round

1. Keep the current optimization scope to a single indoor coarse scene. Do not
   run concurrent benchmarks, do not tune `manage_jobs.num_concurrent`, and do
   not investigate 32-thread or multi-process throughput until single-scene
   behavior-preserving optimization is stable and A/B validated.
2. Treat `INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1` as the current opt-in
   cleanup candidate only. The 2026-06-19 smoke lowered timeout-sample
   `node_groups` remove duration from 366.131s in the baseline to 46.350s in
   the candidate, while the candidate advanced farther and removed more node
   groups. This remains a strong timing signal, not a validated optimization.
3. Treat the 2026-06-20 full 10-room A/B as a completed equivalence failure.
   Both baseline and candidate completed, but `compare_indoor_outputs.py`
   printed `FINAL: FAIL`: `solve_state.json` was `SAME`, while
   `MaskTag.json` differed with `numeric_max_abs_diff: 1` at
   `$.back.bottom` and `$.front.top`.
4. Do not run or interpret a full wall-clock A/B for batch remove until the
   normal 10-room equivalence run prints `FINAL: PASS`. The 2026-06-20
   wall-clock run was intentionally skipped because the equivalence gate failed.
5. Investigate the `MaskTag.json` difference before any further promotion of
   batch remove. Determine whether the front/back count swap is a real visible
   behavior change, a comparison-scope issue, or a Blender data-block lifecycle
   effect from `bpy.data.batch_remove`. This investigation found that
   `MaskTag.json` itself is a tag-label mapping, but the saved blends also
   differ in mesh/material/transform summaries. Any code change or revised
   comparison policy must be followed by a fresh same seed/gin/task 10-room
   A/B.
6. Use `EXPERIMENT_SMOKE_SINGLE_ROOM=1` only as a harness smoke. Passing
   single-room A/B validates the script and catches obvious differences, but it
   does not prove the 10-room mainline target is behavior-preserving or faster.
   The 2026-06-19 single-room smoke did pass compare on both new scripts, but
   wall-clock was effectively flat at `0.999x`, so it is not speed evidence for
   the full target.
7. If reducing iteration cost for diagnosis, clearly label any smaller run as a
   smoke or near-mainline diagnostic. A singleroom PASS or reduced-room PASS
   must not replace the normal 10-room behavior-preserving proof.
8. Keep `LargeShelfFactory` and repeated node group prefixes as the root-cause
   attribution target. The attribution sample measured `LargeShelfFactory` at
   139.219s and 5,661 removed node groups; repeated prefixes included
   `nodegroup_tagged_cube`, `nodegroup_division_board`,
   `nodegroup_screw_head`, and `nodegroup_side_board`.
9. Do not continue expanding `INFINIGEN_GC_NODE_GROUP_INTERVAL` experiments.
   The interval=20 smoke was not a valid speedup: both baseline and candidate
   timed out, no comparable JSON was produced, and raw `node_groups_remove`
   increased from 369.071s to 443.414s. Naive deferred node group cleanup
   creates large burst removes and is not the main path.
10. If batch remove later passes full A/B, run
   `scripts/run_gc_batch_remove_walltime.sh` to measure wall-clock speed without
   heavy timing instrumentation before promoting the opt-in path. If the
   `MaskTag.json` difference persists, first determine whether it is a pure
   GT/tag-label mapping difference or accompanied by USD-relevant static scene
   differences. Keep batch remove opt-in/rejected for mainline use until the
   relevant equivalence gate passes, and shift back to precise reuse, caching,
   or reduced duplicate node group creation in the dominant factories instead
   of broad delayed cleanup if the scene differences remain unexplained.
11. Inspect the factory paths and node tree generation for the factories that
   dominate node group churn, starting with `LargeShelfFactory`, then
   `SimpleBookcaseFactory`, `SimpleDeskFactory`, `KitchenIslandFactory`, and
   the kitchen appliance factories observed in the batch smoke.
12. If repeated node group prefixes are semantically equivalent for the same
   factory parameters, consider an opt-in reuse/cache/reduce-duplicate-creation
   experiment. Preserve node group identity and Blender-visible lifecycle
   behavior unless same seed/gin/task A/B proves equivalence.
13. If inspection shows the node group names are highly parameterized or not
   safely reusable, continue with a finer cleanup strategy instead of broad
   delayed cleanup. Any cleanup strategy must remain opt-in until it passes
   A/B comparison.
14. Keep the standalone geometry kernels out of the default indoor solver
   path. The 2026-06-19 bbox sample measured `union_all_bbox` at 0.075s out of
   334.068s of `bbox_mesh_from_hipoly` time, or 0.023%, so do not prioritize
   default C++ bbox integration from current evidence.
15. Treat `AssetFactory.spawn_asset` / factory lifecycle as the current first
   investigation target. The latest GC sample measured
   `garbage_collect_context_duration` at 177.848s out of 278.502s of
   `spawn_asset` time, or 63.859%; `create_asset_duration` was secondary at
   99.383s, or 35.685%, and `delete_placeholder_duration` was only 0.228s, or
   0.082%.
16. Treat `bpy.data.node_groups` removal as the current first behavior-preserving
   experiment target. The GC target sample measured 183.972s in target
   `exit_cleanup`, 183.378s in `remove_duration`, and 181.131s in
   `node_groups` alone. `enter_snapshot` was only 0.422s, and broad scan time
   excluding remove was about 0.594s.
17. Use the opt-in `INFINIGEN_GC_NODE_GROUP_INTERVAL` experiment only behind the
   environment variable. Unset or `1` keeps default behavior; values greater
   than `1` throttle only `bpy.data.node_groups` cleanup. This may change
   Blender data-block name allocation or leave residual node groups, so it must
   pass same seed/gin/task A/B before being treated as usable.
18. Do not treat the interval=20 smoke as a validated speedup. Both runs timed
   out, `compare_indoor_outputs.py` found no comparable JSON, and raw
   `node_groups_remove` increased from 369.071s to 443.414s in the partial
   sample despite 558 skipped cleanup opportunities. Prefer targeted node group
   attribution, reuse, or cache investigation instead of changing the interval.
19. If trying GC scope adjustment, node-group-specific cleanup, less frequent
   cleanup, deferred cleanup, batch cleanup, or factory bbox/cache reuse,
   preserve random number consumption, proposal order, accept/reject decisions,
   object parent/transform/delete semantics, and final output. Validate with
   `scripts/compare_indoor_outputs.py`.
20. Use `INFINIGEN_PROFILE_GC=1` or `INFINIGEN_PROFILE_TIMING=1` to collect
   `infinigen_gc_timing.csv`, then run `scripts/analyze_gc_timing.py`.
21. Use `INFINIGEN_PROFILE_ASSET_FACTORY=1` or `INFINIGEN_PROFILE_TIMING=1` to
   collect `infinigen_asset_factory_timing.csv`, then run
   `scripts/analyze_asset_factory_timing.py`.
22. Use `INFINIGEN_PROFILE_BBOX=1` or `INFINIGEN_PROFILE_TIMING=1` to collect
   `infinigen_bbox_timing.csv`, then run `scripts/analyze_bbox_timing.py` only
   if bbox behavior changes are under consideration.
23. Run `python -m pytest tests/test_geometry_kernels.py -q` and
   `python scripts/bench_geometry_kernels.py` after every kernel change.
24. When build environments cannot compile the geometry extension, use
   `INFINIGEN_DISABLE_GEOMETRY_CPP=True python -m pip install -e .` and verify
   the NumPy fallback remains importable.
25. Consider an opt-in bbox C++ experiment only if a later timing sample
   contradicts the current 0.023% `union_all_bbox` share.
26. Before any solver-facing use, run same seed/gin/task A/B with
   `scripts/compare_indoor_outputs.py` and require matching coarse JSON.
27. Do not fix the suspected `union_all_bbox` max update while doing this
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
