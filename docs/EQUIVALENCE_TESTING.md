# Equivalence Testing

## Purpose

The indoor speedup work must preserve the generated scene, not only reduce wall
time. The current bottleneck is dominated by failed or unaccepted
`Addition.apply` attempts, especially heavy factories such as
`KitchenIslandFactory` and `LargeShelfFactory`. Many tempting shortcuts can make
the run faster by changing what the solver tries or accepts. Those changes are
not behavior-preserving optimizations unless an A/B comparison shows that the
same seed, gin configuration, task, and output target still produce the same or
acceptably equivalent indoor scene.

The comparison baseline is the original behavior at a known commit. The
candidate is the optimized commit. The A/B output comparison is a guardrail for
future Python and C++ work.

## Behavior-Preserving Optimization

A behavior-preserving optimization keeps the solver's observable behavior
unchanged for the same inputs:

- Same seed.
- Same gin files and gin parameter overrides.
- Same task, especially `--task coarse` for the current priority.
- Same output target type.
- Same solve steps.
- Same room/object availability.
- Same proposal order and accept/reject logic.
- Same random number call order.
- Same Blender-visible side effects for accepted and rejected proposals.

The implementation can be faster internally, but it must not reduce scene
content or change quality as the main acceleration strategy.

## High-Risk Changes

These changes can alter generation results and must not be treated as ordinary
performance optimizations:

- Reducing solve steps.
- Disabling small objects.
- Disabling floating objects.
- Reducing the number of rooms.
- Changing constraint weights.
- Changing proposal order.
- Changing random number call order.
- Changing simulated annealing accept/reject logic.
- Skipping Blender object creation or deletion when later code depends on those
  side effects.
- Changing Blender data-block deletion mode or order. For example, using
  `bpy.data.batch_remove` for node groups may change Blender's internal
  deletion order or data-block lifecycle even when the removed object set is
  unchanged.
- Delaying or throttling `bpy.data` garbage collection. For example,
  `INFINIGEN_GC_NODE_GROUP_INTERVAL>1` can change node group data-block name
  allocation, lifetime, and residual data-block visibility before the next
  cleanup.
- Adding cheap preflight rejection that rejects a proposal earlier than the
  original path. Even when the rejection is logically correct, it can change
  random number consumption, proposal ordering, retry behavior, and final
  output.

Cheap preflight can only move into the main optimization path after it has been
shown not to alter random number order, proposal order, accept/reject decisions,
or final output.

## Required A/B Workflow

Every optimization must have an A/B validation record:

1. Generate a baseline output from the baseline commit.
2. Generate an optimized output from the candidate commit.
3. Use the same seed for both runs.
4. Use the same gin files and parameter overrides.
5. Use the same task, normally `--task coarse`.
6. Use distinct output folders.
7. Compare the two output folders with:

```bash
python scripts/compare_indoor_outputs.py outputs/a/coarse outputs/b/coarse
```

The comparison script recursively scans `.json` files, pairs them by relative
path, canonicalizes obvious run-specific fields, sorts known unordered tag
lists such as `tags`, `child_tags`, and `parent_tags`, compares numeric values
with a default tolerance of `1e-6`, and reports `PASS` or `FAIL`.

Useful tolerance controls:

```bash
python scripts/compare_indoor_outputs.py \
  --rtol 1e-6 \
  --atol 1e-6 \
  --max-diffs 20 \
  outputs/a/coarse \
  outputs/b/coarse
```

If the script prints `NO_COMPARABLE_JSON_FOUND`, the run is not a pass. Record
that no comparable JSON was available and add a better comparison target before
using the run as evidence.

## Node Group Batch Remove Experiment

`INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1` is an opt-in experiment only. When
unset, `GarbageCollect` keeps the original individual `node_groups.remove(obj)`
loop. The experiment only targets `bpy.data.node_groups`; meshes, materials,
textures, objects, and other targets continue to use the original individual
remove path.

The removed node group set and skip rules must stay unchanged:

- Skip data-blocks with users when `keep_in_use=True`.
- Skip names listed in `keep_names`.
- Skip names containing `(no gc)`.

Even with the same object set, `bpy.data.batch_remove` may change Blender's
internal deletion order or data-block lifecycle. It must therefore pass a same
seed/gin/task A/B before it can be considered behavior-preserving.

Use the full equivalence A/B:

```bash
EXPERIMENT_TIMEOUT_SECONDS=14400 \
bash scripts/run_gc_batch_remove_equivalence.sh
```

This script does not enable `INFINIGEN_PROFILE_TIMING`,
`INFINIGEN_PROFILE_GC`, `INFINIGEN_PROFILE_ASSET_FACTORY`, or
`INFINIGEN_PROFILE_BBOX`. By default it uses the normal 10-room indoor coarse
target:

```text
seed 0
task coarse
fast_solve.gin
compose_indoors.terrain_enabled=False
home_room_constraints.has_fewer_rooms=False
restrict_solving.solve_max_rooms=10
```

It writes:

```text
outputs/gc_batch_remove_equiv/baseline/coarse
outputs/gc_batch_remove_equiv/candidate_batch/coarse
```

Use the no-instrumentation wall-clock A/B after equivalence:

```bash
EXPERIMENT_TIMEOUT_SECONDS=14400 \
bash scripts/run_gc_batch_remove_walltime.sh
```

The wall-clock script writes `outputs/gc_batch_remove_walltime/summary.txt`
with per-run exit code, wall time, max RSS when available, speedup, and compare
status.

Both scripts support a single-room smoke:

```bash
EXPERIMENT_SMOKE_SINGLE_ROOM=1 \
EXPERIMENT_TIMEOUT_SECONDS=3600 \
bash scripts/run_gc_batch_remove_equivalence.sh
```

Smoke mode adds `singleroom.gin`, sets
`home_room_constraints.has_fewer_rooms=True`, and sets
`restrict_solving.solve_max_rooms=1`. A single-room PASS is useful only for
checking the script and catching obvious differences. It is not evidence that
the normal 10-room target is behavior-preserving or faster.

The 2026-06-19 single-room smoke completed for both new scripts. Equivalence
and wall-clock compares printed `FINAL: PASS` with `matched_json_file_count: 2`
and `numeric_max_abs_diff: 0`. The wall-clock smoke measured baseline
`163.339s` and candidate `163.462s`, or `0.999x`; max RSS was `2,357,896 KB`
for baseline and `2,350,572 KB` for candidate. No traceback, OOM, kill, or
segmentation fault was observed. This validates the harness only; the normal
10-room A/B remains required.

The 2026-06-19 smoke run produced a strong timing signal but did not validate
equivalence: baseline and candidate both timed out, `compare_indoor_outputs.py`
reported `NO_COMPARABLE_JSON_FOUND`, and the final compare status was `FAIL`.
Partial timing showed baseline `node_groups` remove duration at 366.131s and
candidate batch remove duration at 46.350s, while the candidate progressed
farther and removed more node groups. This is not comparable A/B evidence.

Acceptance requires all of the following:

1. The normal 10-room baseline and candidate both complete.
2. `compare_indoor_outputs.py` prints `FINAL: PASS`.
3. The no-heavy-instrumentation wall-clock script shows a speedup.

Do not use this experiment for concurrent throughput work. The current scope is
single indoor coarse scene speed only. Do not tune `manage_jobs.num_concurrent`
or run 32-thread/multiprocess benchmarks until single-scene
behavior-preserving optimization is stable and validated.

## Node Group GC Throttling Experiment

`INFINIGEN_GC_NODE_GROUP_INTERVAL` is an opt-in experiment only. When unset or
set to `1`, `GarbageCollect` keeps the original behavior and cleans
`bpy.data.node_groups` every time. Values greater than `1` skip node group
cleanup opportunities until the interval is due, while other targets such as
meshes, materials, and textures still use the normal cleanup path.

This experiment is risky because delaying node group removal can change Blender
data-block name allocation and can leave residual node groups visible to later
contexts. It is not a C++ optimization; it touches `bpy.data` lifecycle state.

Use the scripted A/B:

```bash
EXPERIMENT_TIMEOUT_SECONDS=1200 bash scripts/run_gc_node_group_experiment.sh
```

If the candidate differs from the baseline, times out without comparable JSON,
or shows obvious errors or memory growth, it must not become a mainline
optimization. If it passes, repeat with a longer profile and explicit memory
observation before considering a narrower opt-in production path.

### 2026-06-19 interval=20 result

The interval=20 smoke did not validate the optimization. Both baseline and
candidate timed out, `compare_indoor_outputs.py` found no comparable JSON, and
the candidate increased raw `node_groups_remove` from 369.071s to 443.414s
despite skipping 558 cleanup opportunities. This points to large burst removes
from broad deferred cleanup.

Do not promote interval=20 and do not continue by simply expanding the
interval. The current next step is attribution: identify the factories and node
group name prefixes that cause removal cost, then consider precise reuse,
caching, or reduced duplicate node group creation. Any such optimization must
be opt-in first and must pass the same seed/gin/task A/B workflow above.

## Attribution-Only Instrumentation

GC attribution timing is allowed as profiling instrumentation because it should
not change generated behavior. The current instrumentation records optional
`GarbageCollect` metadata such as `caller`, `generator_class`, `factory_seed`,
and `inst_seed`, plus bounded node group name prefix/sample summaries when
profiling is enabled.

Attribution data is not equivalence evidence by itself. It only identifies the
next optimization target. If attribution suggests a reusable node group prefix
or a factory-specific cache, validate the resulting candidate with the required
A/B workflow before treating it as behavior-preserving.

## Recommended Scale-Up

Start with a small smoke A/B to verify the comparison workflow itself. A
single-room run is acceptable for the smoke test, but it is only validating the
test harness. It is not evidence that reducing rooms is a valid optimization.

After the smoke test passes, repeat the A/B on the normal indoor coarse target,
including the full room count and normal solve steps used by the baseline.
Keep the scale-up focused on one scene until the behavior-preserving speedup is
accepted. Multi-scene scheduling, 32-thread throughput, and
`manage_jobs.num_concurrent` tuning belong to a later phase.

## Nondeterminism

If Blender or Infinigen shows unavoidable nondeterminism, record the exact
source and the observed differences. Do not mark a run as equivalent just
because the differences are inconvenient. Prefer a tighter targeted comparison
or a repeated-run baseline study over weakening the definition of pass.
